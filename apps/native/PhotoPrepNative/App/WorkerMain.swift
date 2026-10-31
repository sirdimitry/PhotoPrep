import Foundation
import CoreML
import Darwin
import ImageIO
import UniformTypeIdentifiers
import CoreGraphics

/// Command-line mode of the app binary. It is launched by the UI process with
/// `--photoprep-worker <job-directory>` and never initializes SwiftUI/AppKit.
enum WorkerMain {
    static func run(arguments: [String]) -> Int32 {
        guard let flag = arguments.firstIndex(of: "--photoprep-worker"),
              arguments.indices.contains(flag + 1) else {
            return 2
        }
        let jobDirectory = URL(fileURLWithPath: arguments[flag + 1], isDirectory: true)
        return autoreleasepool {
            runJob(jobDirectory: jobDirectory)
        }
    }

    private static func runJob(jobDirectory: URL) -> Int32 {
        let requestURL = jobDirectory.appendingPathComponent("request.json")
        let responseURL = jobDirectory.appendingPathComponent("response.json")
        var jobID = "unknown"
        do {
            let request = try JSONDecoder().decode(WorkerRequest.self, from: Data(contentsOf: requestURL))
            jobID = request.jobID
            guard request.width == 512, request.height == 512 else {
                throw WorkerFailure.invalidInput
            }
            let imageData = try Data(contentsOf: URL(fileURLWithPath: request.imagePath))
            let maskData = try Data(contentsOf: URL(fileURLWithPath: request.maskPath))
            guard imageData.count == 3 * 512 * 512 * MemoryLayout<Float>.size,
                  maskData.count == 512 * 512 * MemoryLayout<Float>.size else {
                throw WorkerFailure.invalidInput
            }

            if ProcessInfo.processInfo.environment["PHOTOPREP_E1_HANG"] == "1" {
                Thread.sleep(forTimeInterval: 30)
            }
            let loadStart = Date()
            let configuration = MLModelConfiguration()
            configuration.computeUnits = .cpuAndGPU
            let model: MLModel
            do {
                model = try MLModel(contentsOf: URL(fileURLWithPath: request.modelPath), configuration: configuration)
            } catch {
                throw WorkerFailure.modelLoad
            }
            let loadSeconds = Date().timeIntervalSince(loadStart)

            let image = try makeArray(shape: [1, 3, 512, 512], data: imageData)
            let mask = try makeArray(shape: [1, 1, 512, 512], data: maskData)
            let provider = try MLDictionaryFeatureProvider(dictionary: [
                "image": MLFeatureValue(multiArray: image),
                "mask": MLFeatureValue(multiArray: mask),
            ])

            let predictStart = Date()
            let prediction = try model.prediction(from: provider)
            let predictSeconds = Date().timeIntervalSince(predictStart)
            guard let output = prediction.featureValue(for: "output")?.multiArrayValue else {
                throw WorkerFailure.invalidOutput
            }
            guard output.dataType == .float32,
                  output.shape.map({ $0.intValue }) == [1, 3, 512, 512] else {
                throw WorkerFailure.invalidOutput
            }
            let count = 3 * 512 * 512
            let floats = output.dataPointer.bindMemory(to: Float.self, capacity: count)
            for index in 0..<count where !floats[index].isFinite {
                throw WorkerFailure.nonFinite
            }
            let outputData = Data(bytes: output.dataPointer, count: count * MemoryLayout<Float>.size)
            try outputData.write(to: URL(fileURLWithPath: request.outputPath), options: .atomic)
            let response = WorkerResponse(
                jobID: jobID,
                status: "ok",
                error: nil,
                outputPath: request.outputPath,
                loadSeconds: loadSeconds,
                predictSeconds: predictSeconds
            )
            try JSONEncoder().encode(response).write(to: responseURL, options: .atomic)
            return 0
        } catch {
            let response = WorkerResponse(jobID: jobID, status: "error", error: Self.code(for: error))
            try? JSONEncoder().encode(response).write(to: responseURL, options: .atomic)
            return 1
        }
    }

    private static func makeArray(shape: [Int], data: Data) throws -> MLMultiArray {
        let array = try MLMultiArray(shape: shape.map(NSNumber.init(value:)), dataType: .float32)
        guard array.count == data.count / MemoryLayout<Float>.size else { throw WorkerFailure.invalidInput }
        data.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { return }
            memcpy(array.dataPointer, base, data.count)
        }
        return array
    }

    private static func code(for error: Error) -> String {
        if let failure = error as? WorkerFailure {
            return failure.rawValue
        }
        return "worker_failed"
    }
}

