import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import Darwin

public enum OutputEditingError: Error, Equatable, Sendable {
    case invalidCrop, invalidLogo, allocation, encode
}

public enum OutputEditing {
    public static func crop(_ source: StraightImage, to crop: SessionCrop,
                            width: Int, height: Int) throws -> StraightImage {
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
        guard FileManager.default.fileExists(atPath: path),
              let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              CGImageSourceGetType(source) as String? == UTType.png.identifier,
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            throw OutputEditingError.invalidLogo
        }
        if mode == "template" {
            return try trimAlpha(image)
        }
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
                                 width: Int, height: Int) throws -> StraightImage {
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
            for x in 0..<Int(lw) {
                let ox = Int(lx) + x, oy = Int(ly) + y
                guard ox >= 0, oy >= 0, ox < width, oy < height else { continue }
                let u = Int((Double(x) + 0.5) * Double(asset.width) / lw)
                let v = Int((Double(y) + 0.5) * Double(asset.height) / lh)
                let si = (min(asset.height - 1, v) * asset.width + min(asset.width - 1, u)) * 4
                let alpha = Double(logoPixels[si + 3]) / 255.0 * logo.opacity
                guard alpha > 0 else { continue }
                let di = (oy * width + ox) * 4
                let sa = Double(logoPixels[si + 3]) / 255.0
                let lr = sa > 0 ? Double(logoPixels[si]) / sa : 0
                let lg = sa > 0 ? Double(logoPixels[si + 1]) / sa : 0
                let lb = sa > 0 ? Double(logoPixels[si + 2]) / sa : 0
                out[di] = UInt8(clamping: Int((lr * alpha + Double(out[di]) * (1 - alpha)).rounded()))
                out[di + 1] = UInt8(clamping: Int((lg * alpha + Double(out[di + 1]) * (1 - alpha)).rounded()))
                out[di + 2] = UInt8(clamping: Int((lb * alpha + Double(out[di + 2]) * (1 - alpha)).rounded()))
                out[di + 3] = UInt8(clamping: Int((alpha * 255 + Double(out[di + 3]) * (1 - alpha)).rounded()))
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
        return data as Data
    }

    /// Create a new file without replacing anything (including symlinks).
    public static func writeExclusive(_ data: Data, to url: URL) throws -> Bool {
        let fd = open(url.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        guard fd >= 0 else {
            if errno == EEXIST { return false }
            throw OutputEditingError.encode
        }
        defer { close(fd) }
        var offset = 0
        while offset < data.count {
            let written = data.withUnsafeBytes { ptr in
                Darwin.write(fd, ptr.baseAddress!.advanced(by: offset), data.count - offset)
            }
            guard written > 0 else { throw OutputEditingError.encode }
            offset += written
        }
        guard fsync(fd) == 0 else { throw OutputEditingError.encode }
        return true
    }
}
