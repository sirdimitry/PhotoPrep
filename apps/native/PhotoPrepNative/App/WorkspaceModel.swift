import SwiftUI
import AppKit
import UniformTypeIdentifiers
import CoreGraphics
import ImageIO

enum RetouchTool: String, CaseIterable {
    case brush
    case eraser
}

struct RetouchPass: Identifiable, Sendable {
    let id: UUID
    let strokes: [MaskStroke]
    let createdAt: Date
    let modelID: String

    init(id: UUID = UUID(), strokes: [MaskStroke], createdAt: Date = Date(), modelID: String = "lama") {
        self.id = id
        self.strokes = strokes
        self.createdAt = createdAt
        self.modelID = modelID
    }
}

struct PhotoEditState: Sendable {
    var mask: [MaskStroke] = []
    var passes: [RetouchPass] = []
    var sourceIdentity: SourceIdentity?
    var sourceChanged = false
    var view = SessionView()
    var crop: SessionCrop?
    var logo: SessionLogo?
    var cropUndo: [SessionCrop?] = []
}

/// LRU cache of pixel results. Recipes/history live separately, so evicting a
/// result never removes an edit; it only forces replay.
@MainActor
final class PixelCache {
    private struct Entry {
        let image: StraightImage
        let bytes: Int
        var lastUsed: Date
    }
    private var entries: [String: Entry] = [:]
    private(set) var bytes = 0
    let budgetBytes: Int

    init(budgetBytes: Int = 384 * 1024 * 1024) {
        self.budgetBytes = budgetBytes
    }

    private func maskFingerprint(_ strokes: [MaskStroke]) -> String {
        var hash: UInt64 = 1469598103934665603
        func mix(_ value: UInt64) { hash = (hash ^ value) &* 1099511628211 }
        for stroke in strokes {
            mix(stroke.width.bitPattern)
            mix(stroke.erase ? 1 : 0)
            for point in stroke.points {
                mix(point.x.bitPattern)
                mix(point.y.bitPattern)
            }
        }
        return String(format: "%016llx", hash)
    }

    func key(source: SourceIdentity, passes: [RetouchPass], pass: Int) -> String {
        let recipe = passes.prefix(pass + 1).map {
            "\($0.id.uuidString)|\($0.modelID)|\(maskFingerprint($0.strokes))"
        }.joined(separator: ";")
        return "\(source.sha256)|\(source.size)|\(source.mtimeNS)|\(recipe)|\(pass)"
    }

    func get(source: SourceIdentity, passes: [RetouchPass], pass: Int) -> StraightImage? {
        let key = key(source: source, passes: passes, pass: pass)
        guard var entry = entries[key] else { return nil }
        entry.lastUsed = Date()
        entries[key] = entry
        return entry.image
    }

    func put(_ image: StraightImage, source: SourceIdentity, passes: [RetouchPass], pass: Int) {
        let key = key(source: source, passes: passes, pass: pass)
        if let old = entries.removeValue(forKey: key) { bytes -= old.bytes }
        let cost = image.width * image.height * 4
        entries[key] = Entry(image: image, bytes: cost, lastUsed: Date())
        bytes += cost
        while bytes > budgetBytes, let oldest = entries.min(by: { $0.value.lastUsed < $1.value.lastUsed })?.key {
            if let removed = entries.removeValue(forKey: oldest) { bytes -= removed.bytes }
        }
    }

    func contains(source: SourceIdentity, passes: [RetouchPass], pass: Int) -> Bool {
        entries[key(source: source, passes: passes, pass: pass)] != nil
    }

    func invalidate(_ photo: URL) {
        for key in entries.keys where key.hasPrefix(photo.path + "#") {
            if let removed = entries.removeValue(forKey: key) { bytes -= removed.bytes }
        }
    }

    func clear() {
        entries.removeAll()
        bytes = 0
    }

    var count: Int { entries.count }
}

private struct PersistedLogo: Codable {
    var path: String
    var bookmark: Data
    var mode: String
    var width: Double
    var opacity: Double
    var x: Double
    var y: Double
    var enabled: Bool
}

@MainActor
final class WorkspaceModel: ObservableObject {
    @Published private(set) var photos: [PhotoHeader] = []
    @Published var selected: URL? {
        didSet {
            guard oldValue != selected else { return }
            if let oldValue { editStates[oldValue, default: PhotoEditState()].mask = strokes }
            cancelPreview()
            cancelRetouch(wait: true)
            resultImage = nil
            passCount = 0
            crop = nil
            logo = nil
            cropMode = false
            retouchError = nil
            showingAfter = false
            if let selected {
                canvasView = editStates[selected]?.view ?? SessionView()
                strokes = []
                Task { @MainActor [weak self] in await self?.validateIdentityAndLoad(selected) }
                requestPreview()
            } else {
                strokes = []
            }
        }
    }

    private func validateIdentityAndLoad(_ url: URL) async {
        let current = try? await Task.detached(priority: .userInitiated) {
            try SourceIdentity.capture(url)
        }.value
        guard selected == url else { return }
        var state = editStates[url] ?? PhotoEditState()
        if let known = state.sourceIdentity, let current, known != current {
            // Keep the recipes and masks until the user explicitly rebases or
            // resets; only the pixel cache and displayed result are invalid.
            state.sourceChanged = true
            editStates[url] = state
            strokes = state.mask
            passCount = state.passes.count
            resultImage = nil
            pixelCache.clear()
            cacheBytes = 0
            retouchError = "source_changed"
            sourceNeedsDecision = true
            return
        }
        if state.sourceIdentity == nil, let current { state.sourceIdentity = current }
        state.sourceChanged = false
        editStates[url] = state
        sourceNeedsDecision = false
        strokes = state.mask
        passCount = state.passes.count
        crop = state.crop
        logo = state.logo
        loadLogoAsset(state.logo)
        canvasView = state.view
        if let current, !state.passes.isEmpty {
            resultImage = pixelCache.get(source: current, passes: state.passes, pass: state.passes.count - 1)
        } else {
            resultImage = nil
        }
        cacheBytes = pixelCache.bytes
        showingAfter = resultImage != nil
        if resultImage == nil && !state.passes.isEmpty { startRestoreIfNeeded() }
    }

    @Published private(set) var preview: PhotoPreview?
    @Published private(set) var canvasView = SessionView()
    @Published var showMask = true
    @Published private(set) var logoAsset: CGImage?
    @Published private(set) var importBusy = false
    @Published private(set) var previewBusy = false
    @Published private(set) var retouchBusy = false
    @Published private(set) var issue: ResourceFailure?
    @Published private(set) var pressure: MemoryPressure = .normal
    @Published var strokes: [MaskStroke] = []
    @Published var tool: RetouchTool = .brush
    @Published var brushWidth: Double = 0.06
    @Published private(set) var resultImage: StraightImage?
    @Published var showingAfter = false
    @Published private(set) var retouchPhase = ""
    @Published private(set) var retouchError: String?
    @Published private(set) var passCount = 0
    @Published private(set) var cacheBytes = 0
    @Published private(set) var sessionReadOnly: String?
    @Published private(set) var sourceNeedsDecision = false
    @Published private(set) var sessionOutputWidth = 1136
    @Published private(set) var sessionOutputHeight = 710
    @Published private(set) var isDirty = false
    @Published var cropMode = false
    @Published private(set) var crop: SessionCrop?
    private var cropSessionOriginal: SessionCrop?
    private var cropSessionDirty: Bool = false
    @Published private(set) var logo: SessionLogo?
    @Published private(set) var exportBusy = false
    @Published private(set) var exportDone = 0
    @Published private(set) var exportTotal = 0
    @Published private(set) var exportError: String?
    private var sessionURL: URL?
    private var sessionTask: Task<Void, Never>?
    private var sessionGeneration = UUID()
    private var exportCancellation: CancellationFlag?
    private var savePanel: NSSavePanel?
    private var sessionScope: URL?
    private var pressureHistory: [[String: Any]] = []
    private var persistedLogo: SessionLogo?
    private var persistedLogoBookmark: Data?
    private var logoAccessURL: URL?
    private var persistLogoTask: Task<Void, Never>?
    private static let logoDefaultsKey = "v1/logo"
    private var authorizedSessionFolders: Set<String> = []

    var busy: Bool { importBusy || previewBusy || retouchBusy }

    private let decoder = PreviewDecoder()
    private let imageDecoder = StraightImageDecoder()
    private let worker = InferenceWorkerClient()
    private let policy = ResourcePolicy()
    private var importTask: Task<Void, Never>?
    private var previewTask: Task<Void, Never>?
    private var retouchTask: Task<Void, Never>?
    private var importGeneration = UUID()
    private var previewGeneration = UUID()
    private var retouchGeneration = UUID()
    private var maskRevision = 0
    private var editRevision = 0
    private var retouchActiveID: UUID?
    private var retouchCancellation: CancellationFlag?
    private var editStates: [URL: PhotoEditState] = [:]
    private let pixelCache = PixelCache()
    private var restoreTask: Task<Void, Never>?
    private var pressureSource: DispatchSourceMemoryPressure?

    static weak var current: WorkspaceModel?

    init() {
        Self.current = self
        loadPersistedLogo()
        let source = DispatchSource.makeMemoryPressureSource(eventMask: [.normal, .warning, .critical], queue: .main)
        source.setEventHandler { [weak self] in
            guard let self else { return }
            // Capture data synchronously in the handler; reading it from a
            // later Task can observe a different/coalesced event.
            let data = self.pressureSource?.data ?? []
            Task { @MainActor [weak self] in
                guard let self else { return }
                let next: MemoryPressure = data.contains(.critical) ? .critical : data.contains(.warning) ? .warning : .normal
                self.memoryPressure(next, raw: data.rawValue)
            }
        }
        source.resume()
        pressureSource = source
        #if DEBUG
        if CommandLine.arguments.contains("--photoprep-e1-history-selftest") {
            Task { @MainActor [weak self] in await self?.runCumulativeHistorySelfTest() }
        } else if CommandLine.arguments.contains("--photoprep-e1-cache-source-selftest") {
            Task { @MainActor [weak self] in await self?.runCacheSourceChangeSelfTest() }
        } else if CommandLine.arguments.contains("--photoprep-e1-session-replay-selftest") {
            Task { @MainActor [weak self] in await self?.runSessionReplaySelfTest() }
        } else if CommandLine.arguments.contains("--photoprep-v1-export-selftest") {
            Task { @MainActor [weak self] in await self?.runV1ExportSelfTest() }
        } else if CommandLine.arguments.contains("--photoprep-session-state-selftest") {
            Task { @MainActor [weak self] in await self?.runSessionStateSelfTest() }
        } else if CommandLine.arguments.contains("--photoprep-e1-full-stress") {
            Task { @MainActor [weak self] in await self?.runFullStress() }
        } else if CommandLine.arguments.contains("--photoprep-e1-pressure-active-selftest") {
            Task { @MainActor [weak self] in await self?.runActivePressureSelftest() }
        } else if let url = DebugLaunchOptions.openPhoto {
            NSLog("PhotoPrep debug open: %@", url.path)
            DispatchQueue.main.async { [weak self] in self?.importURLs([url]) }
        }
        #endif
    }