private enum WorkerFailure: String, Error {
    case modelLoad = "model_load_failed"
    case invalidInput = "invalid_input"
    case invalidOutput = "invalid_output"
    case nonFinite = "non_finite_output"
}

extension WorkerMain {
    /// Debug-only end-to-end check used by `--photoprep-e1-selftest`. It runs
    /// the same parent client + self-exec worker path as the UI, but without
    /// SwiftUI, so cancellation and process boundaries can be tested from a
    /// signed app bundle.
    static func selfTest() -> Int32 {
        let environment = ProcessInfo.processInfo.environment
        let width = Int(environment["PHOTOPREP_E1_WIDTH"] ?? "") ?? 1024
        let height = Int(environment["PHOTOPREP_E1_HEIGHT"] ?? "") ?? 768
        guard width > 0, height > 0, width * height <= 40_000_000 else {
            print("self-test: unsupported dimensions")
            return 1
        }
        print("self-test: source=\(width)x\(height) phys_before=\(SystemMemory.physicalFootprintBytes() ?? 0)")
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        for y in 0..<height {
            for x in 0..<width {
                let index = (y * width + x) * 4
                pixels[index] = UInt8((x * 255) / width)
                pixels[index + 1] = UInt8((y * 255) / height)
                pixels[index + 2] = UInt8(((x + y) * 255) / (width + height))
                pixels[index + 3] = UInt8((x * 7) % 256)
            }
        }
        let source = StraightImage(width: width, height: height, pixels: pixels)
        let strokes = [
            MaskStroke(points: [MaskPoint(x: 0.3, y: 0.3), MaskPoint(x: 0.7, y: 0.3)], width: 0.18),
            MaskStroke(points: [MaskPoint(x: 0.3, y: 0.5), MaskPoint(x: 0.7, y: 0.5)], width: 0.18),
            MaskStroke(points: [MaskPoint(x: 0.3, y: 0.7), MaskPoint(x: 0.7, y: 0.7)], width: 0.18),
        ]
        let mask = MaskRenderer.render(width: width, height: height, strokes: strokes)
        guard !MaskRenderer.isEmpty(mask) else { print("self-test: empty mask"); return 1 }
        let prepared: PreparedInput
        do {
            prepared = try RetouchPreprocessor.prepare(source: source, mask: mask)
        } catch {
            print("self-test: prepare failed \(error)")
            return 1
        }
        guard let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
            print("self-test: model missing")
            return 1
        }
        let jobID = UUID()
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("PhotoPrep Native/Jobs", isDirectory: true)
        let directory = support.appendingPathComponent(jobID.uuidString, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let imageData = prepared.image.withUnsafeBufferPointer { Data(buffer: $0) }
            let maskData = prepared.mask.withUnsafeBufferPointer { Data(buffer: $0) }
            try imageData.write(to: directory.appendingPathComponent("image.f32"))
            try maskData.write(to: directory.appendingPathComponent("mask.f32"))
        } catch {
            print("self-test: staging failed \(error)")
            return 1
        }
        defer { try? FileManager.default.removeItem(at: directory) }
        let request = WorkerRequest(
            jobID: jobID.uuidString,
            modelPath: model.path,
            imagePath: directory.appendingPathComponent("image.f32").path,
            maskPath: directory.appendingPathComponent("mask.f32").path,
            outputPath: directory.appendingPathComponent("output.f32").path
        )
        do {
            let response = try InferenceWorkerClient().run(request: request, jobDirectory: directory)
            guard let outputPath = response.outputPath else { print("self-test: no output path"); return 1 }
            let data = try Data(contentsOf: URL(fileURLWithPath: outputPath))
            guard data.count == 3 * 512 * 512 * MemoryLayout<Float>.size else { print("self-test: bad output size"); return 1 }
            var predicted = [Float](repeating: 0, count: 3 * 512 * 512)
            _ = predicted.withUnsafeMutableBytes { data.copyBytes(to: $0) }
            guard predicted.allSatisfy({ $0.isFinite }) else { print("self-test: non-finite"); return 1 }
            let result = try RetouchPreprocessor.composite(source: source, coverage: mask, predicted: predicted, rect: prepared.rect)
            var changedOutside = 0
            var changedAlpha = 0
            for index in 0..<(width * height) where mask[index] == 0 {
                let offset = index * 4
                if Array(result.pixels[offset..<(offset + 4)]) != Array(source.pixels[offset..<(offset + 4)]) {
                    changedOutside += 1
                }
            }
            for index in 0..<(width * height) {
                if result.pixels[index * 4 + 3] != source.pixels[index * 4 + 3] { changedAlpha += 1 }
            }
            print("self-test: outside=\(changedOutside) alpha=\(changedAlpha) rect=\(prepared.rect.width)x\(prepared.rect.height) load=\(response.loadSeconds ?? 0) predict=\(response.predictSeconds ?? 0) phys_after=\(SystemMemory.physicalFootprintBytes() ?? 0)")
            return changedOutside == 0 && changedAlpha == 0 ? 0 : 1
        } catch {
            print("self-test: worker failed \(error)")
            return 1
        }
    }
}

