import SwiftUI
import AppKit
import UniformTypeIdentifiers
import CoreGraphics

enum RetouchTool: String, CaseIterable {
    case brush
    case eraser
}

@MainActor
final class WorkspaceModel: ObservableObject {
    @Published private(set) var photos: [PhotoHeader] = []
    @Published var selected: URL? {
        didSet {
            guard oldValue != selected else { return }
            cancelPreview()
            cancelRetouch()
            strokes = []
            resultImage = nil
            showingAfter = false
            retouchError = nil
            if selected != nil { requestPreview() }
        }
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

    var busy: Bool { importBusy || previewBusy || retouchBusy }

    private let decoder = PreviewDecoder()
    private let imageDecoder = StraightImageDecoder()
    private let worker = InferenceWorkerClient()
    private var importTask: Task<Void, Never>?
    private var previewTask: Task<Void, Never>?
    private var retouchTask: Task<Void, Never>?
    private var importGeneration = UUID()
    private var previewGeneration = UUID()
    private var retouchGeneration = UUID()
    private var maskRevision = 0
    private var editRevision = 0
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
    }

    func importPhotos() {
        guard !importBusy, !retouchBusy, pressure == .normal else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.jpeg, .png, .tiff, .bmp, .webP]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
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
        cancelRetouch()
    }

    func memoryPressure(_ pressure: MemoryPressure) {
        self.pressure = pressure
        guard pressure != .normal else { return }
        cancelPreview()
        cancelRetouch()
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
        resultImage = nil
        showingAfter = false
        retouchError = nil
    }

    func undoLastStroke() {
        guard !retouchBusy, !strokes.isEmpty else { return }
        strokes.removeLast()
        maskRevision += 1
        editRevision += 1
        resultImage = nil
        showingAfter = false
        retouchError = nil
    }

    func clearMask() {
        guard !retouchBusy, !strokes.isEmpty else { return }
        strokes.removeAll()
        maskRevision += 1
        editRevision += 1
        resultImage = nil
        showingAfter = false
        retouchError = nil
    }

    func processMask() {
        guard canProcess, let url = selected else { return }
        let snapshot = strokes
        let maskRevisionAtStart = maskRevision
        let editRevisionAtStart = editRevision
        let jobID = UUID()
        retouchGeneration = jobID
        retouchBusy = true
        retouchPhase = "preparing"
        retouchError = nil
        resultImage = nil
        showingAfter = false

        retouchTask = Task { [weak self] in
            guard let self else { return }
            var jobDirectory: URL?
            defer {
                if let jobDirectory { try? FileManager.default.removeItem(at: jobDirectory) }
            }
            do {
                let identity = try await Task.detached(priority: .userInitiated) {
                    try SourceIdentity.capture(url)
                }.value
                try Task.checkCancellation()
                let source = try await self.imageDecoder.decode(url: url)
                try Task.checkCancellation()
                let (mask, prepared) = try await Task.detached(priority: .userInitiated) {
                    let mask = MaskRenderer.render(width: source.width, height: source.height, strokes: snapshot)
                    guard !MaskRenderer.isEmpty(mask) else { throw RetouchFailure.emptyMask }
                    return (mask, try RetouchPreprocessor.prepare(source: source, mask: mask))
                }.value
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
                let response = try await Task.detached(priority: .userInitiated) { [worker] in
                    try worker.run(request: request, jobDirectory: directory)
                }.value
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
                        rect: prepared.rect
                    )
                }.value
                guard self.retouchGeneration == jobID,
                      self.maskRevision == maskRevisionAtStart,
                      self.editRevision == editRevisionAtStart,
                      self.selected == url else { return }
                self.resultImage = result
                self.showingAfter = true
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
            } catch is CancellationError {
                guard self.retouchGeneration == jobID else { return }
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
            } catch let error as WorkerClientFailure {
                guard self.retouchGeneration == jobID else { return }
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
                case .badResponse(let code):
                    self.retouchError = code
                }
            } catch {
                guard self.retouchGeneration == jobID else { return }
                self.retouchBusy = false
                self.retouchPhase = ""
                self.retouchTask = nil
                self.retouchError = Self.code(for: error)
            }
        }
    }

    func cancelRetouch() {
        retouchGeneration = UUID()
        worker.cancel()
        retouchTask?.cancel()
        retouchTask = nil
        retouchBusy = false
        retouchPhase = ""
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
            case .premultipliedAlpha: return "unsupported_alpha"
            case .insufficientMemory: return "memory"
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
}
