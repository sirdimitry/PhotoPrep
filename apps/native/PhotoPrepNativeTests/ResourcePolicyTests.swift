import XCTest
@testable import PhotoPrepCore

final class ResourcePolicyTests: XCTestCase {
    private let policy = ResourcePolicy(physicalBytes: 16_384 * ResourcePolicy.mib)

    func testBudgetLeavesMostPhysicalMemoryToSystem() {
        XCTAssertEqual(policy.appBudget, 2_048 * ResourcePolicy.mib)
        XCTAssertEqual(policy.cacheBudget, 128 * ResourcePolicy.mib)
        XCTAssertEqual(ResourcePolicy(physicalBytes: 4_096 * ResourcePolicy.mib).appBudget, 1_024 * ResourcePolicy.mib)
    }

    func testHugeAndInvalidDimensionsRejectedBeforeMultiplication() {
        for size in [(0, 1), (-1, 100), (Int.max, Int.max), (40_000_001, 1), (8_000, 6_000)] {
            XCTAssertThrowsError(try policy.previewReservation(width: size.0, height: size.1))
        }
        XCTAssertNoThrow(try policy.previewReservation(width: 8_000, height: 5_000))
    }

    func testBudgetIncludesAlreadyResidentMemory() {
        XCTAssertThrowsError(try policy.admit(bytes: 512 * ResourcePolicy.mib,
                                              residentBytes: 1_800 * ResourcePolicy.mib,
                                              availableBytes: 8_192 * ResourcePolicy.mib, pressure: .normal))
        XCTAssertThrowsError(try policy.admit(bytes: UInt64.max, residentBytes: 1,
                                              availableBytes: UInt64.max, pressure: .normal))
    }

    func testLowOrUnknownMemoryAndPressureDenyWork() {
        for available: UInt64? in [nil, 0, 2_048 * ResourcePolicy.mib] {
            XCTAssertThrowsError(try policy.admit(bytes: 1, residentBytes: 0,
                                                  availableBytes: available, pressure: .normal))
        }
        for pressure: MemoryPressure in [.warning, .critical] {
            XCTAssertThrowsError(try policy.admit(bytes: 1, residentBytes: 0,
                                                  availableBytes: 8_192 * ResourcePolicy.mib, pressure: pressure)) {
                XCTAssertEqual($0 as? ResourceFailure, .memoryPressure)
            }
        }
    }

    func testConservativeFortyMegapixelAdmission() throws {
        let bytes = try policy.previewReservation(width: 8_000, height: 5_000)
        XCTAssertGreaterThan(bytes, 320_000_000)
        XCTAssertNoThrow(try policy.admit(bytes: bytes, residentBytes: 128 * ResourcePolicy.mib,
                                         availableBytes: 4_096 * ResourcePolicy.mib, pressure: .normal))
    }
}
