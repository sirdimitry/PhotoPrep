import XCTest
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
@testable import PhotoPrepCore

final class OutputEditingTests: XCTestCase {
    private func image(_ w: Int, _ h: Int, alpha: UInt8 = 255) -> StraightImage {
        var p = [UInt8](repeating: 0, count: w * h * 4)
        for y in 0..<h { for x in 0..<w {
            let i = (y * w + x) * 4
            p[i] = UInt8(x * 255 / max(1, w - 1)); p[i+1] = UInt8(y * 255 / max(1, h - 1))
            p[i+2] = 90; p[i+3] = alpha
        }}
        return StraightImage(width: w, height: h, pixels: p)
    }

    func testCropHasExactSizeAndPreservesAlpha() throws {
        let source = image(120, 80, alpha: 200)
        let rect = SessionCrop(x: 0.2, y: 0.1, width: 0.5, height: 0.5)
        let out = try OutputEditing.crop(source, to: rect, width: 40, height: 30)
        XCTAssertEqual(out.width, 40); XCTAssertEqual(out.height, 30)
        XCTAssertTrue(out.pixels.enumerated().allSatisfy { $0.offset % 4 == 3 ? $0.element == 200 : true })
    }

    func testLogoOverlayChangesPixelsAndKeepsSize() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: dir) }
        let logoURL = dir.appendingPathComponent("logo.png")
        let logo = image(8, 8, alpha: 255)
        guard let cg = logo.cgImage(), let dest = CGImageDestinationCreateWithURL(logoURL as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            return XCTFail("logo encode")
        }
        CGImageDestinationAddImage(dest, cg, nil); XCTAssertTrue(CGImageDestinationFinalize(dest))
        let asset = try OutputEditing.loadLogo(logoURL.path, mode: "logo")
        let base = StraightImage(width: 40, height: 30, pixels: [UInt8](repeating: 10, count: 40 * 30 * 4))
        let placement = SessionLogo(path: logoURL.path, width: 0.3, opacity: 0.5, x: 0, y: 0, enabled: true, mode: "logo")
        let out = try OutputEditing.applyLogo(base, logo: placement, asset: asset, width: 40, height: 30)
        XCTAssertEqual(out.width, 40); XCTAssertEqual(out.height, 30)
        XCTAssertNotEqual(out.pixels, base.pixels)
    }

    func testLogoSourceOverOnTransparentBase() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: dir) }
        let logoURL = dir.appendingPathComponent("logo.png")
        let logo = image(2, 2, alpha: 255)
        guard let cg = logo.cgImage(), let dest = CGImageDestinationCreateWithURL(logoURL as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            return XCTFail("logo encode")
        }
        CGImageDestinationAddImage(dest, cg, nil); XCTAssertTrue(CGImageDestinationFinalize(dest))
        let asset = try OutputEditing.loadLogo(logoURL.path, mode: "logo")
        let base = StraightImage(width: 20, height: 20, pixels: [UInt8](repeating: 0, count: 20 * 20 * 4))
        let placement = SessionLogo(path: logoURL.path, width: 0.9, opacity: 0.5, x: 0, y: 0, enabled: true, mode: "logo")
        let out = try OutputEditing.applyLogo(base, logo: placement, asset: asset, width: 20, height: 20)
        let center = (10 * 20 + 10) * 4
        XCTAssertEqual(out.pixels[center + 3], 128, accuracy: 2)
        XCTAssertGreaterThan(out.pixels[center], 200)
    }

    func testExportEncodingAndExclusiveWrite() throws {
        let source = image(16, 8, alpha: 128)
        let png = try ExportWriter.encode(source, format: .png)
        XCTAssertGreaterThan(png.count, 8)
        let jpg = try ExportWriter.encode(source, format: .jpeg)
        XCTAssertGreaterThan(jpg.count, 8)
        XCTAssertFalse(String(data: png, encoding: .isoLatin1)?.contains("Exif") ?? false)
        XCTAssertFalse(String(data: png, encoding: .isoLatin1)?.contains("eXIf") ?? false)
        let jbytes = [UInt8](jpg)
        XCTAssertFalse((0..<(max(0,jbytes.count-1))).contains { jbytes[$0] == 0xFF && jbytes[$0+1] == 0xE1 })
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: dir) }
        let target = dir.appendingPathComponent("out.png")
        XCTAssertTrue(try ExportWriter.writeExclusive(png, to: target))
        XCTAssertFalse(try ExportWriter.writeExclusive(png, to: target))
    }
    func testCropKeepsTopLeftOrientation() throws {
        var p = [UInt8](repeating: 0, count: 8 * 8 * 4)
        for y in 0..<8 { for x in 0..<8 {
            let i=(y*8+x)*4
            if y < 4 { p[i]=220; p[i+1]=20; p[i+2]=20 } else { p[i]=20; p[i+1]=20; p[i+2]=220 }
            p[i+3]=255
        }}
        let src = StraightImage(width:8,height:8,pixels:p)
        let out = try OutputEditing.crop(src, to: SessionCrop(x:0,y:0,width:1,height:0.5), width:8,height:4)
        XCTAssertGreaterThan(out.pixels[0], 180)
        XCTAssertGreaterThan(out.pixels[(3*8+3)*4], 180)
        XCTAssertLessThan(out.pixels[(3*8+3)*4+2], 60)
    }

}