extension WorkerMain {
    static func timeoutSelfTest() -> Int32 {
        guard let job = makeDiagnosticJob(), let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
            print("timeout self-test: setup failed")
            return 1
        }
        defer { try? FileManager.default.removeItem(at: job) }
        let request = WorkerRequest(
            jobID: UUID().uuidString,
            modelPath: model.path,
            imagePath: job.appendingPathComponent("image.f32").path,
            maskPath: job.appendingPathComponent("mask.f32").path,
            outputPath: job.appendingPathComponent("output.f32").path
        )
        do {
            _ = try InferenceWorkerClient().run(request: request, jobDirectory: job, timeout: 0.05)
            print("timeout self-test: unexpectedly succeeded")
            return 1
        } catch WorkerClientFailure.timedOut {
            print("timeout self-test: ok (worker stopped)")
            return 0
        } catch {
            print("timeout self-test: wrong error \(error)")
            return 1
        }
    }

    static func failureSelfTest() -> Int32 {
        guard let job = makeDiagnosticJob() else { print("failure self-test: setup failed"); return 1 }
        defer { try? FileManager.default.removeItem(at: job) }
        let request = WorkerRequest(
            jobID: UUID().uuidString,
            modelPath: job.appendingPathComponent("missing.mlmodelc").path,
            imagePath: job.appendingPathComponent("image.f32").path,
            maskPath: job.appendingPathComponent("mask.f32").path,
            outputPath: job.appendingPathComponent("output.f32").path
        )
        do {
            _ = try InferenceWorkerClient().run(request: request, jobDirectory: job, timeout: 30)
            print("failure self-test: unexpectedly succeeded")
            return 1
        } catch WorkerClientFailure.workerError(let code) {
            print("failure self-test: ordinary error \(code)")
            return code == "model_load_failed" ? 0 : 1
        } catch {
            print("failure self-test: wrong error \(error)")
            return 1
        }
    }

    static func crashSelfTest() -> Int32 {
        guard let job = makeDiagnosticJob(), let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
            print("crash self-test: setup failed")
            return 1
        }
        defer { try? FileManager.default.removeItem(at: job) }
        let request = WorkerRequest(
            jobID: UUID().uuidString,
            modelPath: model.path,
            imagePath: job.appendingPathComponent("image.f32").path,
            maskPath: job.appendingPathComponent("mask.f32").path,
            outputPath: job.appendingPathComponent("output.f32").path
        )
        do {
            _ = try InferenceWorkerClient().run(request: request, jobDirectory: job, timeout: 30, onStart: { pid in kill(pid, SIGKILL) })
            print("crash self-test: unexpectedly succeeded")
            return 1
        } catch WorkerClientFailure.processExited(let status) {
            print("crash self-test: worker crashed with status \(status)")
            return status == 9 ? 0 : 1
        } catch {
            print("crash self-test: wrong error \(error)")
            return 1
        }
    }

    static func hangSelfTest() -> Int32 {
        guard let job = makeDiagnosticJob(), let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
            print("hang self-test: setup failed")
            return 1
        }
        defer { try? FileManager.default.removeItem(at: job) }
        setenv("PHOTOPREP_E1_HANG", "1", 1)
        defer { unsetenv("PHOTOPREP_E1_HANG") }
        let request = WorkerRequest(
            jobID: UUID().uuidString,
            modelPath: model.path,
            imagePath: job.appendingPathComponent("image.f32").path,
            maskPath: job.appendingPathComponent("mask.f32").path,
            outputPath: job.appendingPathComponent("output.f32").path
        )
        do {
            _ = try InferenceWorkerClient().run(request: request, jobDirectory: job, timeout: 0.2)
            print("hang self-test: unexpectedly succeeded")
            return 1
        } catch WorkerClientFailure.timedOut {
            print("hang self-test: timed out and worker stopped")
            return 0
        } catch {
            print("hang self-test: wrong error \(error)")
            return 1
        }
    }

    static func cancelBeforeStartSelfTest() -> Int32 {
        guard let job = makeDiagnosticJob(), let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
            print("cancel-before-start self-test: setup failed")
            return 1
        }
        defer { try? FileManager.default.removeItem(at: job) }
        let flag = CancellationFlag()
        flag.cancel()
        let request = WorkerRequest(
            jobID: UUID().uuidString,
            modelPath: model.path,
            imagePath: job.appendingPathComponent("image.f32").path,
            maskPath: job.appendingPathComponent("mask.f32").path,
            outputPath: job.appendingPathComponent("output.f32").path
        )
        do {
            _ = try InferenceWorkerClient().run(request: request, jobDirectory: job, timeout: 30, cancellation: flag)
            print("cancel-before-start self-test: unexpectedly succeeded")
            return 1
        } catch WorkerClientFailure.cancelled {
            print("cancel-before-start self-test: cancelled before launch")
            return 0
        } catch {
            print("cancel-before-start self-test: wrong error \(error)")
            return 1
        }
    }

    private static func makeDiagnosticJob() -> URL? {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("PhotoPrep Native/Jobs", isDirectory: true)
        let job = support.appendingPathComponent(UUID().uuidString, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
            let image = [Float](repeating: 0.5, count: 3 * 512 * 512)
            let mask = [Float](repeating: 0, count: 512 * 512)
            try image.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: job.appendingPathComponent("image.f32"))
            try mask.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: job.appendingPathComponent("mask.f32"))
            return job
        } catch {
            return nil
        }
    }
}

