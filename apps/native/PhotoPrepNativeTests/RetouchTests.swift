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

    func testCMYKIsRejected() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("cmyk.jpg")
        let context = try XCTUnwrap(CGContext(data: nil, width: 8, height: 8, bitsPerComponent: 8,
                                             bytesPerRow: 0, space: CGColorSpaceCreateDeviceCMYK(),
                                             bitmapInfo: CGImageAlphaInfo.none.rawValue))
        let image = try XCTUnwrap(context.makeImage())
        let writer = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(writer, image, nil)
        XCTAssertTrue(CGImageDestinationFinalize(writer))
        let decoder = StraightImageDecoder(
            policy: ResourcePolicy(physicalBytes: 16 * 1024 * ResourcePolicy.mib),
            memorySnapshot: { (100 * ResourcePolicy.mib, 8_192 * ResourcePolicy.mib) }
        )
        do {
            _ = try await decoder.decode(url: url)
            XCTFail("CMYK must be rejected")
        } catch let failure as RetouchFailure {
            XCTAssertEqual(failure, .unsupportedColorSpace)
        }
    }

    func testCancellationStopsHeavyStages() throws {
        let width = 32
        let height = 24
        var sourcePixels = [UInt8](repeating: 100, count: width * height * 4)
        for index in 0..<(width * height) { sourcePixels[index * 4 + 3] = 255 }
        let source = StraightImage(width: width, height: height, pixels: sourcePixels)
        var coverage = [UInt8](repeating: 0, count: width * height)
        for y in 8..<16 { for x in 8..<24 { coverage[y * width + x] = 255 } }
        let flag = CancellationFlag()
        flag.cancel()
        XCTAssertNil(RetouchPreprocessor.contextRect(mask: coverage, width: width, height: height,
                                                     isCancelled: { flag.isCancelled }))
        XCTAssertThrowsError(try RetouchPreprocessor.prepare(source: source, mask: coverage, isCancelled: { flag.isCancelled })) {
            XCTAssertEqual($0 as? RetouchFailure, .cancelled)
        }
        let rect = RetouchPreprocessor.contextRect(mask: coverage, width: width, height: height)!
        XCTAssertThrowsError(try RetouchPreprocessor.composite(source: source, coverage: coverage,
                                                               predicted: [Float](repeating: 0, count: 3 * 512 * 512),
                                                               rect: rect, isCancelled: { flag.isCancelled })) {
            XCTAssertEqual($0 as? RetouchFailure, .cancelled)
        }
        XCTAssertTrue(MaskRenderer.render(width: width, height: height,
                                          strokes: [MaskStroke(points: [MaskPoint(x: 0.5, y: 0.5)], width: 0.2)],
                                          isCancelled: { flag.isCancelled }).isEmpty)
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

    private func gradientSource(width: Int, height: Int) -> StraightImage {
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        for y in 0..<height {
            for x in 0..<width {
                let i = (y * width + x) * 4
                pixels[i] = UInt8((x * 255) / max(1, width - 1))
                pixels[i + 1] = UInt8((y * 255) / max(1, height - 1))
                pixels[i + 2] = UInt8(((x + y) * 255) / max(1, width + height - 2))
                pixels[i + 3] = 255
            }
        }
        return StraightImage(width: width, height: height, pixels: pixels)
    }

    private func edgeMask(width: Int, height: Int) -> [UInt8] {
        var mask = [UInt8](repeating: 0, count: width * height)
        for y in 0..<height {
            for x in 0..<width where x < 4 || y < 4 || x >= width - 4 || y >= height - 4 {
                mask[y * width + x] = 255
            }
        }
        return mask
    }

    func testUpscaleRoundsRGBTo8Bit() throws {
        let source = gradientSource(width: 16, height: 12)
        let mask = edgeMask(width: 16, height: 12)
        let prepared = try RetouchPreprocessor.prepare(source: source, mask: mask)
        for value in prepared.image {
            let byte = Double(value) * 255.0
            XCTAssertEqual(byte, byte.rounded(), accuracy: 0.0001)
        }
        XCTAssertTrue(prepared.image.allSatisfy { $0.isFinite && $0 >= 0 && $0 <= 1 })
    }

    func testMixedScaleKeepsEdgesAndOutside() throws {
        let source = gradientSource(width: 900, height: 300)
        let mask = edgeMask(width: 900, height: 300)
        let prepared = try RetouchPreprocessor.prepare(source: source, mask: mask)
        XCTAssertTrue(prepared.image.allSatisfy { $0.isFinite })
        XCTAssertTrue(prepared.mask.allSatisfy { $0 == 0 || $0 == 1 })
        let result = try RetouchPreprocessor.composite(source: source, coverage: mask,
                                                       predicted: [Float](repeating: 100, count: 3 * 512 * 512),
                                                       rect: prepared.rect)
        for i in 0..<(900 * 300) where mask[i] == 0 {
            let offset = i * 4
            XCTAssertEqual(Array(result.pixels[offset..<(offset + 4)]), Array(source.pixels[offset..<(offset + 4)]))
        }
        for i in 0..<(900 * 300) {
            XCTAssertEqual(result.pixels[i * 4 + 3], source.pixels[i * 4 + 3])
        }
    }

    func testDownscaleBoundaries() throws {
        let source = gradientSource(width: 1200, height: 800)
        let mask = edgeMask(width: 1200, height: 800)
        let prepared = try RetouchPreprocessor.prepare(source: source, mask: mask)
        XCTAssertTrue(prepared.image.allSatisfy { $0.isFinite })
        XCTAssertTrue(prepared.mask.allSatisfy { $0 == 0 || $0 == 1 })
        XCTAssertEqual(prepared.rect.width, 1200)
        XCTAssertEqual(prepared.rect.height, 800)
    }
}