    func openSessionPanel() {
        guard !busy, pressure == .normal else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.json]
        #if DEBUG
        if let directory = DebugLaunchOptions.panelDirectory { panel.directoryURL = directory }
        #endif
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch self.confirmUnsaved("Открытие другого набора") {
                case .discard: self.openSession(url)
                case .save: self.saveSessionPanel()
                case .cancel: return
                }
            }
        }
    }

    func saveSessionPanel() {
        guard !photos.isEmpty, !busy, pressure == .normal else { return }
        let panel = NSSavePanel()
        savePanel = panel
        panel.allowedContentTypes = [.json]
        #if DEBUG
        if let directory = DebugLaunchOptions.panelDirectory { panel.directoryURL = directory }
        #endif
        panel.nameFieldStringValue = sessionURL?.lastPathComponent ?? "Untitled.photoprep.json"
        if panel.directoryURL == nil {
            panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
        }
        let response = panel.runModal()
        savePanel = nil
        guard response == .OK else { return }
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
        guard let initial = panel.url ?? documents?.appendingPathComponent(panel.nameFieldStringValue) else {
            retouchError = "session_save_failed"
            return
        }
        var url = initial
        if !url.lastPathComponent.lowercased().hasSuffix(".photoprep.json") {
            url = url.deletingPathExtension().appendingPathExtension("photoprep.json")
        }
        Task { @MainActor [weak self] in await self?.saveSession(to: url) }
    }

    var hasUnsavedEdits: Bool { isDirty }

    enum UnsavedDecision { case save, discard, cancel }

    func confirmUnsaved(_ action: String) -> UnsavedDecision {
        guard isDirty else { return .discard }
        let alert = NSAlert()
        alert.messageText = "Несохранённые правки"
        alert.informativeText = "\(action): сохранить изменения перед продолжением?"
        alert.addButton(withTitle: "Сохранить")
        alert.addButton(withTitle: "Не сохранять")
        alert.addButton(withTitle: "Отмена")
        switch alert.runModal() {
        case .alertFirstButtonReturn: return .save
        case .alertSecondButtonReturn: return .discard
        default: return .cancel
        }
    }

    func openSession(_ url: URL) {
        sessionTask?.cancel()
        let token = UUID()
        sessionGeneration = token
        retouchError = nil
        NSLog("E1.5 session open start %@", url.path)
        sessionTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let document = try await Task.detached(priority: .userInitiated) {
                    try SessionCodec.load(url)
                }.value
                NSLog("E1.5 session decoded photos=%d output=%dx%d", document.photos.count, document.outputWidth, document.outputHeight)
                try Task.checkCancellation()
                var headers: [PhotoHeader] = []
                for photo in document.photos {
                    try Task.checkCancellation()
                    do {
                        let header = try await self.decoder.header(url: photo.url)
                        headers.append(header)
                    } catch {
                        NSLog("Session photo access failed %@: %@", photo.url.path, String(describing: error))
                    }
                }
                NSLog("E1.5 session headers=%d", headers.count)
                guard token == self.sessionGeneration, !Task.isCancelled else { return }
                if headers.count < document.photos.count {
                    if !self.authorizedSessionFolders.contains(url.deletingLastPathComponent().path) {
                        self.sessionTask = nil
                        self.requestSessionFolderAccess(for: url, token: token)
                        return
                    }
                    self.sessionTask = nil
                    self.retouchError = "session_incomplete"
                    NSLog("E1.5 session incomplete: %d of %d photos accessible", headers.count, document.photos.count)
                    return
                }
                self.cancelImport()
                self.cancelPreview()
                self.cancelRetouch()
                self.sourceNeedsDecision = false
                self.sessionURL = url
                self.sessionReadOnly = document.readOnlyReason
                self.sessionOutputWidth = document.outputWidth
                self.sessionOutputHeight = document.outputHeight
                self.photos = headers
                var states: [URL: PhotoEditState] = [:]
                for photo in document.photos {
                    var state = PhotoEditState()
                    state.mask = photo.mask
                    state.passes = photo.passes.map { RetouchPass(strokes: $0.strokes, modelID: $0.modelID) }
                    state.view = photo.view
                    state.crop = photo.crop
                    state.logo = photo.logo
                    states[photo.url] = state
                }
                self.editStates = states
                self.sessionTask = nil
                if let selected = document.selected, headers.contains(where: { $0.url == selected }) {
                    self.selected = nil
                    self.selected = selected
                } else {
                    self.selected = headers.first?.url
                }
                self.isDirty = false
                if document.readOnly {
                    self.retouchError = "session_read_only"
                    self.sessionReadOnly = document.readOnlyReason
                }
            } catch is CancellationError {
                return
            } catch {
                guard token == self.sessionGeneration else { return }
                self.sessionTask = nil
                self.retouchError = (error as? SessionError)?.code ?? "session_invalid"
                NSLog("E1.5 session open error %@", String(describing: error))
            }
        }
    }

    func saveSession(to url: URL) async {
        guard sessionReadOnly == nil, !sourceNeedsDecision else {
            retouchError = "session_read_only"
            return
        }
        var workspace = SessionWorkspace(version: 3, photos: [], selected: selected,
                                         outputWidth: sessionOutputWidth, outputHeight: sessionOutputHeight)
        workspace.photos = photos.map { photo in
            let state = editStates[photo.url] ?? PhotoEditState()
            return SessionPhoto(url: photo.url, view: state.view, mask: state.mask,
                                passes: state.passes.map { SessionPass(strokes: $0.strokes, modelID: $0.modelID) },
                                crop: state.crop, logo: state.logo)
        }
        let result = await Task.detached(priority: .userInitiated) { () -> Result<Void, Error> in
            do {
                try SessionCodec.save(workspace, to: url)
                return .success(())
            } catch {
                return .failure(error)
            }
        }.value
        switch result {
        case .success:
            sessionURL = url
            isDirty = false
            retouchError = nil
        case .failure(let error):
            retouchError = (error as? SessionError)?.code ?? "session_save_failed"
        }
    }

    private func requestSessionFolderAccess(for session: URL, token: UUID) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = session.deletingLastPathComponent()
        panel.message = "Разрешите доступ к папке с фотографиями этого набора."
        panel.prompt = "Разрешить"
        panel.begin { [weak self] response in
            guard response == .OK, let folder = panel.url else { return }
            Task { @MainActor [weak self] in
                guard let self, token == self.sessionGeneration else { return }
                let accessed = folder.startAccessingSecurityScopedResource()
                NSLog("Session folder access %@ = %@", folder.path, accessed ? "yes" : "no")
                if accessed {
                    self.sessionScope?.stopAccessingSecurityScopedResource()
                    self.sessionScope = folder
                    self.authorizedSessionFolders.insert(folder.path)
                }
                self.openSession(session)
            }
        }
    }

    func importFolder() {
        guard !busy, pressure == .normal else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Открыть папку"
        panel.begin { [weak self] response in
            guard response == .OK, let folder = panel.url else { return }
            let keys: [URLResourceKey] = [.isRegularFileKey, .isSymbolicLinkKey, .contentTypeKey]
            let urls = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: keys,
                                                                      options: [.skipsHiddenFiles])) ?? []
            let images = urls.filter { url in
                guard let values = try? url.resourceValues(forKeys: Set(keys)),
                      values.isRegularFile == true, values.isSymbolicLink != true,
                      let type = values.contentType else { return false }
                return type.conforms(to: .image) && (type.conforms(to: .jpeg) || type.conforms(to: .png) ||
                       type.conforms(to: .tiff) || type.conforms(to: .bmp) || type.conforms(to: .webP))
            }.sorted { $0.lastPathComponent < $1.lastPathComponent }
            Task { @MainActor [weak self] in self?.importURLs(images) }
        }
    }

    func importPhotos() {
        guard !importBusy, !retouchBusy, pressure == .normal else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.jpeg, .png, .tiff, .bmp, .webP]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        #if DEBUG
        if let directory = DebugLaunchOptions.panelDirectory { panel.directoryURL = directory }
        #endif
        panel.begin { [weak self] response in
            guard response == .OK else { return }
            let urls = panel.urls
            Task { @MainActor [weak self] in self?.importURLs(urls) }
        }
    }

    func importURLs(_ urls: [URL]) {
        guard !importBusy, pressure == .normal else { return }
        cancelImport()
        let token = UUID()
        importGeneration = token
        importBusy = true
        issue = nil
        importTask = Task { [weak self, decoder] in
            var added: [PhotoHeader] = []
            var failure: ResourceFailure?
            let capacity = max(0, 10_000 - (self?.photos.count ?? 0))
            for url in urls.prefix(capacity) {
                do {
                    try Task.checkCancellation()
                    let header = try await decoder.header(url: url)
                    added.append(header)
                } catch is CancellationError { break }
                catch {
                    failure = error as? ResourceFailure ?? .invalidImage
                    #if DEBUG
                    print("PhotoPrep import failed for \(url.lastPathComponent): \(error)")
                    #endif
                }
            }
            guard let self, !Task.isCancelled, token == self.importGeneration else { return }
            var known = Set(self.photos.map(\.url))
            let fresh = added.filter { known.insert($0.url).inserted }
            self.photos += fresh
            if !fresh.isEmpty { self.isDirty = true }
            self.importBusy = false
            self.importTask = nil
            self.issue = failure
            if self.selected == nil { self.selected = self.photos.first?.url }
        }
    }

    func closePhoto(_ url: URL) {
        guard !busy else { return }
        let wasSelected = selected == url
        let index = photos.firstIndex { $0.url == url }
        photos.removeAll { $0.url == url }
        editStates.removeValue(forKey: url)
        if wasSelected {
            if let index, !photos.isEmpty {
                selected = photos[min(index, photos.count - 1)].url
            } else {
                selected = photos.first?.url
            }
        } else if photos.isEmpty {
            selected = nil
        }
        if photos.isEmpty {
            preview = nil
            resultImage = nil
            strokes = []
            crop = nil
            logo = nil
            logoAsset = nil
        }
        isDirty = !photos.isEmpty
    }

    private func requestPreview() {
        cancelPreview()
        preview = nil
        guard let selected, pressure == .normal else { return }
        let token = UUID()
        previewGeneration = token
        previewBusy = true
        issue = nil
        previewTask = Task { [weak self, decoder] in
            do {
                let result = try await decoder.preview(url: selected)
                guard let self, !Task.isCancelled, token == self.previewGeneration else { return }
                self.preview = result
                self.previewBusy = false
                self.previewTask = nil
            } catch {
                guard let self, !Task.isCancelled, token == self.previewGeneration else { return }
                self.issue = error as? ResourceFailure ?? .invalidImage
                self.previewBusy = false
                self.previewTask = nil
            }
        }
    }

    func cancelImport() {
        importGeneration = UUID()
        importTask?.cancel()
        importTask = nil
        importBusy = false
    }

    func cancelPreview() {
        previewGeneration = UUID()
        previewTask?.cancel()
        previewTask = nil
        previewBusy = false
    }

    private(set) var allowTermination = false
    private var terminationDialogOpen = false

    @MainActor
    func confirmTermination() -> Bool {
        if allowTermination { return true }
        guard !terminationDialogOpen else { return false }
        terminationDialogOpen = true
        defer { terminationDialogOpen = false }
        let alert = NSAlert()
        alert.messageText = "Закрыть PhotoPrep?"
        alert.informativeText = "Завершить работу и закрыть приложение? Несохранённые результаты обработки будут потеряны."
        alert.addButton(withTitle: "Нет")
        alert.addButton(withTitle: "Да")
        alert.alertStyle = .warning
        NSApp.activate(ignoringOtherApps: true)
        let approved = alert.runModal() == .alertSecondButtonReturn
        if approved { allowTermination = true }
        return approved
    }

    /// Used by window close/termination and destructive collection actions.
    func cancel() {
        cancelImport()
        cancelPreview()
        cancelRetouch(wait: true)
    }

    func memoryPressure(_ pressure: MemoryPressure, raw: UInt = 0) {
        self.pressure = pressure
        let event: [String: Any] = [
            "timestamp": ISO8601DateFormatter().string(from: Date()),
            "pressure": "\(pressure)", "raw": raw,
            "resident": SystemMemory.physicalFootprintBytes() ?? 0,
            "available": SystemMemory.availableBytes() ?? 0,
            "photos": photos.count, "selected": selected?.lastPathComponent ?? "",
            "busy": retouchBusy, "phase": retouchPhase,
            "preview": preview != nil, "result": resultImage != nil,
            "dirty": isDirty
        ]
        pressureHistory.append(event)
        if pressureHistory.count > 50 { pressureHistory.removeFirst(pressureHistory.count - 50) }
        #if DEBUG
        writeDebugJSON(pressureHistory, name: "pressure-events")
        NSLog("E1.7 pressure event %@ raw=%llu resident=%llu available=%llu busy=%@ phase=%@",
              "\(pressure)", raw, SystemMemory.physicalFootprintBytes() ?? 0,
              SystemMemory.availableBytes() ?? 0, retouchBusy ? "yes" : "no", retouchPhase)
        #endif
        if pressure == .normal {
            issue = nil
            if selected != nil && preview == nil { requestPreview() }
            return
        }
        cancelPreview()
        cancelRetouch(wait: true)
        preview = nil
        issue = .memoryPressure
        retouchPhase = ""
    }

    func clear() {
        cancel()
        selected = nil
        photos.removeAll()
        preview = nil
        resultImage = nil
        strokes = []
        editStates.removeAll()
        pixelCache.clear()
        cacheBytes = 0
        passCount = 0
        sessionReadOnly = nil
        sessionURL = nil
        issue = nil
        retouchError = nil
        showingAfter = false
    }

    func newCollection() {
        clear()
    }

    func suspend() {
        cancel()
        preview = nil
    }

    func resume() {
        if selected != nil, preview == nil, pressure == .normal { requestPreview() }
    }

    // MARK: - Retouch

    var displayImage: CGImage? {
        if showingAfter, let result = resultImage { return result.cgImage() }
        return preview?.image
    }

    var cropImage: CGImage? { resultImage?.cgImage() ?? preview?.image }

    var canUndoStroke: Bool { !strokes.isEmpty && !retouchBusy }
    var canProcess: Bool {
        selected != nil && !strokes.isEmpty && !retouchBusy && !importBusy
            && pressure == .normal && sessionReadOnly == nil
            && !(selected.flatMap { editStates[$0]?.sourceChanged } ?? false)
    }

    func addStroke(_ stroke: MaskStroke) {
        guard sessionReadOnly == nil, !retouchBusy, !stroke.points.isEmpty else { return }
        strokes.append(stroke)
        maskRevision += 1
        editRevision += 1
        if let selected { editStates[selected, default: PhotoEditState()].mask = strokes }
        isDirty = true
        showingAfter = false
        retouchError = nil
    }

    func undoLastStroke() {
        guard sessionReadOnly == nil, !retouchBusy, !strokes.isEmpty else { return }
        strokes.removeLast()
        maskRevision += 1
        editRevision += 1
        if let selected { editStates[selected, default: PhotoEditState()].mask = strokes }
        isDirty = true
        showingAfter = false
        retouchError = nil
    }

    func clearMask() {
        guard sessionReadOnly == nil, !retouchBusy, !strokes.isEmpty else { return }
        strokes.removeAll()
        maskRevision += 1
        editRevision += 1
        if let selected { editStates[selected, default: PhotoEditState()].mask = [] }
        isDirty = true
        showingAfter = false
        retouchError = nil
    }

    func processMask() {
        guard canProcess, retouchActiveID == nil, let url = selected else { return }
        if let header = photos.first(where: { $0.url == url }) {
            do {
                try policy.admitRetouch(
                    pixels: UInt64(header.width) * UInt64(header.height),
                    residentBytes: SystemMemory.physicalFootprintBytes() ?? 0,
                    availableBytes: SystemMemory.availableBytes(),
                    pressure: pressure
                )
            } catch {
                retouchError = "memory"
                return
            }
        }
        let snapshot = strokes
        let priorPasses = editStates[url]?.passes ?? []
        let priorResult = resultImage
        let maskRevisionAtStart = maskRevision
        let editRevisionAtStart = editRevision
        let jobID = UUID()
        let cancellation = CancellationFlag()
        retouchCancellation = cancellation
        retouchGeneration = jobID
        retouchActiveID = jobID
        retouchBusy = true
        retouchPhase = "preparing"
        retouchError = nil
        showingAfter = false

        retouchTask = Task { [weak self] in
            guard let self else { return }
            let timingsStart = Date()
            var decodeEnd = timingsStart
            var prepareEnd = timingsStart
            var workerStart = timingsStart
            var workerEnd = timingsStart
            var compositeEnd = timingsStart
            var jobDirectory: URL?
            defer {
                if let jobDirectory { try? FileManager.default.removeItem(at: jobDirectory) }
            }
            do {
                let identity = try await Task.detached(priority: .userInitiated) {
                    try SourceIdentity.capture(url)
                }.value
                try Task.checkCancellation()
                var currentState = self.editStates[url] ?? PhotoEditState()
                if let known = currentState.sourceIdentity, known != identity {
                    currentState.passes = []
                    currentState.mask = []
                    currentState.sourceIdentity = identity
                    self.editStates[url] = currentState
                    self.pixelCache.clear()
                    self.cacheBytes = 0
                    throw RetouchFailure.sourceChanged
                }
                if currentState.sourceIdentity == nil {
                    currentState.sourceIdentity = identity
                    self.editStates[url] = currentState
                }
                let source: StraightImage
                if priorPasses.isEmpty {
                    source = try await self.imageDecoder.decode(url: url)
                } else if let priorResult {
                    source = priorResult
                } else {
                    source = try await self.replayPasses(url: url, passes: priorPasses,
                                                         identity: identity, cancellation: cancellation,
                                                         maskRevision: maskRevisionAtStart,
                                                         editRevision: editRevisionAtStart)
                }
                decodeEnd = Date()
                try Task.checkCancellation()
                let (mask, prepared) = try await Task.detached(priority: .userInitiated) {
                    let mask = MaskRenderer.render(width: source.width, height: source.height, strokes: snapshot, isCancelled: { cancellation.isCancelled })
                    guard !cancellation.isCancelled else { throw RetouchFailure.cancelled }
                    guard !MaskRenderer.isEmpty(mask) else { throw RetouchFailure.emptyMask }
                    return (mask, try RetouchPreprocessor.prepare(source: source, mask: mask, isCancelled: { cancellation.isCancelled }))
                }.value
                prepareEnd = Date()
                try Task.checkCancellation()
                guard let modelURL = self.modelURL else { throw RetouchFailure.modelMissing }
                let directory = try Self.makeJobDirectory(jobID)
                jobDirectory = directory
                try Self.writePrepared(prepared, to: directory)
                self.retouchPhase = "processing"
                let request = WorkerRequest(
                    jobID: jobID.uuidString,
                    modelPath: modelURL.path,
                    imagePath: directory.appendingPathComponent("image.f32").path,
                    maskPath: directory.appendingPathComponent("mask.f32").path,
                    outputPath: directory.appendingPathComponent("output.f32").path
                )
                workerStart = Date()
                let response = try await Task.detached(priority: .userInitiated) { [worker] in
                    try worker.run(request: request, jobDirectory: directory, cancellation: cancellation)
                }.value
                workerEnd = Date()
                try Task.checkCancellation()
                guard let outputPath = response.outputPath else { throw RetouchFailure.invalidOutputShape }
                let predicted = try Self.readFloats(URL(fileURLWithPath: outputPath), count: 3 * 512 * 512)
                guard predicted.allSatisfy({ $0.isFinite }) else { throw RetouchFailure.nonFiniteOutput }
                let result = try await Task.detached(priority: .userInitiated) {
                    let currentIdentity = try SourceIdentity.capture(url)
                    guard currentIdentity == identity else { throw RetouchFailure.sourceChanged }
                    return try RetouchPreprocessor.composite(
                        source: source,
                        coverage: mask,
                        predicted: predicted,
                        rect: prepared.rect,
                        isCancelled: { cancellation.isCancelled }
                    )
                }.value
                compositeEnd = Date()
                #if DEBUG
                let timing: [String: Double] = [
                    "decode": decodeEnd.timeIntervalSince(timingsStart),
                    "prepare": prepareEnd.timeIntervalSince(decodeEnd),
                    "worker": workerEnd.timeIntervalSince(workerStart),
                    "composite": compositeEnd.timeIntervalSince(workerEnd),
                    "total": Date().timeIntervalSince(timingsStart),
                ]
                NSLog("E1.2 timing decode=%.2f prepare=%.2f worker=%.2f composite=%.2f total=%.2f",
                      timing["decode"]!, timing["prepare"]!, timing["worker"]!, timing["composite"]!, timing["total"]!)
                self.writeDebugJSON(timing, name: "e1.2-last-retouch")
                #endif
                guard self.retouchActiveID == jobID else { return }
                self.retouchActiveID = nil
                self.retouchCancellation = nil
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
                guard self.retouchGeneration == jobID,
                      self.maskRevision == maskRevisionAtStart,
                      self.editRevision == editRevisionAtStart,
                      self.selected == url,
                      !cancellation.isCancelled else { return }
                var state = self.editStates[url] ?? PhotoEditState()
                guard state.passes.count == priorPasses.count,
                      state.sourceIdentity == identity else {
                    self.retouchError = "source_changed"
                    return
                }
                let pass = RetouchPass(id: UUID(), strokes: snapshot, createdAt: Date(), modelID: "lama")
                state.passes.append(pass)
                state.mask = []
                self.editStates[url] = state
                self.pixelCache.put(result, source: identity, passes: state.passes, pass: state.passes.count - 1)
                self.cacheBytes = self.pixelCache.bytes
                self.syncCurrentResultWithCache()
                self.passCount = state.passes.count
                self.isDirty = true
                self.strokes = []
                self.maskRevision += 1
                self.editRevision += 1
                self.resultImage = result
                self.showingAfter = true
            } catch is CancellationError {
                guard self.retouchActiveID == jobID else { return }
                self.retouchActiveID = nil
                self.retouchCancellation = nil
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
            } catch RetouchFailure.cancelled {
                guard self.retouchActiveID == jobID else { return }
                self.retouchActiveID = nil
                self.retouchCancellation = nil
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
            } catch let error as WorkerClientFailure {
                guard self.retouchActiveID == jobID else { return }
                self.retouchActiveID = nil
                self.retouchCancellation = nil
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
                switch error {
                case .cancelled:
                    break
                case .timedOut:
                    self.retouchError = "timeout"
                case .launchFailed:
                    self.retouchError = "worker_launch_failed"
                case .processExited:
                    self.retouchError = "worker_crashed"
                case .badResponse(let code), .workerError(let code):
                    self.retouchError = code
                }
            } catch {
                guard self.retouchActiveID == jobID else { return }
                self.retouchActiveID = nil
                self.retouchCancellation = nil
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
                self.retouchError = Self.code(for: error)
            }
        }
    }

    var outputAspect: Double { Double(sessionOutputWidth) / Double(sessionOutputHeight) }

    private func sourceAspect(_ url: URL?) -> Double? {
        guard let url, let header = photos.first(where: { $0.url == url }) else { return nil }
        return Double(header.width) / Double(header.height)
    }

    func fittedCrop(sourceAspect: Double) -> SessionCrop {
        let output = outputAspect
        let w: Double, h: Double
        if sourceAspect > output { w = output / sourceAspect; h = 1 } else { w = 1; h = sourceAspect / output }
        return SessionCrop(x: (1 - w) / 2, y: (1 - h) / 2, width: w, height: h)
    }

    private func normalizedCrop(_ value: SessionCrop, sourceAspect: Double) -> SessionCrop {
        let output = outputAspect
        var w = min(1, max(0.02, value.width))
        var h = w * sourceAspect / output
        if h > 1 { h = 1; w = output / sourceAspect }
        let x = min(max(0, value.x), 1 - w)
        let y = min(max(0, value.y), 1 - h)
        return SessionCrop(x: x, y: y, width: w, height: h)
    }

    func setCanvasView(_ value: SessionView) {
        canvasView = value
        guard let selected else { return }
        var state = editStates[selected] ?? PhotoEditState()
        state.view = value
        editStates[selected] = state
    }

    func effectiveCrop(for url: URL) -> SessionCrop {
        guard let header = photos.first(where: { $0.url == url }) else {
            return SessionCrop(x: 0, y: 0, width: 1, height: 1)
        }
        return editStates[url]?.crop ?? fittedCrop(sourceAspect: Double(header.width) / Double(header.height))
    }

    func beginCrop() {
        guard let selected, let state = editStates[selected], !cropMode else { return }
        let aspect = sourceAspect(selected) ?? (4.0 / 3.0)
        cropSessionOriginal = state.crop
        cropSessionDirty = isDirty
        if state.crop == nil {
            let fit = fittedCrop(sourceAspect: aspect)
            editStates[selected, default: PhotoEditState()].crop = fit
            crop = fit
        } else { crop = state.crop }
        cropMode = true
    }

    func setCrop(_ value: SessionCrop) {
        guard let selected, let aspect = sourceAspect(selected) else { return }
        var state = editStates[selected] ?? PhotoEditState()
        let normalized = normalizedCrop(value, sourceAspect: aspect)
        state.crop = normalized
        editStates[selected] = state
        crop = normalized
    }

    func commitCrop() {
        defer { cropSessionOriginal = nil; cropMode = false }
        guard let selected, var state = editStates[selected] else { return }
        if state.crop != cropSessionOriginal {
            state.cropUndo.append(cropSessionOriginal)
            if state.cropUndo.count > 20 { state.cropUndo.removeFirst(state.cropUndo.count - 20) }
            editStates[selected] = state
            isDirty = true
        } else { isDirty = cropSessionDirty }
    }

    func cancelCrop() {
        defer { cropSessionOriginal = nil; cropMode = false }
        guard let selected, var state = editStates[selected] else { return }
        state.crop = cropSessionOriginal
        editStates[selected] = state
        crop = cropSessionOriginal
        isDirty = cropSessionDirty
    }

    func undoCrop() {
        guard let selected, var state = editStates[selected], let previous = state.cropUndo.popLast() else { return }
        state.crop = previous
        editStates[selected] = state
        crop = previous
        isDirty = true
    }

    func resetCrop() {
        guard let selected, var state = editStates[selected] else { return }
        state.cropUndo.append(state.crop)
        if state.cropUndo.count > 20 { state.cropUndo.removeFirst(state.cropUndo.count - 20) }
        state.crop = nil
        editStates[selected] = state
        crop = nil
        isDirty = true
    }

    func chooseLogo() {
        guard let selected else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor [weak self] in
                guard let self else { return }
                do {
                    let asset = try OutputEditing.loadLogo(url.path, mode: "logo")
                    var state = self.editStates[selected] ?? PhotoEditState()
                    state.logo = SessionLogo(path: url.path,
                                             width: Double(asset.width) / Double(max(1, self.sessionOutputWidth)),
                                             opacity: 1, x: 0, y: 0, enabled: true, mode: "logo")
                    self.editStates[selected] = state
                    self.logo = state.logo
                    self.logoAsset = asset
                    self.exportError = nil
                    self.isDirty = true
                    self.persistedLogo = state.logo
                    self.persistedLogoBookmark = try? url.bookmarkData(options: [.withSecurityScope], includingResourceValuesForKeys: nil, relativeTo: nil)
                    if self.logoAccessURL != url { self.logoAccessURL?.stopAccessingSecurityScopedResource() }
                    self.logoAccessURL = url
                    _ = url.startAccessingSecurityScopedResource()
                    if let value = state.logo { self.schedulePersistLogo(value) }
                } catch { self.exportError = "Не удалось прочитать PNG-логотип" }
            }
        }
    }

    func updateLogo(width: Double? = nil, opacity: Double? = nil, x: Double? = nil,
                    y: Double? = nil, enabled: Bool? = nil, mode: String? = nil) {
        guard let selected, var value = logo else { return }
        if let width { value.width = min(100, max(0.0001, width)) }
        if let opacity { value.opacity = min(1, max(0, opacity)) }
        if let x { value.x = x }
        if let y { value.y = y }
        if let enabled { value.enabled = enabled }
        if mode != nil { value.mode = "logo" }
        var state = editStates[selected] ?? PhotoEditState()
        state.logo = value
        editStates[selected] = state
        logo = value
        persistedLogo = value
        schedulePersistLogo(value)
        isDirty = true
    }

    func applyLogoToAll() {
        guard let value = logo else { return }
        for key in editStates.keys {
            var state = editStates[key] ?? PhotoEditState()
            state.logo = value
            editStates[key] = state
        }
        persistedLogo = value
        schedulePersistLogo(value)
        isDirty = true
    }

    func removeLogo() {
        guard let selected, var state = editStates[selected] else { return }
        state.logo = nil
        editStates[selected] = state
        logo = nil
        logoAsset = nil
        persistedLogo = nil
        persistedLogoBookmark = nil
        UserDefaults.standard.removeObject(forKey: Self.logoDefaultsKey)
        isDirty = true
    }

    var hasPersistedLogo: Bool { persistedLogo != nil }
    var persistedLogoName: String? { persistedLogo.map { URL(fileURLWithPath: $0.path).lastPathComponent } }

    func applyPersistedLogo() {
        guard let selected, let persistedLogo else { return }
        var value = persistedLogo
        value.enabled = true
        value.mode = "logo"
        value.opacity = 1
        var state = editStates[selected] ?? PhotoEditState()
        state.logo = value
        editStates[selected] = state
        logo = value
        loadLogoAsset(value)
        isDirty = true
    }

    func ensureLogoForCurrentPhoto() {
        guard let selected, editStates[selected]?.logo == nil, var value = persistedLogo else { return }
        value.enabled = true
        value.mode = "logo"
        value.opacity = 1
        var state = editStates[selected] ?? PhotoEditState()
        state.logo = value
        editStates[selected] = state
        logo = value
        loadLogoAsset(value)
    }

    private func schedulePersistLogo(_ value: SessionLogo) {
        persistLogoTask?.cancel()
        persistLogoTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(450))
            guard !Task.isCancelled, let self else { return }
            self.storePersistedLogo(value)
        }
    }

    private func storePersistedLogo(_ value: SessionLogo) {
        guard let bookmark = persistedLogoBookmark else { return }
        let item = PersistedLogo(path: value.path, bookmark: bookmark, mode: value.mode,
                                 width: value.width, opacity: value.opacity,
                                 x: value.x, y: value.y, enabled: value.enabled)
        if let data = try? JSONEncoder().encode(item) {
            UserDefaults.standard.set(data, forKey: Self.logoDefaultsKey)
        }
        persistedLogo = value
    }

    private func loadPersistedLogo() {
        guard let data = UserDefaults.standard.data(forKey: Self.logoDefaultsKey),
              let item = try? JSONDecoder().decode(PersistedLogo.self, from: data) else { return }
        var stale = false
        guard let url = try? URL(resolvingBookmarkData: item.bookmark, options: [.withSecurityScope],
                                 relativeTo: nil, bookmarkDataIsStale: &stale), !stale else { return }
        _ = url.startAccessingSecurityScopedResource()
        logoAccessURL = url
        persistedLogoBookmark = item.bookmark
        persistedLogo = SessionLogo(path: url.path, width: item.width, opacity: item.opacity,
                                    x: item.x, y: item.y, enabled: item.enabled, mode: item.mode)
        if let logo = persistedLogo { loadLogoAsset(logo) }
    }

    private func loadLogoAsset(_ value: SessionLogo?) {
        guard let value else { logoAsset = nil; return }
        Task { @MainActor [weak self] in
            do {
                let asset = try OutputEditing.loadLogo(value.path, mode: value.mode)
                guard self?.logo?.path == value.path, self?.logo?.mode == value.mode else { return }
                self?.logoAsset = asset
                self?.exportError = nil
            } catch { self?.logoAsset = nil; self?.exportError = "Не удалось прочитать PNG-логотип" }
        }
    }

    var canUndoPass: Bool {
        guard let selected else { return false }
        return !retouchBusy && (editStates[selected]?.passes.isEmpty == false)
    }

    /// Undo the last completed removal, restore its mask for refinement, and
    /// leave earlier passes intact.
    func undoLastPass() {
        guard sessionReadOnly == nil, !retouchBusy, let url = selected, var state = editStates[url],
              let removed = state.passes.popLast() else { return }
        // The undone pass's strokes come before the current refinement strokes.
        state.mask = removed.strokes + strokes
        editStates[url] = state
        strokes = state.mask
        maskRevision += 1
        editRevision += 1
        passCount = state.passes.count
        if let identity = state.sourceIdentity, !state.passes.isEmpty {
            resultImage = pixelCache.get(source: identity, passes: state.passes, pass: state.passes.count - 1)
        } else {
            resultImage = nil
        }
        showingAfter = false
        retouchError = nil
        isDirty = true
        cacheBytes = pixelCache.bytes
        if resultImage == nil && !state.passes.isEmpty { startRestoreIfNeeded() }
    }

    func restoreCurrentResult() {
        startRestoreIfNeeded()
    }

    private func syncCurrentResultWithCache() {
        guard let url = selected, let state = editStates[url],
              let identity = state.sourceIdentity, !state.passes.isEmpty else { return }
        if !pixelCache.contains(source: identity, passes: state.passes, pass: state.passes.count - 1) {
            resultImage = nil
            showingAfter = false
        }
    }

    func rebaseSource() {
        guard let url = selected, var state = editStates[url], !retouchBusy else { return }
        Task { @MainActor [weak self] in
            guard let self, let current = try? await Task.detached { try SourceIdentity.capture(url) }.value else { return }
            state.sourceIdentity = current
            state.sourceChanged = false
            self.editStates[url] = state
            self.sourceNeedsDecision = false
            self.isDirty = true
            self.pixelCache.clear()
            self.cacheBytes = 0
            self.resultImage = nil
            self.retouchError = nil
            self.startRestoreIfNeeded()
        }
    }

    func resetEdits() {
        guard let url = selected, var state = editStates[url], !retouchBusy else { return }
        state.mask = []
        state.passes = []
        state.crop = nil
        state.logo = nil
        state.sourceChanged = false
        editStates[url] = state
        sourceNeedsDecision = false
        isDirty = true
        strokes = []
        passCount = 0
        resultImage = nil
        showingAfter = false
        pixelCache.clear()
        cacheBytes = 0
        retouchError = nil
    }

    private func startRestoreIfNeeded() {
        guard sessionReadOnly == nil, !retouchBusy, retouchActiveID == nil, let url = selected,
              let state = editStates[url], !state.passes.isEmpty, !state.sourceChanged,
              let identity = state.sourceIdentity, resultImage == nil else { return }
        let jobID = UUID()
        let cancellation = CancellationFlag()
        retouchActiveID = jobID
        retouchCancellation = cancellation
        retouchGeneration = jobID
        retouchBusy = true
        retouchPhase = "restoring"
        retouchError = nil
        retouchTask = Task { [weak self] in
            guard let self else { return }
            do {
                guard let currentIdentity = try? await Task.detached { try SourceIdentity.capture(url) }.value,
                      currentIdentity == identity else { throw RetouchFailure.sourceChanged }
                guard self.retouchActiveID == jobID else { return }
                let result = try await self.replayPasses(url: url, passes: state.passes,
                                                         identity: identity, cancellation: cancellation,
                                                         maskRevision: 0, editRevision: 0)
                guard self.retouchActiveID == jobID else { return }
                self.retouchActiveID = nil
                self.retouchCancellation = nil
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
                guard self.selected == url, !cancellation.isCancelled,
                      self.editStates[url]?.sourceIdentity == identity else { return }
                self.pixelCache.put(result, source: identity, passes: state.passes, pass: state.passes.count - 1)
                self.resultImage = result
                self.cacheBytes = self.pixelCache.bytes
                self.syncCurrentResultWithCache()
                self.showingAfter = true
            } catch {
                guard self.retouchActiveID == jobID else { return }
                self.retouchActiveID = nil
                self.retouchCancellation = nil
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
                if !(error is CancellationError) { self.retouchError = Self.code(for: error) }
            }
        }
    }

    private func replayPasses(url: URL, passes: [RetouchPass], identity: SourceIdentity,
                              cancellation: CancellationFlag, maskRevision: Int, editRevision: Int) async throws -> StraightImage {
        if let header = photos.first(where: { $0.url == url }) {
            do {
                try policy.admitRetouch(pixels: UInt64(header.width) * UInt64(header.height),
                                        residentBytes: SystemMemory.physicalFootprintBytes() ?? 0,
                                        availableBytes: SystemMemory.availableBytes(),
                                        pressure: pressure)
            } catch { throw RetouchFailure.insufficientMemory }
        }
        var current: StraightImage?
        for (index, pass) in passes.enumerated() {
            try Task.checkCancellation()
            if let cached = pixelCache.get(source: identity, passes: passes, pass: index) {
                current = cached
                continue
            }
            if current == nil {
                current = try await imageDecoder.decode(url: url)
            }
            guard var source = current else { throw RetouchFailure.invalidImage }
            retouchPhase = "restoring \(index + 1)/\(passes.count)"
            source = try await runPass(source: source, url: url, strokes: pass.strokes,
                                       modelID: pass.modelID, identity: identity, cancellation: cancellation)
            current = source
            pixelCache.put(source, source: identity, passes: passes, pass: index)
            cacheBytes = pixelCache.bytes
        }
        guard let result = current else { throw RetouchFailure.invalidImage }
        return result
    }

    private func runPass(source: StraightImage, url: URL, strokes: [MaskStroke], modelID: String,
                         identity: SourceIdentity, cancellation: CancellationFlag) async throws -> StraightImage {
        let jobID = UUID()
        var jobDirectory: URL?
        defer { if let jobDirectory { try? FileManager.default.removeItem(at: jobDirectory) } }
        let mask = MaskRenderer.render(width: source.width, height: source.height,
                                       strokes: strokes, isCancelled: { cancellation.isCancelled })
        guard !cancellation.isCancelled else { throw RetouchFailure.cancelled }
        guard !MaskRenderer.isEmpty(mask) else { throw RetouchFailure.emptyMask }
        let prepared = try await Task.detached(priority: .userInitiated) {
            try RetouchPreprocessor.prepare(source: source, mask: mask, isCancelled: { cancellation.isCancelled })
        }.value
        try Task.checkCancellation()
        guard let modelURL = modelURL(for: modelID) else { throw RetouchFailure.modelMissing }
        let directory = try Self.makeJobDirectory(jobID)
        jobDirectory = directory
        try Self.writePrepared(prepared, to: directory)
        let request = WorkerRequest(
            jobID: jobID.uuidString,
            modelPath: modelURL.path,
            imagePath: directory.appendingPathComponent("image.f32").path,
            maskPath: directory.appendingPathComponent("mask.f32").path,
            outputPath: directory.appendingPathComponent("output.f32").path
        )
        let response = try await Task.detached(priority: .userInitiated) { [worker] in
            try worker.run(request: request, jobDirectory: directory, cancellation: cancellation)
        }.value
        guard let outputPath = response.outputPath else { throw RetouchFailure.invalidOutputShape }
        let predicted = try Self.readFloats(URL(fileURLWithPath: outputPath), count: 3 * 512 * 512)
        guard predicted.allSatisfy({ $0.isFinite }) else { throw RetouchFailure.nonFiniteOutput }
        let currentIdentity = try SourceIdentity.capture(url)
        guard currentIdentity == identity else { throw RetouchFailure.sourceChanged }
        return try RetouchPreprocessor.composite(source: source, coverage: mask, predicted: predicted,
                                                 rect: prepared.rect, isCancelled: { cancellation.isCancelled })
    }

    var selectedHasVisibleBranding: Bool {
        guard let selected, let logo = editStates[selected]?.logo, logo.enabled,
              logo.opacity > 0, let asset = logoAsset, asset.width > 0 else { return false }
        let w = Double(sessionOutputWidth) * logo.width
        let h = w * Double(asset.height) / Double(max(1, asset.width))
        let lx = Double(sessionOutputWidth) / 2 + logo.x - w / 2
        let ly = Double(sessionOutputHeight) / 2 + logo.y - h / 2
        return lx < Double(sessionOutputWidth) && lx + w > 0 &&
               ly < Double(sessionOutputHeight) && ly + h > 0
    }

    var selectedCropHasEmptyArea: Bool {
        guard let selected, let crop = editStates[selected]?.crop else { return false }
        return crop.x < 0 || crop.y < 0 || crop.x + crop.width > 1.000001 || crop.y + crop.height > 1.000001
    }

    func exportPanel(format: ExportFormat, quality: Double) {
        guard !exportBusy, !photos.isEmpty else { return }
        if selectedCropHasEmptyArea {
            let alert = NSAlert()
            alert.messageText = "Кадр выходит за фотографию"
            alert.informativeText = "Часть выходного кадра не содержит изображения. Вернитесь к кадрированию и уменьшите кадр."
            alert.addButton(withTitle: "Вернуться")
            NSApp.activate(ignoringOtherApps: true)
            alert.runModal()
            return
        }
        if !selectedHasVisibleBranding {
            let alert = NSAlert()
            alert.messageText = "Нет брендирования"
            alert.informativeText = "На фотографию не добавлен логотип. Экспортировать без брендирования?"
            alert.addButton(withTitle: "Нет")
            alert.addButton(withTitle: "Да")
            NSApp.activate(ignoringOtherApps: true)
            guard alert.runModal() == .alertSecondButtonReturn else { return }
        }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Экспортировать"
        panel.begin { [weak self] response in
            guard response == .OK, let folder = panel.url else { return }
            Task { @MainActor [weak self] in
                await self?.exportCollection(to: folder, format: format, quality: quality)
            }
        }
    }

    func cancelExport() {
        exportCancellation?.cancel()
    }

    func exportCollection(to folder: URL, format: ExportFormat, quality: Double) async {
        guard !exportBusy, sessionReadOnly == nil, !sourceNeedsDecision else { return }
        let cancellation = CancellationFlag()
        exportCancellation = cancellation
        exportBusy = true
        exportDone = 0
        exportTotal = photos.count
        exportError = nil
        defer {
            exportBusy = false
            exportCancellation = nil
        }
        for (index, photo) in photos.enumerated() {
            if cancellation.isCancelled { break }
            do {
                var state = editStates[photo.url] ?? PhotoEditState()
                let identity: SourceIdentity
                if let known = state.sourceIdentity { identity = known }
                else { identity = try SourceIdentity.capture(photo.url); state.sourceIdentity = identity; editStates[photo.url] = state }
                guard try SourceIdentity.capture(photo.url) == identity else {
                    throw RetouchFailure.sourceChanged
                }
                let base: StraightImage
                if state.passes.isEmpty {
                    base = try await imageDecoder.decode(url: photo.url)
                } else if let cached = pixelCache.get(source: identity, passes: state.passes, pass: state.passes.count - 1) {
                    base = cached
                } else {
                    base = try await replayPasses(url: photo.url, passes: state.passes, identity: identity,
                                                  cancellation: cancellation, maskRevision: 0, editRevision: 0)
                }
                if cancellation.isCancelled { break }
                let aspect = Double(photo.width) / Double(photo.height)
                let crop = state.crop ?? fittedCrop(sourceAspect: aspect)
                let width = sessionOutputWidth, height = sessionOutputHeight
                let pixels = UInt64(width) * UInt64(height)
                guard width > 0, height > 0, width <= 16000, height <= 16000, pixels <= 40_000_000 else {
                    throw RetouchFailure.imageTooLarge
                }
                do {
                    try policy.admitRetouch(pixels: pixels,
                                            residentBytes: SystemMemory.physicalFootprintBytes() ?? 0,
                                            availableBytes: SystemMemory.availableBytes(),
                                            pressure: pressure)
                } catch { throw RetouchFailure.insufficientMemory }
                let logo = state.logo
                let logoIdentity = try logo.map { try SourceIdentity.capture(URL(fileURLWithPath: $0.path)) }
                let encoded = try await Task.detached(priority: .userInitiated) { () -> Data in
                    if cancellation.isCancelled { throw OutputEditingError.cancelled }
                    var output = try OutputEditing.crop(base, to: crop, width: width, height: height,
                                                        isCancelled: { cancellation.isCancelled })
                    if let logo, logo.enabled, logo.opacity > 0 {
                        let asset = try OutputEditing.loadLogo(logo.path, mode: logo.mode)
                        output = try OutputEditing.applyLogo(output, logo: logo, asset: asset,
                                                             width: width, height: height,
                                                             isCancelled: { cancellation.isCancelled })
                    }
                    return try ExportWriter.encode(output, format: format, quality: quality)
                }.value
                if cancellation.isCancelled { break }
                guard try SourceIdentity.capture(photo.url) == identity else {
                    throw RetouchFailure.sourceChanged
                }
                if let logo, let logoIdentity {
                    guard try SourceIdentity.capture(URL(fileURLWithPath: logo.path)) == logoIdentity else {
                        throw OutputEditingError.invalidLogo
                    }
                }
                let originals = Set(photos.map { $0.url.standardizedFileURL })
                try await Task.detached(priority: .userInitiated) {
                    try Self.writeExport(encoded, folder: folder,
                                         stem: photo.url.deletingPathExtension().lastPathComponent,
                                         format: format, originals: originals)
                }.value
                exportDone = index + 1
            } catch {
                exportError = (error as? OutputEditingError).map { "export_\($0)" } ?? Self.code(for: error)
                break
            }
        }
    }

    nonisolated private static func writeExport(_ data: Data, folder: URL, stem: String, format: ExportFormat,
                                    originals: Set<URL>) throws {
        let suffix = format == .png ? ".png" : ".jpg"
        for index in 0..<1000 {
            let name = "\(stem)-logo" + (index == 0 ? "" : String(format: "%02d", index)) + suffix
            let target = folder.appendingPathComponent(name).standardizedFileURL
            if originals.contains(target) { continue }
            do {
                if try ExportWriter.publish(data, to: target) { return }
            } catch { throw error }
        }
        throw OutputEditingError.encode
    }

    func cancelRetouch(wait: Bool = false) {
        guard let active = retouchActiveID else { return }
        retouchGeneration = UUID()
        retouchCancellation?.cancel()
        worker.cancel()
        if wait {
            // Do not block MainActor. The slot stays busy until the worker
            // task observes termination and releases activeID.
            let worker = self.worker
            Task.detached(priority: .userInitiated) { worker.cancelAndWait() }
        }
        retouchTask?.cancel()
        // Keep busy=true until the task/worker confirms termination. A new
        // heavy job must not start while the old process is still alive.
        retouchPhase = "cancelling"
        _ = active
    }

    private func modelURL(for modelID: String) -> URL? {
        guard modelID == "lama" else { return nil }
        return modelURL
    }

    private var modelURL: URL? {
        if let bundled = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") {
            return bundled
        }
        if let override = ProcessInfo.processInfo.environment["PHOTOPREP_LAMA_MODEL"], !override.isEmpty {
            let url = URL(fileURLWithPath: override, isDirectory: true)
            if FileManager.default.fileExists(atPath: url.path) { return url }
        }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?
            .appendingPathComponent("PhotoPrep Native/Models/LaMa-fp32.mlmodelc", isDirectory: true)
        if let support, FileManager.default.fileExists(atPath: support.path) { return support }
        return nil
    }

    private static func makeJobDirectory(_ jobID: UUID) throws -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("PhotoPrep Native/Jobs", isDirectory: true)
        let directory = base.appendingPathComponent(jobID.uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        return directory
    }

    private static func writePrepared(_ prepared: PreparedInput, to directory: URL) throws {
        let imageData = prepared.image.withUnsafeBufferPointer { Data(buffer: $0) }
        let maskData = prepared.mask.withUnsafeBufferPointer { Data(buffer: $0) }
        try imageData.write(to: directory.appendingPathComponent("image.f32"), options: .atomic)
        try maskData.write(to: directory.appendingPathComponent("mask.f32"), options: .atomic)
    }

    private static func readFloats(_ url: URL, count: Int) throws -> [Float] {
        let data = try Data(contentsOf: url)
        guard data.count == count * MemoryLayout<Float>.size else { throw RetouchFailure.invalidOutputShape }
        var values = [Float](repeating: 0, count: count)
        _ = values.withUnsafeMutableBytes { data.copyBytes(to: $0) }
        return values
    }

    private static func code(for error: Error) -> String {
        if let failure = error as? RetouchFailure {
            switch failure {
            case .emptyMask: return "empty_mask"
            case .sourceChanged: return "source_changed"
            case .modelMissing: return "model_missing"
            case .premultipliedAlpha, .unsupportedAlphaLayout: return "unsupported_alpha"
            case .insufficientMemory: return "memory"
            case .unsupportedColorSpace: return "unsupported_color"
            case .bufferTooSmall: return "invalid_image"
            case .invalidImage, .unsupportedPixelLayout, .invalidMask: return "invalid_image"
            case .nonFiniteOutput, .invalidOutputShape: return "invalid_output"
            case .imageTooLarge: return "image_too_large"
            case .workerFailed(let code): return code
            case .timeout: return "timeout"
            case .cancelled: return "cancelled"
            }
        }
        if error is WorkerClientFailure { return "worker_crashed" }
        return "worker_failed"
    }
    #if DEBUG
    private func waitWhileBusy(_ description: String) async {
        var waited = 0.0
        while (retouchBusy || importBusy) && waited < 180 {
            try? await Task.sleep(for: .milliseconds(50))
            waited += 0.05
        }
        if retouchBusy || importBusy {
            NSLog("PhotoPrep full stress: timeout waiting for %@", description)
        }
    }

    private func debugSetMask() {
        strokes = [
            MaskStroke(points: [MaskPoint(x: 0.02, y: 0.03), MaskPoint(x: 0.38, y: 0.03)], width: 0.16),
            MaskStroke(points: [MaskPoint(x: 0.02, y: 0.12), MaskPoint(x: 0.38, y: 0.12)], width: 0.16),
            MaskStroke(points: [MaskPoint(x: 0.02, y: 0.21), MaskPoint(x: 0.38, y: 0.21)], width: 0.16),
        ]
        maskRevision += 1
        editRevision += 1
        resultImage = nil
        showingAfter = false
    }

    private func writeDebugJSON(_ value: Any, name: String) {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted]) else { return }
        let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("PhotoPrep Native/\(name).json")
        try? data.write(to: url)
        NSLog("PhotoPrep full stress: wrote %@", url.path)
    }

    private func setHistoryMask(_ strokes: [MaskStroke]) {
        self.strokes = strokes
        if let selected { editStates[selected, default: PhotoEditState()].mask = strokes }
        maskRevision += 1
        editRevision += 1
        showingAfter = false
        retouchError = nil
    }

    func runCumulativeHistorySelfTest() async {
        guard let coffee = DebugLaunchOptions.openPhoto else {
            NSLog("E1.3 history: missing --photoprep-open")
            NSApplication.shared.terminate(nil); return
        }
        let astronaut = coffee.deletingLastPathComponent().appendingPathComponent("real-astronaut.png")
        importURLs([coffee, astronaut])
        var waited = 0.0
        while (photos.count < 1 || selected == nil || importBusy) && waited < 60 {
            try? await Task.sleep(for: .milliseconds(100)); waited += 0.1
        }
        guard selected == coffee else {
            NSLog("E1.3 history: coffee was not selected")
            NSApplication.shared.terminate(nil); return
        }
        let mask1 = [MaskStroke(points: [MaskPoint(x: 0.05, y: 0.1), MaskPoint(x: 0.35, y: 0.1)], width: 0.12)]
        let mask2 = [MaskStroke(points: [MaskPoint(x: 0.05, y: 0.3), MaskPoint(x: 0.35, y: 0.3)], width: 0.12)]
        setHistoryMask(mask1)
        processMask()
        await waitWhileBusy("history pass 1")
        guard let firstResult = resultImage, passCount == 1, retouchError == nil else {
            NSLog("E1.3 history: pass1 failed")
            NSApplication.shared.terminate(nil); return
        }
        // Clearing the next mask must not delete the completed pass.
        setHistoryMask(mask2)
        clearMask()
        let clearKeptResult = resultImage != nil && passCount == 1
        setHistoryMask(mask2)
        processMask()
        await waitWhileBusy("history pass 2")
        guard let secondResult = resultImage, passCount == 2, retouchError == nil else {
            NSLog("E1.3 history: pass2 failed")
            NSApplication.shared.terminate(nil); return
        }
        // Outside mask2 the second pass must be identical to the first result.
        let coverage2 = MaskRenderer.render(width: secondResult.width, height: secondResult.height, strokes: mask2)
        var outsideSame = true
        for index in 0..<(secondResult.width * secondResult.height) where coverage2[index] == 0 {
            let offset = index * 4
            if Array(secondResult.pixels[offset..<(offset + 4)]) != Array(firstResult.pixels[offset..<(offset + 4)]) {
                outsideSame = false; break
            }
        }
        let beforeTogglePasses = passCount
        showingAfter = false; showingAfter = true
        let toggleKeptRecipe = passCount == beforeTogglePasses
        // Simulate pixel-cache eviction, then replay from the recipes.
        pixelCache.clear(); cacheBytes = 0; resultImage = nil
        restoreCurrentResult()
        await waitWhileBusy("history replay")
        let replayRestored = resultImage != nil && passCount == 2
        // Photo switch must keep masks/passes.
        selected = astronaut
        try? await Task.sleep(for: .milliseconds(500))
        let astronautPasses = passCount
        selected = coffee
        try? await Task.sleep(for: .milliseconds(700))
        let switchKept = passCount == 2 && astronautPasses == 0
        // Undo last pass must return its mask BEFORE the current refinement.
        let removedMask = editStates[coffee]?.passes.last?.strokes ?? []
        let refinement = [MaskStroke(points: [MaskPoint(x: 0.2, y: 0.7), MaskPoint(x: 0.4, y: 0.7)], width: 0.08)]
        setHistoryMask(refinement)
        undoLastPass()
        let undoOrdered = strokes.count == removedMask.count + refinement.count
            && Array(strokes.prefix(removedMask.count)) == removedMask
            && strokes.last?.points == refinement.last?.points
        let undoKeptOne = passCount == 1 && !strokes.isEmpty && undoOrdered
        let mask3 = [MaskStroke(points: [MaskPoint(x: 0.1, y: 0.5), MaskPoint(x: 0.3, y: 0.5)], width: 0.1)]
        setHistoryMask(mask3)
        let passesBeforeCancel = passCount
        processMask()
        try? await Task.sleep(for: .milliseconds(100))
        cancelRetouch()
        await waitWhileBusy("history cancel")
        let cancelKeptMask = !strokes.isEmpty && passCount == passesBeforeCancel
        let report: [String: Any] = [
            "pass1": true, "pass2": true, "outsideSame": outsideSame,
            "clearKeptResult": clearKeptResult, "toggleKeptRecipe": toggleKeptRecipe,
            "replayRestored": replayRestored, "switchKept": switchKept,
            "undoKeptOne": undoKeptOne, "passCountAfterUndo": passCount,
            "cacheBytes": cacheBytes, "astronautPasses": astronautPasses
        ]
        writeDebugJSON(report, name: "e1.3-history")
        NSLog("E1.3 history: outside=%@ clear=%@ toggle=%@ replay=%@ switch=%@ undo=%@",
              outsideSame ? "yes" : "no", clearKeptResult ? "yes" : "no",
              toggleKeptRecipe ? "yes" : "no", replayRestored ? "yes" : "no",
              switchKept ? "yes" : "no", undoKeptOne ? "yes" : "no")
        NSLog("E1.3 history cancel mask kept=\(cancelKeptMask ? "yes" : "no") undoOrdered=\(undoOrdered ? "yes" : "no")")
        NSApplication.shared.terminate(nil)
    }

    func runV1ExportSelfTest() async {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let coffee = base.appendingPathComponent("real-coffee.png")
        let astro = base.appendingPathComponent("real-astronaut.png")
        let logo = base.appendingPathComponent("v1-logo.png")
        if !FileManager.default.fileExists(atPath: logo.path) {
            let w = 32, h = 32
            var p = [UInt8](repeating: 0, count: w*h*4)
            for y in 8..<24 { for x in 8..<24 {
                let i=(y*w+x)*4; p[i]=220; p[i+1]=30; p[i+2]=30; p[i+3]=255
            }}
            let img = StraightImage(width:w,height:h,pixels:p)
            if let cg=img.cgImage(), let d=CGImageDestinationCreateWithURL(logo as CFURL, UTType.png.identifier as CFString,1,nil) {
                CGImageDestinationAddImage(d,cg,nil); _ = CGImageDestinationFinalize(d)
            }
        }
        let originals = [coffee, astro].compactMap { try? SourceIdentity.digest($0) }
        importURLs([coffee, astro])
        var waited = 0.0
        while (photos.count < 2 || importBusy) && waited < 30 { try? await Task.sleep(for: .milliseconds(100)); waited += 0.1 }
        for url in [coffee, astro] {
            selected = url
            try? await Task.sleep(for: .milliseconds(300))
            setHistoryMask([MaskStroke(points: [MaskPoint(x: 0.05,y: 0.1), MaskPoint(x: 0.3,y: 0.1)], width: 0.1)])
            processMask(); await waitWhileBusy("v1 export pass")
            if let selected, var state = editStates[selected] {
                state.crop = fittedCrop(sourceAspect: sourceAspect(selected) ?? 4.0/3.0)
                state.logo = SessionLogo(path: logo.path, width: 0.2, opacity: 0.9, x: 0, y: 0, enabled: true, mode: "logo")
                editStates[selected] = state
            }
        }
        let folder = base.appendingPathComponent("v1-export", isDirectory: true)
        try? FileManager.default.removeItem(at: folder)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        await exportCollection(to: folder, format: .png, quality: 0.92)
        let files = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        var dims: [[String:Any]] = []
        for f in files where f.pathExtension.lowercased()=="png" {
            if let src=CGImageSourceCreateWithURL(f as CFURL,nil), let image=CGImageSourceCreateImageAtIndex(src,0,nil) {
                dims.append(["name":f.lastPathComponent,"width":image.width,"height":image.height])
            }
        }
        let after = [coffee, astro].compactMap { try? SourceIdentity.digest($0) }
        let report: [String:Any] = ["exported": dims.count, "expected": 2,
                                    "dimensions": dims, "error": exportError ?? "",
                                    "originalsUnchanged": originals == after,
                                    "dirty": isDirty]
        writeDebugJSON(report, name: "v1-export")
        NSLog("V1 export: files=%d error=%@ originals=%@", dims.count, exportError ?? "", originals == after ? "yes" : "no")
        NSApplication.shared.terminate(nil)
    }

    func runSessionStateSelfTest() async {
        guard let path = ProcessInfo.processInfo.environment["PHOTOPREP_SESSION_FILE"] else {
            NSApplication.shared.terminate(nil); return
        }
        let url = URL(fileURLWithPath: path)
        openSession(url)
        var waited = 0.0
        while (photos.isEmpty || sessionTask != nil) && waited < 30 {
            try? await Task.sleep(for: .milliseconds(100)); waited += 0.1
        }
        let loadedWidth = sessionOutputWidth
        let loadedHeight = sessionOutputHeight
        let selectedURL = selected
        let loadedView = selectedURL.flatMap { editStates[$0]?.view } ?? SessionView()
        let out = url.deletingLastPathComponent().appendingPathComponent("native-state-out.photoprep.json")
        await saveSession(to: out)
        let saved = (try? SessionCodec.load(out))
        let report: [String: Any] = [
            "loadedWidth": loadedWidth, "loadedHeight": loadedHeight,
            "savedWidth": saved?.outputWidth ?? -1, "savedHeight": saved?.outputHeight ?? -1,
            "viewEqual": saved?.photos.first(where: { $0.url.standardizedFileURL == selectedURL?.standardizedFileURL })?.view == loadedView,
            "photos": photos.count, "error": retouchError ?? ""
        ]
        writeDebugJSON(report, name: "e1.5-session-state")
        NSLog("E1.5 session-state: loaded=%dx%d saved=%dx%d view=%@ photos=%d",
              loadedWidth, loadedHeight, saved?.outputWidth ?? -1, saved?.outputHeight ?? -1,
              (saved?.photos.first(where: { $0.url.standardizedFileURL == selectedURL?.standardizedFileURL })?.view == loadedView) ? "yes" : "no", photos.count)
        try? FileManager.default.removeItem(at: out)
        NSApplication.shared.terminate(nil)
    }

    func runSessionReplaySelfTest() async {
        guard let photo = DebugLaunchOptions.openPhoto else {
            NSApplication.shared.terminate(nil); return
        }
        importURLs([photo])
        var waited = 0.0
        while (selected == nil || importBusy) && waited < 30 {
            try? await Task.sleep(for: .milliseconds(100)); waited += 0.1
        }
        setHistoryMask([MaskStroke(points: [MaskPoint(x: 0.05, y: 0.1), MaskPoint(x: 0.3, y: 0.1)], width: 0.1)])
        processMask(); await waitWhileBusy("session pass1")
        setHistoryMask([MaskStroke(points: [MaskPoint(x: 0.05, y: 0.3), MaskPoint(x: 0.3, y: 0.3)], width: 0.1)])
        processMask(); await waitWhileBusy("session pass2")
        guard let before = resultImage else {
            NSLog("E1.4 session-replay: no result before save")
            NSApplication.shared.terminate(nil); return
        }
        let session = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("PhotoPrep Native/e1.4-reopen.photoprep.json")
        await saveSession(to: session)
        let saveError = retouchError
        clear()
        openSession(session)
        waited = 0
        while (selected == nil || importBusy || retouchBusy || resultImage == nil) && waited < 90 {
            try? await Task.sleep(for: .milliseconds(100)); waited += 0.1
        }
        let after = resultImage
        let equal = after != nil && before.width == after!.width && before.height == after!.height && before.pixels == after!.pixels
        let report: [String: Any] = ["saveError": saveError ?? "", "reopened": selected != nil,
                                     "restored": after != nil, "pixelsEqual": equal,
                                     "beforeBytes": before.pixels.count, "afterBytes": after?.pixels.count ?? 0,
                                     "passes": passCount, "sessionReadOnly": sessionReadOnly ?? ""]
        writeDebugJSON(report, name: "e1.4-session-replay")
        NSLog("E1.4 session-replay: reopened=\(selected != nil ? "yes" : "no") restored=\(after != nil ? "yes" : "no") equal=\(equal ? "yes" : "no")")
        try? FileManager.default.removeItem(at: session)
        NSApplication.shared.terminate(nil)
    }

    func runCacheSourceChangeSelfTest() async {
        guard let source = DebugLaunchOptions.openPhoto else {
            NSApplication.shared.terminate(nil); return
        }
        let copy = source.deletingLastPathComponent().appendingPathComponent("e1.4-cache-source.png")
        try? FileManager.default.removeItem(at: copy)
        do { try FileManager.default.copyItem(at: source, to: copy) } catch {
            NSLog("E1.4 cache-source: copy failed"); NSApplication.shared.terminate(nil); return
        }
        importURLs([source, copy])
        var waited = 0.0
        while (photos.count < 2 || importBusy) && waited < 60 {
            try? await Task.sleep(for: .milliseconds(100)); waited += 0.1
        }
        selected = copy
        try? await Task.sleep(for: .milliseconds(500))
        setHistoryMask([MaskStroke(points: [MaskPoint(x: 0.1, y: 0.1), MaskPoint(x: 0.3, y: 0.1)], width: 0.1)])
        processMask()
        await waitWhileBusy("cache-source pass")
        let had = resultImage != nil && passCount == 1
        if let handle = try? FileHandle(forWritingTo: copy) {
            try? handle.seekToEnd(); try? handle.write(contentsOf: Data([0])); try? handle.close()
        }
        selected = source
        try? await Task.sleep(for: .milliseconds(300))
        selected = copy
        try? await Task.sleep(for: .milliseconds(900))
        let cacheCleared = resultImage == nil && retouchError == "source_changed" && sourceNeedsDecision
        let recipesKept = passCount == 1 && (editStates[copy]?.passes.count == 1)
        let report: [String: Any] = ["cacheWasPresent": had, "cacheCleared": cacheCleared,
                                     "recipesKept": recipesKept,
                                     "error": retouchError ?? "", "passCount": passCount]
        writeDebugJSON(report, name: "e1.4-cache-source")
        NSLog("E1.4 cache-source: had=\(had ? "yes" : "no") cacheCleared=\(cacheCleared ? "yes" : "no") recipesKept=\(recipesKept ? "yes" : "no")")
        try? FileManager.default.removeItem(at: copy)
        NSApplication.shared.terminate(nil)
    }

    func runFullStress() async {
        guard let url = DebugLaunchOptions.openPhoto else {
            NSLog("PhotoPrep full stress: missing --photoprep-open")
            NSApplication.shared.terminate(nil)
            return
        }
        let requested = Int(ProcessInfo.processInfo.environment["PHOTOPREP_E1_FULL_STRESS"] ?? "20") ?? 20
        importURLs([url])
        var waited = 0.0
        while (photos.isEmpty || selected == nil || importBusy) && waited < 60 {
            try? await Task.sleep(for: .milliseconds(100))
            waited += 0.1
        }
        guard selected != nil else {
            NSLog("PhotoPrep full stress: import failed")
            NSApplication.shared.terminate(nil)
            return
        }
        while previewBusy && waited < 60 {
            try? await Task.sleep(for: .milliseconds(100))
            waited += 0.1
        }
        debugSetMask()
        var samples: [[String: Any]] = []
        var peak = SystemMemory.physicalFootprintBytes() ?? 0
        let overallStart = Date()
        for index in 1...max(1, requested) {
            debugSetMask()
            let start = Date()
            processMask()
            await waitWhileBusy("iteration \(index)")
            let elapsed = Date().timeIntervalSince(start)
            let phys = SystemMemory.physicalFootprintBytes() ?? 0
            peak = max(peak, phys)
            let ok = resultImage != nil && retouchError == nil
            if let image = resultImage?.cgImage() {
                _ = image.width
            }
            showingAfter = true
            // Force SwiftUI to render the result before the next iteration.
            await Task.yield()
            try? await Task.sleep(for: .milliseconds(80))
            let sample: [String: Any] = ["iteration": index, "ok": ok, "seconds": elapsed,
                                         "phys": phys, "width": resultImage?.width ?? 0,
                                         "height": resultImage?.height ?? 0]
            samples.append(sample)
            NSLog("PhotoPrep full stress: \(index)/\(requested) ok=\(ok ? "yes" : "no") seconds=\(String(format: "%.2f", elapsed)) phys=\(phys)")
        }
        let residual = SystemMemory.physicalFootprintBytes() ?? 0
        let report: [String: Any] = [
            "iterations": requested, "ok": samples.allSatisfy { ($0["ok"] as? Bool) == true },
            "peakPhys": peak, "residualPhys": residual,
            "totalSeconds": Date().timeIntervalSince(overallStart), "samples": samples,
            "source": url.path, "pressure": "\(pressure)"
        ]
        writeDebugJSON(report, name: "e1.2-full-stress")
        NSApplication.shared.terminate(nil)
    }

    func runActivePressureSelftest() async {
        guard let url = DebugLaunchOptions.openPhoto else {
            NSLog("PhotoPrep pressure active: missing --photoprep-open")
            NSApplication.shared.terminate(nil)
            return
        }
        importURLs([url])
        var waited = 0.0
        while (photos.isEmpty || selected == nil || importBusy) && waited < 60 {
            try? await Task.sleep(for: .milliseconds(100))
            waited += 0.1
        }
        guard selected != nil else { NSApplication.shared.terminate(nil); return }
        debugSetMask()
        processMask()
        waited = 0
        let targetPhase = ProcessInfo.processInfo.environment["PHOTOPREP_E1_PRESSURE_PHASE"] ?? "processing"
        while retouchPhase != targetPhase && retouchBusy && waited < 60 {
            try? await Task.sleep(for: .milliseconds(20))
            waited += 0.02
        }
        let phaseAtInject = retouchPhase
        let level = ProcessInfo.processInfo.environment["PHOTOPREP_E1_PRESSURE_LEVEL"] ?? "warning"
        let injected: MemoryPressure = level == "critical" ? .critical : .warning
        memoryPressure(injected)
        waited = 0
        while retouchBusy && waited < 30 {
            try? await Task.sleep(for: .milliseconds(20))
            waited += 0.02
        }
        let noResult = resultImage == nil
        let idle = !retouchBusy
        let report: [String: Any] = ["phaseAtInject": phaseAtInject, "noResult": noResult,
                                     "idle": idle, "pressure": "\(pressure)", "target": targetPhase, "level": level]
        writeDebugJSON(report, name: "e1.2-pressure-active")
        NSLog("PhotoPrep pressure active: phase=%@ noResult=%@ idle=%@", phaseAtInject, noResult ? "yes" : "no", idle ? "yes" : "no")
        NSApplication.shared.terminate(nil)
    }
    #endif
}
