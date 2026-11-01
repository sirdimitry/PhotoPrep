import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import Darwin

public enum OutputEditingError: Error, Equatable, Sendable {
    case invalidCrop, invalidLogo, allocation, encode, cancelled, logoTooLarge
}

public enum OutputEditing {
    public static func crop(_ source: StraightImage, to crop: SessionCrop,
                            width: Int, height: Int,
                            isCancelled: () -> Bool = { false }) throws -> StraightImage {
        guard width > 0, height > 0,
              crop.x >= 0, crop.y >= 0, crop.width > 0, crop.height > 0,
              crop.x + crop.width <= 1.000001, crop.y + crop.height <= 1.000001 else {
            throw OutputEditingError.invalidCrop
        }
        let sx = crop.x * Double(source.width)
        let sy = crop.y * Double(source.height)
        let sw = crop.width * Double(source.width)
        let sh = crop.height * Double(source.height)
        var out = [UInt8](repeating: 0, count: width * height * 4)
        for y in 0..<height {
            if isCancelled() { throw OutputEditingError.cancelled }
            let fy = sy + (Double(y) + 0.5) * sh / Double(height) - 0.5
            for x in 0..<width {
                let fx = sx + (Double(x) + 0.5) * sw / Double(width) - 0.5
                for c in 0..<4 {
                    out[(y * width + x) * 4 + c] = UInt8(clamping: Int(sample(source, fx, fy, c).rounded(.toNearestOrEven)))
                }
            }
        }
        return StraightImage(width: width, height: height, pixels: out)
    }

    private static func sample(_ image: StraightImage, _ x: Double, _ y: Double, _ channel: Int) -> Double {
        let x0 = Int(floor(x)), y0 = Int(floor(y))
        let fx = x - Double(x0), fy = y - Double(y0)
        let xa = min(max(0, x0), image.width - 1), xb = min(max(0, x0 + 1), image.width - 1)
        let ya = min(max(0, y0), image.height - 1), yb = min(max(0, y0 + 1), image.height - 1)
        func p(_ xx: Int, _ yy: Int) -> Double { Double(image.pixels[(yy * image.width + xx) * 4 + channel]) }
        let top = p(xa, ya) * (1 - fx) + p(xb, ya) * fx
        let bottom = p(xa, yb) * (1 - fx) + p(xb, yb) * fx
        return top * (1 - fy) + bottom * fy
    }

