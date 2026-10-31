import Foundation
import Darwin

enum WorkerClientFailure: Error, Equatable, Sendable {
    case launchFailed
    case timedOut
    case cancelled
    case badResponse(String)
    case processExited(Int32)
}

/// Parent side of the self-exec worker. The app binary becomes the worker when
/// launched with `--photoprep-worker`; it is a separate process with its own
/// crash domain and Core ML lifetime.
final class InferenceWorkerClient: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var cancelled = false

    func run(request: WorkerRequest, jobDirectory: URL, timeout: TimeInterval = 120) throws -> WorkerResponse {
        lock.lock()
        cancelled = false
        lock.unlock()
        let requestURL = jobDirectory.appendingPathComponent("request.json")
        try JSONEncoder().encode(request).write(to: requestURL, options: .atomic)

        let process = Process()
        process.executableURL = Bundle.main.executableURL
        process.arguments = ["--photoprep-worker", jobDirectory.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        lock.lock()
        self.process = process
        lock.unlock()
        defer {
            lock.lock()
            self.process = nil
            lock.unlock()
        }

        do {
            try process.run()
        } catch {
            throw WorkerClientFailure.launchFailed
        }

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning {
            if isCancelled {
                terminate(process)
                throw WorkerClientFailure.cancelled
            }
            if Date() >= deadline {
                terminate(process)
                throw WorkerClientFailure.timedOut
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        if isCancelled {
            throw WorkerClientFailure.cancelled
        }
        guard process.terminationStatus == 0 else {
            throw WorkerClientFailure.processExited(process.terminationStatus)
        }
        let responseURL = jobDirectory.appendingPathComponent("response.json")
        guard let data = try? Data(contentsOf: responseURL),
              let response = try? JSONDecoder().decode(WorkerResponse.self, from: data) else {
            throw WorkerClientFailure.badResponse("missing_response")
        }
        guard response.jobID == request.jobID else {
            throw WorkerClientFailure.badResponse("job_id_mismatch")
        }
        guard response.status == "ok" else {
            throw WorkerClientFailure.badResponse(response.error ?? "worker_failed")
        }
        return response
    }

    func cancel() {
        lock.lock()
        cancelled = true
        let process = self.process
        lock.unlock()
        if let process {
            terminate(process)
        }
    }

    private var isCancelled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancelled
    }

    private func terminate(_ process: Process) {
        guard process.isRunning else { return }
        process.terminate()
        let pid = process.processIdentifier
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.5) {
            if process.isRunning {
                kill(pid, SIGKILL)
            }
        }
    }
}
