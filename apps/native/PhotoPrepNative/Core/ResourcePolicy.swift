import Foundation
import Darwin

public enum ResourceFailure: Error, Equatable, Sendable {
    case invalidDimensions, imageTooLarge, insufficientMemory, memoryPressure, invalidImage
}

public enum MemoryPressure: Sendable { case normal, warning, critical }

/// Admission estimates, not a hard OS/GPU quota. No unmeasured model is admitted here.
public struct ResourcePolicy: Sendable {
    public static let mib: UInt64 = 1_048_576
    public let physicalBytes: UInt64
    public var appBudget: UInt64 { min(2_048 * Self.mib, physicalBytes / 4) }
    public var cacheBudget: UInt64 { min(128 * Self.mib, appBudget / 8) }
    public let previewEdge = 2_048

    public init(physicalBytes: UInt64 = ProcessInfo.processInfo.physicalMemory) {
        self.physicalBytes = physicalBytes
    }

    public func pixelCount(width: Int, height: Int) throws -> UInt64 {
        guard width > 0, height > 0 else { throw ResourceFailure.invalidDimensions }
        let (pixels, overflow) = UInt64(width).multipliedReportingOverflow(by: UInt64(height))
        guard !overflow, pixels <= 40_000_000, width <= 40_000, height <= 40_000 else {
            throw ResourceFailure.imageTooLarge
        }
        return pixels
    }

    public func previewReservation(width: Int, height: Int) throws -> UInt64 {
        let pixels = try pixelCount(width: width, height: height)
        // Allow decoders that transiently hold full-sized input/output, plus thumbnail
        // and UI surfaces. Metadata inspection happens before this reservation.
        return pixels * 8 + UInt64(previewEdge * previewEdge) * 12 + 64 * Self.mib
    }

    public func admit(bytes: UInt64, residentBytes: UInt64, availableBytes: UInt64?,
                      pressure: MemoryPressure) throws {
        guard pressure == .normal else { throw ResourceFailure.memoryPressure }
        let (total, overflow) = bytes.addingReportingOverflow(residentBytes)
        guard !overflow, total <= appBudget else { throw ResourceFailure.insufficientMemory }
        // A failed memory query is not permission to allocate blindly.
        guard let availableBytes, availableBytes >= 2_048 * Self.mib,
              bytes <= availableBytes - 2_048 * Self.mib else {
            throw ResourceFailure.insufficientMemory
        }
    }
}

public enum SystemMemory {
    /// Reclaimable snapshot; inactive pages are not a guarantee of allocation success.
    /// os_proc_available_memory is explicitly unavailable on macOS (SDK os/proc.h).
    public static func availableBytes() -> UInt64? {
        var stats = vm_statistics64()
        let host = mach_host_self()
        defer { mach_port_deallocate(mach_task_self_, host) }
        var count = mach_msg_type_number_t(MemoryLayout<vm_statistics64>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &stats) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(host, HOST_VM_INFO64, $0, &count)
            }
        }
        var pageSize: vm_size_t = 0
        guard result == KERN_SUCCESS, host_page_size(host, &pageSize) == KERN_SUCCESS else { return nil }
        return (UInt64(stats.free_count) + UInt64(stats.inactive_count)) * UInt64(pageSize)
    }

    public static func physicalFootprintBytes() -> UInt64? {
        var info = task_vm_info()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(22), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? UInt64(info.phys_footprint) : nil
    }

    public static func residentBytes() -> UInt64? {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? UInt64(info.resident_size) : nil
    }
}