    public static func loadLogo(_ path: String, mode: String) throws -> CGImage {
        let url = URL(fileURLWithPath: path)
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let size = (attrs[.size] as? NSNumber)?.intValue, size > 0, size <= 32 * 1024 * 1024,
              let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              CGImageSourceGetType(source) as String? == UTType.png.identifier,
              CGImageSourceGetCount(source) == 1,
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let w = props[kCGImagePropertyPixelWidth] as? Int,
              let h = props[kCGImagePropertyPixelHeight] as? Int,
              w > 0, h > 0, w <= 32_000_000 / max(1, h),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            throw OutputEditingError.invalidLogo
        }
        // Overlay/template keeps its full transparent canvas. Do not trim:
        // internal composition and padding are part of the asset.
        return image
    }

    private static func trimAlpha(_ image: CGImage) throws -> CGImage {
        let width = image.width, height = image.height
        guard width > 0, height > 0 else { throw OutputEditingError.invalidLogo }
        var data = [UInt8](repeating: 0, count: width * height * 4)
        guard let ctx = CGContext(data: &data, width: width, height: height, bitsPerComponent: 8,
                                  bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw OutputEditingError.allocation
        }
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        var minX = width, minY = height, maxX = -1, maxY = -1
        for y in 0..<height { for x in 0..<width where data[(y * width + x) * 4 + 3] != 0 {
            minX = min(minX, x); minY = min(minY, y); maxX = max(maxX, x); maxY = max(maxY, y)
        }}
        guard maxX >= minX, maxY >= minY else { throw OutputEditingError.invalidLogo }
        return image.cropping(to: CGRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1)) ?? image
    }

    public static func applyLogo(_ source: StraightImage, logo: SessionLogo, asset: CGImage,
                                 width: Int, height: Int,
                                 isCancelled: () -> Bool = { false }) throws -> StraightImage {
        guard width > 0, height > 0 else { throw OutputEditingError.allocation }
        let areaInset = logo.mode == "template" ? 0.0 : 0.03
        let area = CGRect(x: Double(width) * areaInset, y: Double(height) * areaInset,
                          width: Double(width) * (1 - 2 * areaInset),
                          height: Double(height) * (1 - 2 * areaInset))
        let aspect = Double(asset.height) / Double(max(1, asset.width))
        let lw = min(Double(width) * logo.width, area.width, area.height / aspect)
        let lh = lw * aspect
        let lx = area.minX + (area.width - lw) * logo.x
        let ly = area.minY + (area.height - lh) * logo.y
        var logoPixels = [UInt8](repeating: 0, count: asset.width * asset.height * 4)
        guard let ctx = CGContext(data: &logoPixels, width: asset.width, height: asset.height,
                                  bitsPerComponent: 8, bytesPerRow: asset.width * 4,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw OutputEditingError.allocation
        }
        ctx.draw(asset, in: CGRect(x: 0, y: 0, width: asset.width, height: asset.height))
        var out = source.pixels
        for y in 0..<Int(lh) {
            if isCancelled() { throw OutputEditingError.cancelled }
            for x in 0..<Int(lw) {
                let ox = Int(lx) + x, oy = Int(ly) + y
                guard ox >= 0, oy >= 0, ox < width, oy < height else { continue }
                let u = Int((Double(x) + 0.5) * Double(asset.width) / lw)
                let v = Int((Double(y) + 0.5) * Double(asset.height) / lh)
                let si = (min(asset.height - 1, v) * asset.width + min(asset.width - 1, u)) * 4
                let la = Double(logoPixels[si + 3]) / 255.0
                let sa = la * logo.opacity
                guard sa > 0 else { continue }
                let di = (oy * width + ox) * 4
                let da = Double(out[di + 3]) / 255.0
                let oa = sa + da * (1 - sa)
                guard oa > 0 else { continue }
                let lr = la > 0 ? Double(logoPixels[si]) / 255.0 / la : 0
                let lg = la > 0 ? Double(logoPixels[si + 1]) / 255.0 / la : 0
                let lb = la > 0 ? Double(logoPixels[si + 2]) / 255.0 / la : 0
                out[di] = UInt8(clamping: Int(((lr * sa + Double(out[di]) / 255.0 * da * (1 - sa)) / oa * 255).rounded()))
                out[di + 1] = UInt8(clamping: Int(((lg * sa + Double(out[di + 1]) / 255.0 * da * (1 - sa)) / oa * 255).rounded()))
                out[di + 2] = UInt8(clamping: Int(((lb * sa + Double(out[di + 2]) / 255.0 * da * (1 - sa)) / oa * 255).rounded()))
                out[di + 3] = UInt8(clamping: Int((oa * 255).rounded()))
            }
        }
        return StraightImage(width: width, height: height, pixels: out)
    }
}

public enum ExportFormat: String, Sendable { case png = "PNG", jpeg = "JPEG" }

