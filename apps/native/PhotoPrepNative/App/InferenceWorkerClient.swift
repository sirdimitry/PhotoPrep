import Foundation
import Darwin

enum WorkerClientFailure: Error, Equatable, Sendable {
    case launchFailed
    case timedOut
    case cancelled
    case badResponse(String)
    case workerError(String)
    case processExited(Int32)
}

/// Parent side of the self-exec worker. The app binary becomes the worker when
/// launched with `--photoprep-worker`; it is a separate process with its own
/// crash domain and Core ML lifetime.
final class InferenceWorkerClient: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var cancelled = false

    func run(request: WorkerRequest, jobDirectory: URL, timeout: TimeInterval = 120, cancellation: CancellationFlag? = nil, onStart: ((Int32) -> Void)? = nil) throws -> WorkerResponse {
        lock.lock()
        cancelled = false
        lock.unlock()
        if cancellation?.isCancelled == true { throw WorkerClientFailure.cancelled }
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
        onStart?(process.processIdentifier)

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning {
            if isCancelled || cancellation?.isCancelled == true {
                terminateAndWait(process)
                throw WorkerClientFailure.cancelled
            }
            if Date() >= deadline {
                terminateAndWait(process)
                throw WorkerClientFailure.timedOut
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        if isCancelled || cancellation?.isCancelled == true {
            throw WorkerClientFailure.cancelled
        }
        let responseURL = jobDirectory.appendingPathComponent("response.json")
        let responseData = try? Data(contentsOf: responseURL)
        let decodedResponse = responseData.flatMap { try? JSONDecoder().decode(WorkerResponse.self, from: $0) }
        guard process.terminationStatus == 0 else {
            if let decodedResponse, decodedResponse.status == "error" {
                throw WorkerClientFailure.workerError(decodedResponse.error ?? "worker_failed")
            }
            throw WorkerClientFailure.processExited(process.terminationStatus)
        }
        guard let response = decodedResponse else {
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
        // The run loop owns the process wait. It observes this flag every 50 ms
        // and performs the confirmed SIGTERM -> SIGKILL wait before returning.
        lock.lock()
        cancelled = true
        lock.unlock()
    }

    /// Synchronous variant used when we must not leave a child behind while
    /// switching photos or closing the window.
    func cancelAndWait() {
        lock.lock()
        cancelled = true
        let process = self.process
        lock.unlock()
        if let process { terminateAndWait(process) }
    }

    private var isCancelled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancelled
    }

    /// Stop the child and do not return until it is gone and reaped. This is
    /// what makes job-directory cleanup and the next heavy job safe.
    private func terminateAndWait(_ process: Process) {
        guard process.isRunning else { return }
        let pid = process.processIdentifier
        process.terminate()
        let termDeadline = Date().addingTimeInterval(0.5)
        while process.isRunning && Date() < termDeadline {
            Thread.sleep(forTimeInterval: 0.02)
        }
        if process.isRunning {
            kill(pid, SIGKILL)
        }
        let killDeadline = Date().addingTimeInterval(2.0)
        while process.isRunning && Date() < killDeadline {
            Thread.sleep(forTimeInterval: 0.02)
        }
        if process.isRunning {
            kill(pid, SIGKILL)
        }
        process.waitUntilExit()
    }
}
