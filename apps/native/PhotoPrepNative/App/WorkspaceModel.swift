import SwiftUI
import AppKit
import UniformTypeIdentifiers
import CoreGraphics

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
            retouchError = nil
            showingAfter = false
            if let selected {
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
            // The source changed. Never display or use a result from another
            // byte sequence/mtime; discard the pixel result and stale recipes.
            state.passes = []
            state.mask = []
            state.sourceIdentity = current
            editStates[url] = state
            strokes = []
            passCount = 0
            resultImage = nil
            pixelCache.clear()
            cacheBytes = 0
            retouchError = "source_changed"
            return
        }
        if state.sourceIdentity == nil, let current { state.sourceIdentity = current }
        editStates[url] = state
        strokes = state.mask
        passCount = state.passes.count
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
    private var sessionURL: URL?

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

    init() {
        let source = DispatchSource.makeMemoryPressureSource(eventMask: [.normal, .warning, .critical], queue: .main)
        source.setEventHandler { [weak self] in
            guard let self else { return }
            // Capture data synchronously in the handler; reading it from a
            // later Task can observe a different/coalesced event.
            let data = self.pressureSource?.data ?? []
            Task { @MainActor [weak self] in
                guard let self else { return }
                let next: MemoryPressure = data.contains(.critical) ? .critical : data.contains(.warning) ? .warning : .normal
                self.memoryPressure(next)
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
        panel.allowedContentTypes = [.json]
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        #if DEBUG
        if let directory = DebugLaunchOptions.panelDirectory { panel.directoryURL = directory }
        #endif
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor [weak self] in self?.openSession(url) }
        }
    }

    func saveSessionPanel() {
        guard !photos.isEmpty, !busy, pressure == .normal else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = sessionURL?.lastPathComponent ?? "Untitled.photoprep.json"
        panel.begin { [weak self] response in
            guard response == .OK, var url = panel.url else { return }
            if !url.lastPathComponent.lowercased().hasSuffix(".photoprep.json") {
                url = url.deletingPathExtension().appendingPathExtension("photoprep.json")
            }
            Task { @MainActor [weak self] in self?.saveSession(to: url) }
        }
    }

    func openSession(_ url: URL) {
        let workspace: SessionWorkspace
        do { workspace = try SessionCodec.load(url) } catch {
            retouchError = (error as? SessionError)?.code ?? "session_invalid"
            return
        }
        clear()
        sessionURL = url
        sessionReadOnly = workspace.readOnlyReason
        let urls = workspace.photos.map(\.url)
        importURLs(urls)
        Task { @MainActor [weak self] in
            guard let self else { return }
            var waited = 0.0
            while (self.importBusy || self.photos.isEmpty) && waited < 60 {
                try? await Task.sleep(for: .milliseconds(100)); waited += 0.1
            }
            for photo in workspace.photos {
                var state = PhotoEditState()
                state.mask = workspace.readOnly ? [] : photo.mask
                state.passes = workspace.readOnly ? [] : photo.passes.map {
                    RetouchPass(strokes: $0.strokes, modelID: $0.modelID)
                }
                self.editStates[photo.url] = state
            }
            if let selected = workspace.selected {
                // Force didSet even when the imported session selected the
                // already-selected URL, so masks/passes and replay load.
                self.selected = nil
                self.selected = selected
            }
            if workspace.readOnly {
                self.retouchError = "session_read_only"
                self.sessionReadOnly = workspace.readOnlyReason
            }
        }
    }

    func saveSession(to url: URL) {
        var workspace = SessionWorkspace(version: 3, photos: [], selected: selected,
                                         outputWidth: 1136, outputHeight: 710)
        workspace.photos = photos.map { photo in
            let state = editStates[photo.url] ?? PhotoEditState()
            return SessionPhoto(url: photo.url, view: SessionView(), mask: state.mask,
                                passes: state.passes.map { SessionPass(strokes: $0.strokes, modelID: $0.modelID) })
        }
        do {
            try SessionCodec.save(workspace, to: url)
            sessionURL = url
            sessionReadOnly = nil
            retouchError = nil
        } catch {
            retouchError = (error as? SessionError)?.code ?? "session_save_failed"
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
            self.photos += added.filter { known.insert($0.url).inserted }
            self.importBusy = false
            self.importTask = nil
            self.issue = failure
            if self.selected == nil { self.selected = self.photos.first?.url }
        }
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

    /// Used by window close/termination and destructive collection actions.
    func cancel() {
        cancelImport()
        cancelPreview()
        cancelRetouch(wait: true)
    }

    func memoryPressure(_ pressure: MemoryPressure) {
        self.pressure = pressure
        guard pressure != .normal else { return }
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

    var canUndoStroke: Bool { !strokes.isEmpty && !retouchBusy }
    var canProcess: Bool { selected != nil && !strokes.isEmpty && !retouchBusy && !importBusy && pressure == .normal }

    func addStroke(_ stroke: MaskStroke) {
        guard !retouchBusy, !stroke.points.isEmpty else { return }
        strokes.append(stroke)
        maskRevision += 1
        editRevision += 1
        if let selected { editStates[selected, default: PhotoEditState()].mask = strokes }
        showingAfter = false
        retouchError = nil
    }

    func undoLastStroke() {
        guard !retouchBusy, !strokes.isEmpty else { return }
        strokes.removeLast()
        maskRevision += 1
        editRevision += 1
        if let selected { editStates[selected, default: PhotoEditState()].mask = strokes }
        showingAfter = false
        retouchError = nil
    }

    func clearMask() {
        guard !retouchBusy, !strokes.isEmpty else { return }
        strokes.removeAll()
        maskRevision += 1
        editRevision += 1
        if let selected { editStates[selected, default: PhotoEditState()].mask = [] }
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

    var canUndoPass: Bool {
        guard let selected else { return false }
        return !retouchBusy && (editStates[selected]?.passes.isEmpty == false)
    }

    /// Undo the last completed removal, restore its mask for refinement, and
    /// leave earlier passes intact.
    func undoLastPass() {
        guard !retouchBusy, let url = selected, var state = editStates[url],
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

    private func startRestoreIfNeeded() {
        guard !retouchBusy, retouchActiveID == nil, let url = selected,
              let state = editStates[url], !state.passes.isEmpty,
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

    func cancelRetouch(wait: Bool = false) {
        guard let active = retouchActiveID else { return }
        retouchGeneration = UUID()
        retouchCancellation?.cancel()
        worker.cancel()
        if wait { worker.cancelAndWait() }
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

    private func writeDebugJSON(_ value: [String: Any], name: String) {
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
        saveSession(to: session)
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
        let cleared = resultImage == nil && passCount == 0 && retouchError == "source_changed"
        let report: [String: Any] = ["cacheWasPresent": had, "sourceChangeCleared": cleared,
                                     "error": retouchError ?? "", "passCount": passCount]
        writeDebugJSON(report, name: "e1.4-cache-source")
        NSLog("E1.4 cache-source: had=\(had ? "yes" : "no") cleared=\(cleared ? "yes" : "no")")
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