public enum ExportWriter {
    public static func encode(_ image: StraightImage, format: ExportFormat, quality: Double = 0.92) throws -> Data {
        var source = image
        if format == .jpeg {
            var flattened = image.pixels
            for i in stride(from: 3, to: flattened.count, by: 4) {
                let a = Double(flattened[i]) / 255
                for c in 0..<3 {
                    flattened[i - 3 + c] = UInt8(clamping: Int((Double(flattened[i - 3 + c]) * a + 255 * (1 - a)).rounded()))
                }
                flattened[i] = 255
            }
            source = StraightImage(width: image.width, height: image.height, pixels: flattened)
        }
        guard let cg = source.cgImage() else { throw OutputEditingError.encode }
        let data = NSMutableData()
        let type = format == .png ? UTType.png.identifier : UTType.jpeg.identifier
        guard let dest = CGImageDestinationCreateWithData(data, type as CFString, 1, nil) else {
            throw OutputEditingError.encode
        }
        let properties: [CFString: Any] = format == .jpeg
            ? [kCGImageDestinationLossyCompressionQuality: max(0, min(1, quality))]
            : [:]
        CGImageDestinationAddImage(dest, cg, properties as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { throw OutputEditingError.encode }
        return stripMetadata(data as Data, format: format)
    }

    /// Write to a temp file in the target folder, fsync it, then publish with a
    /// hard-link/no-replace step. A collision is a distinct, non-fatal result.
    public static func publish(_ data: Data, to url: URL) throws -> Bool {
        let folder = url.deletingLastPathComponent()
        let temp = folder.appendingPathComponent(".photoprep-\(UUID().uuidString).tmp")
        let fd = open(temp.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw OutputEditingError.encode }
        var tempExists = true
        defer { if tempExists { try? FileManager.default.removeItem(at: temp) } }
        do {
            var offset = 0
            while offset < data.count {
                let written = data.withUnsafeBytes { ptr in
                    Darwin.write(fd, ptr.baseAddress!.advanced(by: offset), data.count - offset)
                }
                guard written > 0 else { throw OutputEditingError.encode }
                offset += written
            }
            guard fsync(fd) == 0 else { throw OutputEditingError.encode }
        } catch {
            close(fd)
            throw error
        }
        close(fd)
        // link(2) is atomic and refuses to replace an existing path or symlink.
        if Darwin.link(temp.path, url.path) == 0 {
            try? FileManager.default.removeItem(at: temp)
            tempExists = false
            return true
        }
        if errno == EEXIST { return false }
        throw OutputEditingError.encode
    }

    public static func writeExclusive(_ data: Data, to url: URL) throws -> Bool {
        try publish(data, to: url)
    }
    /// ImageIO adds a minimal EXIF/Photoshop container. Python exports clean
    /// pixel data, so remove metadata segments before publication.
    public static func stripMetadata(_ data: Data, format: ExportFormat) -> Data {
        switch format {
        case .png: return stripPNGMetadata(data)
        case .jpeg: return stripJPEGMetadata(data)
        }
    }

    private static func stripPNGMetadata(_ data: Data) -> Data {
        let bytes = [UInt8](data)
        guard bytes.count > 8, Array(bytes.prefix(8)) == [137,80,78,71,13,10,26,10] else { return data }
        var out = Array(bytes.prefix(8)); var i = 8
        let drop: Set<String> = ["eXIf", "iTXt", "tEXt", "zTXt", "tIME"]
        while i + 12 <= bytes.count {
            let length = Int(bytes[i]) << 24 | Int(bytes[i+1]) << 16 | Int(bytes[i+2]) << 8 | Int(bytes[i+3])
            guard length >= 0, i + 12 + length <= bytes.count else { return data }
            let type = String(bytes: bytes[(i+4)..<(i+8)], encoding: .ascii) ?? ""
            let end = i + 12 + length
            if !drop.contains(type) { out.append(contentsOf: bytes[i..<end]) }
            i = end
            if type == "IEND" { break }
        }
        return Data(out)
    }

    private static func stripJPEGMetadata(_ data: Data) -> Data {
        let bytes = [UInt8](data)
        guard bytes.count > 4, bytes[0] == 0xFF, bytes[1] == 0xD8 else { return data }
        var out = [UInt8]([0xFF,0xD8]); var i = 2
        while i + 3 < bytes.count {
            guard bytes[i] == 0xFF else { return data }
            let marker = bytes[i+1]
            if marker == 0xDA { // SOS: copy entropy-coded data verbatim
                out.append(contentsOf: bytes[i..<bytes.count]); return Data(out)
            }
            if marker == 0xD9 { out.append(contentsOf: bytes[i..<bytes.count]); return Data(out) }
            if marker == 0x00 || marker == 0x01 || (marker >= 0xD0 && marker <= 0xD7) {
                out.append(contentsOf: [0xFF, marker]); i += 2; continue
            }
            let length = Int(bytes[i+2]) << 8 | Int(bytes[i+3])
            guard length >= 2, i + 2 + length <= bytes.count else { return data }
            let end = i + 2 + length
            // APP1 (EXIF/XMP), APP13 (Photoshop/IPTC), COM comments: drop.
            if marker != 0xE1 && marker != 0xED && marker != 0xFE {
                out.append(contentsOf: bytes[i..<end])
            }
            i = end
        }
        return Data(out)
    }
}