extension WorkerMain {
    static func cancelSelfTest() -> Int32 {
        guard let job = makeDiagnosticJob(), let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
            print("cancel self-test: setup failed")
            return 1
        }
        defer { try? FileManager.default.removeItem(at: job) }
        let client = InferenceWorkerClient()
        let request = WorkerRequest(
            jobID: UUID().uuidString,
            modelPath: model.path,
            imagePath: job.appendingPathComponent("image.f32").path,
            maskPath: job.appendingPathComponent("mask.f32").path,
            outputPath: job.appendingPathComponent("output.f32").path
        )
        let semaphore = DispatchSemaphore(value: 0)
        final class Box: @unchecked Sendable { var value = "" }
        let box = Box()
        Task.detached {
            do {
                _ = try client.run(request: request, jobDirectory: job, timeout: 60)
                box.value = "succeeded"
            } catch WorkerClientFailure.cancelled {
                box.value = "cancelled"
            } catch {
                box.value = "other:\(error)"
            }
            semaphore.signal()
        }
        Thread.sleep(forTimeInterval: 0.2)
        client.cancel()
        _ = semaphore.wait(timeout: .now() + 10)
        print("cancel self-test: \(box.value)")
        guard box.value == "cancelled" else { return 1 }
        guard let second = makeDiagnosticJob() else { print("cancel self-test: second setup failed"); return 1 }
        defer { try? FileManager.default.removeItem(at: second) }
        let secondRequest = WorkerRequest(
            jobID: UUID().uuidString,
            modelPath: model.path,
            imagePath: second.appendingPathComponent("image.f32").path,
            maskPath: second.appendingPathComponent("mask.f32").path,
            outputPath: second.appendingPathComponent("output.f32").path
        )
        do {
            _ = try InferenceWorkerClient().run(request: secondRequest, jobDirectory: second, timeout: 30)
            print("cancel self-test: restart after cancel ok")
            return 0
        } catch {
            print("cancel self-test: restart failed \(error)")
            return 1
        }
    }
}

