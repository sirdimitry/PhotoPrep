import XCTest
import Foundation
import ImageIO
import UniformTypeIdentifiers
import CoreGraphics
@testable import PhotoPrepCore

final class RetouchTests: XCTestCase {
    private let hiddenPNG = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGklEQVR4nGPkEpFjkJOTa2CxsbH5LycnxwQAGCMDK8impKAAAAAASUVORK5CYII=")!

    func testDecoderPreservesHiddenRGBAndAlpha() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("hidden.png")
        try hiddenPNG.write(to: url)
        let decoder = StraightImageDecoder(
            policy: ResourcePolicy(physicalBytes: 16 * 1024 * ResourcePolicy.mib),
            memorySnapshot: { (100 * ResourcePolicy.mib, 8_192 * ResourcePolicy.mib) }
        )
        let image = try await decoder.decode(url: url)
        XCTAssertEqual(image.width, 2)
        XCTAssertEqual(image.height, 2)
        XCTAssertEqual(Array(image.pixels[0..<4]), [10, 20, 30, 0])
        XCTAssertEqual(Array(image.pixels[4..<8]), [40, 50, 60, 128])
        XCTAssertEqual(Array(image.pixels[8..<12]), [70, 80, 90, 255])
        XCTAssertEqual(Array(image.pixels[12..<16]), [100, 110, 120, 1])
    }

    func testMaskStartsTopLeftAndEraserClears() {
        var mask = MaskRenderer.render(
            width: 100,
            height: 100,
            strokes: [MaskStroke(points: [MaskPoint(x: 0, y: 0)], width: 0.1)]
        )
        XCTAssertGreaterThan(mask[0], 0, "top-left point must be in row 0")
        mask = MaskRenderer.render(
            width: 100,
            height: 100,
            strokes: [
                MaskStroke(points: [MaskPoint(x: 0.5, y: 0.5)], width: 0.2),
                MaskStroke(points: [MaskPoint(x: 0.5, y: 0.5)], width: 0.2, erase: true),
            ]
        )
        XCTAssertEqual(mask[50 * 100 + 50], 0)
    }

    func testContextRectContainsMaskAndClampsAtEdge() {
        var mask = [UInt8](repeating: 0, count: 100 * 80)
        mask[(10 * 100) + 20] = 255
        let rect = RetouchPreprocessor.contextRect(mask: mask, width: 100, height: 80)
        XCTAssertNotNil(rect)
        XCTAssertEqual(rect!.width, 100)
        XCTAssertEqual(rect!.x, 0)
        XCTAssertEqual(rect!.y, 0)
        XCTAssertEqual(rect!.height, 80)
        XCTAssertLessThanOrEqual(rect!.x + rect!.width, 100)
        XCTAssertLessThanOrEqual(rect!.y + rect!.height, 80)
    }

    func testCompositePreservesOutsidePixelsAndAlpha() throws {
        let width = 32
        let height = 24
        var sourcePixels = [UInt8](repeating: 0, count: width * height * 4)
        for index in 0..<(width * height) {
            sourcePixels[index * 4] = 100
            sourcePixels[index * 4 + 1] = 50
            sourcePixels[index * 4 + 2] = 25
            sourcePixels[index * 4 + 3] = UInt8(index % 256)
        }
        let source = StraightImage(width: width, height: height, pixels: sourcePixels)
        var coverage = [UInt8](repeating: 0, count: width * height)
        for y in 8..<16 {
            for x in 8..<24 { coverage[y * width + x] = 255 }
        }
        let rect = RetouchPreprocessor.contextRect(mask: coverage, width: width, height: height)!
        let predicted = [Float](repeating: 200, count: 3 * 512 * 512)
        let result = try RetouchPreprocessor.composite(source: source, coverage: coverage, predicted: predicted, rect: rect)
        for index in 0..<(width * height) {
            if coverage[index] == 0 {
                XCTAssertEqual(Array(result.pixels[index * 4..<(index * 4 + 4)]), Array(sourcePixels[index * 4..<(index * 4 + 4)]))
            }
            XCTAssertEqual(result.pixels[index * 4 + 3], sourcePixels[index * 4 + 3])
        }
    }

    func testOrientationSixFullDecode() async throws {
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
        let decoder = StraightImageDecoder(
            policy: ResourcePolicy(physicalBytes: 16 * 1024 * ResourcePolicy.mib),
            memorySnapshot: { (100 * ResourcePolicy.mib, 8_192 * ResourcePolicy.mib) }
        )
        let decoded = try await decoder.decode(url: url)
        XCTAssertEqual(decoded.width, 1_000)
        XCTAssertEqual(decoded.height, 3_000)
        XCTAssertEqual(decoded.pixels.count, 1_000 * 3_000 * 4)
        XCTAssertTrue(decoded.pixels.enumerated().allSatisfy { $0.offset % 4 != 3 || $0.element == 255 })
    }

    func testSourceIdentityChangesWhenBytesChange() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("source.bin")
        try Data([1, 2, 3]).write(to: url)
        let first = try SourceIdentity.capture(url)
        try Data([1, 2, 4]).write(to: url)
        let second = try SourceIdentity.capture(url)
        XCTAssertNotEqual(first.sha256, second.sha256)
    }
}
