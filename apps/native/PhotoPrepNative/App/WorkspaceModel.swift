import SwiftUI
import AppKit
import UniformTypeIdentifiers

@MainActor
final class WorkspaceModel: ObservableObject {
    @Published private(set) var photos: [PhotoHeader] = []
    @Published var selected: URL? { didSet { requestPreview() } }
    @Published private(set) var preview: PhotoPreview?
    @Published private(set) var busy = false
    @Published private(set) var issue: ResourceFailure?
    @Published private(set) var pressure: MemoryPressure = .normal
    private let decoder = PreviewDecoder()
    private var task: Task<Void, Never>?
    private var generation = UUID()
    private var pressureSource: DispatchSourceMemoryPressure?

    init() {
        let source = DispatchSource.makeMemoryPressureSource(eventMask: [.normal, .warning, .critical], queue: .main)
        source.setEventHandler { [weak self] in
            Task { @MainActor [weak self] in
                guard let self, let data = self.pressureSource?.data else { return }
                self.memoryPressure(data.contains(.critical) ? .critical : data.contains(.warning) ? .warning : .normal)
            }
        }
        source.resume()
        pressureSource = source
    }

    func importPhotos() {
        guard !busy, pressure == .normal else { return }
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
        guard !busy, pressure == .normal else { return }
        cancel()
        let token = generation
        busy = true
        issue = nil
        task = Task { [weak self, decoder] in
            var added: [PhotoHeader] = []
            var failure: ResourceFailure?
            // Import is capped before enqueueing metadata requests; never create one
            // independent task per photo. No file contents are persisted in settings.
            let capacity = max(0, 10_000 - (self?.photos.count ?? 0))
            for url in urls.prefix(capacity) {
                do {
                    try Task.checkCancellation()
                    let header = try await decoder.header(url: url)
                    added.append(header)
                } catch is CancellationError { break }
                catch { failure = error as? ResourceFailure ?? .invalidImage }
            }
            guard let self, !Task.isCancelled, token == self.generation else { return }
            var known = Set(self.photos.map(\.url))
            self.photos += added.filter { known.insert($0.url).inserted }
            self.busy = false
            self.issue = failure
            if self.selected == nil { self.selected = self.photos.first?.url }
        }
    }

    private func requestPreview() {
        cancel()
        preview = nil
        guard let selected, pressure == .normal else { return }
        let token = generation
        busy = true
        issue = nil
        task = Task { [weak self, decoder] in
            do {
                let result = try await decoder.preview(url: selected)
                guard let self, !Task.isCancelled, token == self.generation else { return }
                self.preview = result
                self.busy = false
            } catch {
                guard let self, !Task.isCancelled, token == self.generation else { return }
                self.issue = error as? ResourceFailure ?? .invalidImage
                self.busy = false
            }
        }
    }

    func cancel() {
        generation = UUID()
        task?.cancel()
        task = nil
        busy = false
    }

    func memoryPressure(_ pressure: MemoryPressure) {
        self.pressure = pressure
        guard pressure != .normal else { return }
        cancel()
        preview = nil
        issue = .memoryPressure
    }

    func clear() {
        cancel()
        selected = nil
        photos.removeAll()
        preview = nil
        issue = nil
    }

    func suspend() {
        cancel()
        preview = nil
    }

    func resume() {
        if selected != nil, preview == nil { requestPreview() }
    }
}