extension WorkerMain {
    /// Real-photo check: decode a permitted file through StraightImageDecoder,
    /// run the same worker, composite and write a PNG for visual review.
    static func fileSelfTest() -> Int32 {
        guard let path = ProcessInfo.processInfo.environment["PHOTOPREP_E1_FILE"], !path.isEmpty,
              let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
            print("file self-test: missing PHOTOPREP_E1_FILE or model")
            return 1
        }
        let url = URL(fileURLWithPath: path)
        final class Box: @unchecked Sendable { var image: StraightImage?; var error = "" }
        let box = Box()
        let semaphore = DispatchSemaphore(value: 0)
        Task.detached {
            do {
                let decoder = StraightImageDecoder()
                box.image = try await decoder.decode(url: url)
            } catch {
                box.error = String(describing: error)
            }
            semaphore.signal()
        }
        _ = semaphore.wait(timeout: .now() + 60)
        guard let source = box.image else {
            print("file self-test: decode failed \(box.error)")
            return 1
        }
        let width = source.width
        let height = source.height
        let strokes = [
            MaskStroke(points: [MaskPoint(x: 0.02, y: 0.03), MaskPoint(x: 0.38, y: 0.03)], width: 0.16),
            MaskStroke(points: [MaskPoint(x: 0.02, y: 0.12), MaskPoint(x: 0.38, y: 0.12)], width: 0.16),
            MaskStroke(points: [MaskPoint(x: 0.02, y: 0.21), MaskPoint(x: 0.38, y: 0.21)], width: 0.16),
        ]
        let mask = MaskRenderer.render(width: width, height: height, strokes: strokes)
        guard !MaskRenderer.isEmpty(mask), let prepared = try? RetouchPreprocessor.prepare(source: source, mask: mask) else {
            print("file self-test: mask/prepare failed")
            return 1
        }
        let jobID = UUID()
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("PhotoPrep Native/Jobs", isDirectory: true)
        let directory = support.appendingPathComponent(jobID.uuidString, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try prepared.image.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: directory.appendingPathComponent("image.f32"))
            try prepared.mask.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: directory.appendingPathComponent("mask.f32"))
        } catch {
            print("file self-test: staging failed \(error)")
            return 1
        }
        defer { try? FileManager.default.removeItem(at: directory) }
        let request = WorkerRequest(
            jobID: jobID.uuidString,
            modelPath: model.path,
            imagePath: directory.appendingPathComponent("image.f32").path,
            maskPath: directory.appendingPathComponent("mask.f32").path,
            outputPath: directory.appendingPathComponent("output.f32").path
        )
        do {
            let response = try InferenceWorkerClient().run(request: request, jobDirectory: directory)
            guard let outputPath = response.outputPath else { print("file self-test: no output"); return 1 }
            let data = try Data(contentsOf: URL(fileURLWithPath: outputPath))
            guard data.count == 3 * 512 * 512 * MemoryLayout<Float>.size else { print("file self-test: bad output"); return 1 }
            var predicted = [Float](repeating: 0, count: 3 * 512 * 512)
            _ = predicted.withUnsafeMutableBytes { data.copyBytes(to: $0) }
            guard predicted.allSatisfy({ $0.isFinite }) else { print("file self-test: non-finite"); return 1 }
            let result = try RetouchPreprocessor.composite(source: source, coverage: mask, predicted: predicted, rect: prepared.rect)
            var outside = 0
            var alpha = 0
            for index in 0..<(width * height) where mask[index] == 0 {
                let offset = index * 4
                if Array(result.pixels[offset..<(offset + 4)]) != Array(source.pixels[offset..<(offset + 4)]) { outside += 1 }
            }
            for index in 0..<(width * height) where result.pixels[index * 4 + 3] != source.pixels[index * 4 + 3] { alpha += 1 }
            let outputURL = url.deletingPathExtension().appendingPathExtension("native.png")
            if let cg = result.cgImage(), let destination = CGImageDestinationCreateWithURL(outputURL as CFURL, UTType.png.identifier as CFString, 1, nil) {
                CGImageDestinationAddImage(destination, cg, nil)
                _ = CGImageDestinationFinalize(destination)
            }
            if let dumpPath = ProcessInfo.processInfo.environment["PHOTOPREP_E1_DUMP"], !dumpPath.isEmpty {
                let dump = URL(fileURLWithPath: dumpPath, isDirectory: true)
                try? FileManager.default.createDirectory(at: dump, withIntermediateDirectories: true)
                if let cg = source.cgImage() { Self.writePNG(cg, to: dump.appendingPathComponent("source-native.png")) }
                if let maskImage = Self.grayImage(mask, width: width, height: height) { Self.writePNG(maskImage, to: dump.appendingPathComponent("mask-native.png")) }
                try? prepared.image.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: dump.appendingPathComponent("image512-native.f32"))
                try? prepared.mask.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: dump.appendingPathComponent("mask512-native.f32"))
                try? Data(contentsOf: URL(fileURLWithPath: outputPath)).write(to: dump.appendingPathComponent("model-native.f32"))
                if let cg = result.cgImage() { Self.writePNG(cg, to: dump.appendingPathComponent("final-native.png")) }
                let context = ["x": prepared.rect.x, "y": prepared.rect.y, "width": prepared.rect.width, "height": prepared.rect.height,
                               "sourceWidth": width, "sourceHeight": height] as [String: Int]
                if let data = try? JSONSerialization.data(withJSONObject: context, options: [.prettyPrinted]) { try? data.write(to: dump.appendingPathComponent("context-native.json")) }
            }
            print("file self-test: source=\(width)x\(height) outside=\(outside) alpha=\(alpha) rect=\(prepared.rect.width)x\(prepared.rect.height) output=\(outputURL.path) load=\(response.loadSeconds ?? 0) predict=\(response.predictSeconds ?? 0) phys=\(SystemMemory.physicalFootprintBytes() ?? 0)")
            return outside == 0 && alpha == 0 ? 0 : 1
        } catch {
            print("file self-test: worker failed \(error)")
            return 1
        }
    }

    private static func writePNG(_ image: CGImage, to url: URL) {
        guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else { return }
        CGImageDestinationAddImage(destination, image, nil)
        _ = CGImageDestinationFinalize(destination)
    }

    private static func grayImage(_ bytes: [UInt8], width: Int, height: Int) -> CGImage? {
        guard width > 0, height > 0, bytes.count == width * height,
              let provider = CGDataProvider(data: Data(bytes) as CFData) else { return nil }
        return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 8,
                       bytesPerRow: width, space: CGColorSpaceCreateDeviceGray(),
                       bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)
    }
}

