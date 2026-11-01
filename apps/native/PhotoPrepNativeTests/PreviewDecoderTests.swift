import XCTest
import ImageIO
import UniformTypeIdentifiers
@testable import PhotoPrepCore

final class PreviewDecoderTests: XCTestCase, @unchecked Sendable {
    private func withImage(_ operation: (URL) async throws -> Void) async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("oriented.jpg")
        let context = try XCTUnwrap(CGContext(data: nil, width: 3_000, height: 1_000, bitsPerComponent: 8,
                                             bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                             bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        let image = try XCTUnwrap(context.makeImage())
        let writer = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(writer, image, [kCGImagePropertyOrientation: 6] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(writer))
        try await operation(url)
    }

    func testPreviewAppliesOrientationAndBoundsAndPreservesSource() async throws {
        try await withImage { url in
            let original = try Data(contentsOf: url)
            let decoder = PreviewDecoder(memorySnapshot: { (100 * ResourcePolicy.mib, 8_192 * ResourcePolicy.mib) })
            let header = try await decoder.header(url: url)
            XCTAssertEqual(header.width, 1_000)
            XCTAssertEqual(header.height, 3_000)
            let preview = try await decoder.preview(url: url)
            XCTAssertEqual(preview.image.height, 2_048)
            XCTAssertLessThan(preview.image.width, preview.image.height)
            XCTAssertEqual(try Data(contentsOf: url), original)
        }
    }

    func testLowMemoryDeclinesDecodeWhileMetadataRemainsReadable() async throws {
        try await withImage { url in
            let decoder = PreviewDecoder(memorySnapshot: { (100 * ResourcePolicy.mib, nil) })
            _ = try await decoder.header(url: url)
            do {
                _ = try await decoder.preview(url: url)
                XCTFail("Must not decode when memory query fails")
            } catch { XCTAssertEqual(error as? ResourceFailure, .insufficientMemory) }
        }
    }

    func testRemoteAndCorruptFilesAreRejected() async {
        let decoder = PreviewDecoder()
        do {
            _ = try await decoder.header(url: URL(string: "https://example.com/photo.jpg")!)
            XCTFail("Network URL must not be opened")
        } catch { XCTAssertEqual(error as? ResourceFailure, .invalidImage) }
        do {
            _ = try await decoder.header(url: URL(fileURLWithPath: "/dev/null"))
            XCTFail("Corrupt image must be rejected")
        } catch { XCTAssertEqual(error as? ResourceFailure, .invalidImage) }
    }
}
