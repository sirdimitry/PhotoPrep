import Foundation
import CoreML

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

            let loadStart = Date()
            let configuration = MLModelConfiguration()
            configuration.computeUnits = .cpuAndGPU
            let model = try MLModel(contentsOf: URL(fileURLWithPath: request.modelPath), configuration: configuration)
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

    static func crashSelfTest() -> Int32 {
        guard let job = makeDiagnosticJob() else {
            print("crash self-test: setup failed")
            return 1
        }
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
            print("crash self-test: unexpectedly succeeded")
            return 1
        } catch {
            print("crash self-test: app survived worker failure: \(error)")
            return 0
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
        return box.value == "cancelled" ? 0 : 1
    }
}