extension WorkerMain {
    static func pressureSelfTest() -> Int32 {
        final class Box: @unchecked Sendable { var ok = false; var message = ""; var done = false }
        let box = Box()
        Task { @MainActor in
            let model = WorkspaceModel()
            model.memoryPressure(.warning)
            let warningOK = model.pressure == .warning && !model.retouchBusy && model.preview == nil
            model.memoryPressure(.critical)
            let criticalOK = model.pressure == .critical && !model.retouchBusy && model.retouchPhase.isEmpty
            model.memoryPressure(.normal)
            box.ok = warningOK && criticalOK && model.pressure == .normal
            box.message = "warning=\(warningOK) critical=\(criticalOK)"
            box.done = true
        }
        let deadline = Date().addingTimeInterval(10)
        while !box.done && Date() < deadline {
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        }
        print("pressure self-test: \(box.message) ok=\(box.ok)")
        return box.ok ? 0 : 1
    }
}

extension WorkerMain {
    static func stressSelfTest() -> Int32 {
        let iterations = Int(ProcessInfo.processInfo.environment["PHOTOPREP_E1_STRESS"] ?? "20") ?? 20
        let client = InferenceWorkerClient()
        var worst = 0
        for index in 1...max(1, iterations) {
            guard let job = makeDiagnosticJob(), let model = Bundle.main.url(forResource: "LaMa-fp32", withExtension: "mlmodelc", subdirectory: "Models") else {
                print("stress self-test: setup failed at \(index)")
                return 1
            }
            let request = WorkerRequest(
                jobID: UUID().uuidString,
                modelPath: model.path,
                imagePath: job.appendingPathComponent("image.f32").path,
                maskPath: job.appendingPathComponent("mask.f32").path,
                outputPath: job.appendingPathComponent("output.f32").path
            )
            do {
                _ = try client.run(request: request, jobDirectory: job, timeout: 30)
                let phys = Int(SystemMemory.physicalFootprintBytes() ?? 0)
                worst = max(worst, phys)
                if index % 5 == 0 || index == iterations {
                    print("stress self-test: \(index)/\(iterations) phys=\(phys)")
                }
            } catch {
                print("stress self-test: iteration \(index) failed \(error)")
                try? FileManager.default.removeItem(at: job)
                return 1
            }
            try? FileManager.default.removeItem(at: job)
        }
        print("stress self-test: completed \(iterations), worst phys=\(worst)")
        return 0
    }
}
