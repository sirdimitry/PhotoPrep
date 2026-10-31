import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import CryptoKit

public enum RetouchFailure: Error, Equatable, Sendable {
    case invalidImage
    case unsupportedPixelLayout
    case premultipliedAlpha
    case imageTooLarge
    case insufficientMemory
    case emptyMask
    case invalidMask
    case nonFiniteOutput
    case invalidOutputShape
    case sourceChanged
    case modelMissing
    case workerFailed(String)
    case timeout
    case cancelled
}

public struct SourceIdentity: Codable, Sendable, Equatable {
    public let size: Int64
    public let mtimeNS: Int64
    public let sha256: String

    public init(size: Int64, mtimeNS: Int64, sha256: String) {
        self.size = size
        self.mtimeNS = mtimeNS
        self.sha256 = sha256
    }

    public static func capture(_ url: URL) throws -> SourceIdentity {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let size = (attributes[.size] as? NSNumber)?.int64Value ?? 0
        let modified = (attributes[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        return SourceIdentity(size: size, mtimeNS: Int64(modified * 1_000_000_000), sha256: try digest(url))
    }

    public static func digest(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let data = try handle.read(upToCount: 1 << 20) ?? Data()
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

public struct StraightImage: Sendable, Equatable {
    public let width: Int
    public let height: Int
    public var pixels: [UInt8] // RGBA8, straight alpha, top-left origin

    public init(width: Int, height: Int, pixels: [UInt8]) {
        self.width = width
        self.height = height
        self.pixels = pixels
    }

    public var byteCount: Int { pixels.count }

    public func cgImage() -> CGImage? {
        let data = Data(pixels)
        guard let provider = CGDataProvider(data: data as CFData) else { return nil }
        let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue)
        return CGImage(
            width: width,
            height: height,
            bitsPerComponent: 8,
            bitsPerPixel: 32,
            bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: bitmapInfo,
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        )
    }
}

public struct MaskPoint: Codable, Sendable, Equatable {
    public var x: Double
    public var y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }
}

public struct MaskStroke: Codable, Sendable, Equatable {
    public var points: [MaskPoint]
    public var width: Double
    public var erase: Bool

    public init(points: [MaskPoint], width: Double, erase: Bool = false) {
        self.points = points
        self.width = width
        self.erase = erase
    }
}

public enum MaskRenderer {
    /// Renders a full-resolution grayscale mask, origin top-left, exactly like
    /// the Python/Qt mask contract: round caps/joins, antialiasing, ordered
    /// SourceOver strokes, and a filled circle for a single point.
    public static func render(width: Int, height: Int, strokes: [MaskStroke]) -> [UInt8] {
        guard width > 0, height > 0, width * height <= 100_000_000 else { return [] }
        var pixels = [UInt8](repeating: 0, count: width * height)
        let space = CGColorSpace(name: CGColorSpace.linearGray) ?? CGColorSpaceCreateDeviceGray()
        pixels.withUnsafeMutableBytes { raw in
            guard let context = CGContext(
                data: raw.baseAddress,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width,
                space: space,
                bitmapInfo: CGImageAlphaInfo.none.rawValue
            ) else { return }
            context.setShouldAntialias(true)
            // Core Graphics bitmap contexts are lower-left; PhotoPrep's mask
            // coordinates are top-left. Flip the context once.
            context.translateBy(x: 0, y: CGFloat(height))
            context.scaleBy(x: 1, y: -1)
            for stroke in strokes where !stroke.points.isEmpty {
                let lineWidth = max(1.0, stroke.width * Double(min(width, height)))
                let gray: CGFloat = stroke.erase ? 0 : 1
                context.setLineCap(.round)
                context.setLineJoin(.round)
                context.setLineWidth(lineWidth)
                context.setStrokeColor(gray: gray, alpha: 1)
                context.setFillColor(gray: gray, alpha: 1)
                if stroke.points.count == 1 {
                    let point = stroke.points[0]
                    let x = point.x * Double(width)
                    let y = point.y * Double(height)
                    let radius = lineWidth / 2
                    context.fillEllipse(in: CGRect(x: x - radius, y: y - radius, width: lineWidth, height: lineWidth))
                } else {
                    context.beginPath()
                    context.move(to: CGPoint(x: stroke.points[0].x * Double(width), y: stroke.points[0].y * Double(height)))
                    for point in stroke.points.dropFirst() {
                        context.addLine(to: CGPoint(x: point.x * Double(width), y: point.y * Double(height)))
                    }
                    context.strokePath()
                }
            }
        }
        return pixels
    }

    public static func isEmpty(_ mask: [UInt8]) -> Bool {
        !mask.contains { $0 != 0 }
    }
}

public struct ContextRect: Sendable, Equatable {
    public let x: Int
    public let y: Int
    public let width: Int
    public let height: Int

    public init(x: Int, y: Int, width: Int, height: Int) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }
}

public enum RetouchPreprocessor {
    public static let resolution = 512

    public static func contextRect(mask: [UInt8], width: Int, height: Int) -> ContextRect? {
        guard width > 0, height > 0, mask.count == width * height else { return nil }
        var minX = width
        var minY = height
        var maxX = -1
        var maxY = -1
        for y in 0..<height {
            let row = y * width
            for x in 0..<width where mask[row + x] != 0 {
                if x < minX { minX = x }
                if x > maxX { maxX = x }
                if y < minY { minY = y }
                if y > maxY { maxY = y }
            }
        }
        guard maxX >= minX, maxY >= minY else { return nil }
        let dx = maxX - minX + 1
        let dy = maxY - minY + 1
        let span = max(dx, dy)
        let side = max(256, span + max(64, span / 2))
        let centerX = (Double(minX) + Double(maxX)) / 2
        let centerY = (Double(minY) + Double(maxY)) / 2
        let cw = min(side, width)
        let ch = min(side, height)
        let rawX = Int((centerX - Double(cw) / 2).rounded(.toNearestOrEven))
        let rawY = Int((centerY - Double(ch) / 2).rounded(.toNearestOrEven))
        return ContextRect(
            x: min(max(0, rawX), width - cw),
            y: min(max(0, rawY), height - ch),
            width: cw,
            height: ch
        )
    }

    public static func prepare(source: StraightImage, mask: [UInt8]) throws -> PreparedInput {
        guard source.width > 0, source.height > 0,
              source.pixels.count == source.width * source.height * 4,
              mask.count == source.width * source.height else {
            throw RetouchFailure.invalidImage
        }
        guard !MaskRenderer.isEmpty(mask),
              let rect = contextRect(mask: mask, width: source.width, height: source.height) else {
            throw RetouchFailure.emptyMask
        }
        var image = [Float](repeating: 0, count: 3 * resolution * resolution)
        var mask512 = [Float](repeating: 0, count: resolution * resolution)
        for y in 0..<resolution {
            let sy = (Double(y) + 0.5) * Double(rect.height) / Double(resolution) - 0.5
            for x in 0..<resolution {
                let sx = (Double(x) + 0.5) * Double(rect.width) / Double(resolution) - 0.5
                for channel in 0..<3 {
                    image[channel * resolution * resolution + y * resolution + x] = Float(
                        bilinear(source: source, x: sx + Double(rect.x), y: sy + Double(rect.y), channel: channel) / 255.0
                    )
                }
                let gray = bilinearGray(source: source, mask: mask, x: sx + Double(rect.x), y: sy + Double(rect.y))
                mask512[y * resolution + x] = gray > 0 ? 1 : 0
            }
        }
        // A 5x5 inference-only dilation; the final composite uses the exact
        // original coverage, so no extra pixels are changed.
        var dilated = [Float](repeating: 0, count: resolution * resolution)
        for y in 0..<resolution {
            for x in 0..<resolution {
                var hit: Float = 0
                for dy in -2...2 where hit == 0 {
                    let yy = y + dy
                    guard yy >= 0, yy < resolution else { continue }
                    for dx in -2...2 {
                        let xx = x + dx
                        guard xx >= 0, xx < resolution else { continue }
                        if mask512[yy * resolution + xx] != 0 {
                            hit = 1
                            break
                        }
                    }
                }
                dilated[y * resolution + x] = hit
            }
        }
        return PreparedInput(image: image, mask: dilated, rect: rect)
    }

    private static func bilinear(source: StraightImage, x: Double, y: Double, channel: Int) -> Double {
        let w = source.width
        let h = source.height
        let x0 = Int(floor(x))
        let y0 = Int(floor(y))
        let fx = x - Double(x0)
        let fy = y - Double(y0)
        let xa = min(max(0, x0), w - 1)
        let xb = min(max(0, x0 + 1), w - 1)
        let ya = min(max(0, y0), h - 1)
        let yb = min(max(0, y0 + 1), h - 1)
        let p00 = source.pixels[(ya * w + xa) * 4 + channel]
        let p10 = source.pixels[(ya * w + xb) * 4 + channel]
        let p01 = source.pixels[(yb * w + xa) * 4 + channel]
        let p11 = source.pixels[(yb * w + xb) * 4 + channel]
        let top = Double(p00) * (1 - fx) + Double(p10) * fx
        let bottom = Double(p01) * (1 - fx) + Double(p11) * fx
        return top * (1 - fy) + bottom * fy
    }

    private static func bilinearGray(source: StraightImage, mask: [UInt8], x: Double, y: Double) -> Double {
        let w = source.width
        let h = source.height
        let x0 = Int(floor(x))
        let y0 = Int(floor(y))
        let fx = x - Double(x0)
        let fy = y - Double(y0)
        let xa = min(max(0, x0), w - 1)
        let xb = min(max(0, x0 + 1), w - 1)
        let ya = min(max(0, y0), h - 1)
        let yb = min(max(0, y0 + 1), h - 1)
        let p00 = mask[ya * w + xa]
        let p10 = mask[ya * w + xb]
        let p01 = mask[yb * w + xa]
        let p11 = mask[yb * w + xb]
        let top = Double(p00) * (1 - fx) + Double(p10) * fx
        let bottom = Double(p01) * (1 - fx) + Double(p11) * fx
        return top * (1 - fy) + bottom * fy
    }

    public static func composite(source: StraightImage, coverage: [UInt8], predicted: [Float], rect: ContextRect) throws -> StraightImage {
        let expected = 3 * resolution * resolution
        guard predicted.count == expected else { throw RetouchFailure.invalidOutputShape }
        guard predicted.allSatisfy({ $0.isFinite }) else { throw RetouchFailure.nonFiniteOutput }
        guard coverage.count == source.width * source.height else { throw RetouchFailure.invalidMask }
        var result = source
        for y in 0..<rect.height {
            let sy = (Double(y) + 0.5) * Double(resolution) / Double(rect.height) - 0.5
            for x in 0..<rect.width {
                let sx = (Double(x) + 0.5) * Double(resolution) / Double(rect.width) - 0.5
                let index = (rect.y + y) * source.width + (rect.x + x)
                let alpha = Double(coverage[index]) / 255.0
                guard alpha > 0 else { continue }
                for channel in 0..<3 {
                    let fill = bilinearPredicted(predicted, x: sx, y: sy, channel: channel)
                    let old = Double(source.pixels[index * 4 + channel])
                    let value = (fill * alpha + old * (1 - alpha)).rounded(.toNearestOrEven)
                    result.pixels[index * 4 + channel] = UInt8(min(255, max(0, value)))
                }
            }
        }
        return result
    }

    private static func bilinearPredicted(_ predicted: [Float], x: Double, y: Double, channel: Int) -> Double {
        let width = resolution
        let height = resolution
        let x0 = Int(floor(x))
        let y0 = Int(floor(y))
        let fx = x - Double(x0)
        let fy = y - Double(y0)
        let xa = min(max(0, x0), width - 1)
        let xb = min(max(0, x0 + 1), width - 1)
        let ya = min(max(0, y0), height - 1)
        let yb = min(max(0, y0 + 1), height - 1)
        let base = channel * width * height
        let p00 = Double(predicted[base + ya * width + xa])
        let p10 = Double(predicted[base + ya * width + xb])
        let p01 = Double(predicted[base + yb * width + xa])
        let p11 = Double(predicted[base + yb * width + xb])
        let top = p00 * (1 - fx) + p10 * fx
        let bottom = p01 * (1 - fx) + p11 * fx
        return top * (1 - fy) + bottom * fy
    }
}

public struct PreparedInput: Sendable {
    public let image: [Float]
    public let mask: [Float]
    public let rect: ContextRect
}

public actor StraightImageDecoder {
    private let policy: ResourcePolicy
    private let memorySnapshot: @Sendable () -> (resident: UInt64?, available: UInt64?)

    public init(
        policy: ResourcePolicy = ResourcePolicy(),
        memorySnapshot: @escaping @Sendable () -> (resident: UInt64?, available: UInt64?) = {
            (SystemMemory.physicalFootprintBytes(), SystemMemory.availableBytes())
        }
    ) {
        self.policy = policy
        self.memorySnapshot = memorySnapshot
    }

    public func decode(url: URL) throws -> StraightImage {
        guard url.isFileURL else { throw RetouchFailure.invalidImage }
        let url = url.standardizedFileURL.resolvingSymlinksInPath()
        guard let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetCount(source) == 1,
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let rawWidth = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let rawHeight = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue else {
            throw RetouchFailure.invalidImage
        }
        let orientation = (properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        let pixels = try policy.pixelCount(width: rawWidth, height: rawHeight)
        guard pixels <= 40_000_000 else { throw RetouchFailure.imageTooLarge }
        let snapshot = memorySnapshot()
        guard let resident = snapshot.resident else { throw RetouchFailure.insufficientMemory }
        try policy.admit(
            bytes: pixels * 4 + 64 * ResourcePolicy.mib,
            residentBytes: resident,
            availableBytes: snapshot.available,
            pressure: .normal
        )
        let options: [CFString: Any] = [
            kCGImageSourceShouldCache: true,
            kCGImageSourceShouldCacheImmediately: true
        ]
        guard let image = CGImageSourceCreateImageAtIndex(source, 0, options as CFDictionary) else {
            throw RetouchFailure.invalidImage
        }
        let decoded = try Self.rgba(from: image, width: rawWidth, height: rawHeight)
        return try Self.orient(decoded, orientation: orientation)
    }

    private static func rgba(from image: CGImage, width: Int, height: Int) throws -> StraightImage {
        guard image.bitsPerComponent == 8, image.width == width, image.height == height else {
            throw RetouchFailure.unsupportedPixelLayout
        }
        guard let data = image.dataProvider?.data, let pointer = CFDataGetBytePtr(data) else {
            throw RetouchFailure.invalidImage
        }
        let alpha = image.alphaInfo
        if alpha == .premultipliedLast || alpha == .premultipliedFirst {
            // Hidden RGB cannot be reconstructed from a premultiplied buffer.
            // Fully opaque images are safe, but we still reject anything with
            // a non-255 alpha sample.
            let bytes = CFDataGetLength(data)
            let step = image.bitsPerPixel / 8
            if step > 0 {
                for index in stride(from: 0, to: bytes, by: step) {
                    let alphaIndex = (alpha == .premultipliedFirst) ? index : index + 3
                    if alphaIndex < bytes && pointer[alphaIndex] != 255 {
                        throw RetouchFailure.premultipliedAlpha
                    }
                }
            }
        }
        let bytesPerRow = image.bytesPerRow
        let step = image.bitsPerPixel / 8
        guard step == 3 || step == 4 else { throw RetouchFailure.unsupportedPixelLayout }
        let alphaFirst = alpha == .first || alpha == .premultipliedFirst || alpha == .noneSkipFirst
        var output = [UInt8](repeating: 255, count: width * height * 4)
        for y in 0..<height {
            let row = y * bytesPerRow
            for x in 0..<width {
                let sourceIndex = row + x * step
                let target = (y * width + x) * 4
                if step == 4 {
                    if alphaFirst {
                        output[target] = pointer[sourceIndex + 1]
                        output[target + 1] = pointer[sourceIndex + 2]
                        output[target + 2] = pointer[sourceIndex + 3]
                        output[target + 3] = pointer[sourceIndex]
                    } else {
                        output[target] = pointer[sourceIndex]
                        output[target + 1] = pointer[sourceIndex + 1]
                        output[target + 2] = pointer[sourceIndex + 2]
                        output[target + 3] = pointer[sourceIndex + 3]
                    }
                } else {
                    output[target] = pointer[sourceIndex]
                    output[target + 1] = pointer[sourceIndex + 1]
                    output[target + 2] = pointer[sourceIndex + 2]
                    output[target + 3] = 255
                }
            }
        }
        return StraightImage(width: width, height: height, pixels: output)
    }

    private static func orient(_ image: StraightImage, orientation: Int) throws -> StraightImage {
        switch orientation {
        case 1: return image
        case 2: return flipHorizontal(image)
        case 3: return rotate180(image)
        case 4: return flipVertical(image)
        case 5: return transpose(image)
        case 6: return rotate90(image)
        case 7: return transverse(image)
        case 8: return rotate270(image)
        default: throw RetouchFailure.invalidImage
        }
    }

    private static func flipHorizontal(_ image: StraightImage) -> StraightImage {
        var out = image
        for y in 0..<image.height {
            for x in 0..<image.width {
                let src = (y * image.width + x) * 4
                let dst = (y * image.width + (image.width - 1 - x)) * 4
                out.pixels.replaceSubrange(dst..<(dst + 4), with: image.pixels[src..<(src + 4)])
            }
        }
        return out
    }

    private static func flipVertical(_ image: StraightImage) -> StraightImage {
        var out = image
        for y in 0..<image.height {
            let srcRow = (image.height - 1 - y) * image.width * 4
            let dstRow = y * image.width * 4
            out.pixels.replaceSubrange(dstRow..<(dstRow + image.width * 4), with: image.pixels[srcRow..<(srcRow + image.width * 4)])
        }
        return out
    }

    private static func rotate180(_ image: StraightImage) -> StraightImage {
        var out = image
        let count = image.width * image.height
        for index in 0..<count {
            let src = index * 4
            let dst = (count - 1 - index) * 4
            out.pixels.replaceSubrange(dst..<(dst + 4), with: image.pixels[src..<(src + 4)])
        }
        return out
    }

    private static func rotate90(_ image: StraightImage) -> StraightImage {
        var out = StraightImage(width: image.height, height: image.width, pixels: [UInt8](repeating: 0, count: image.pixels.count))
        for y in 0..<image.height {
            for x in 0..<image.width {
                let dstX = image.height - 1 - y
                let dstY = x
                let src = (y * image.width + x) * 4
                let dst = (dstY * out.width + dstX) * 4
                out.pixels.replaceSubrange(dst..<(dst + 4), with: image.pixels[src..<(src + 4)])
            }
        }
        return out
    }

    private static func rotate270(_ image: StraightImage) -> StraightImage {
        var out = StraightImage(width: image.height, height: image.width, pixels: [UInt8](repeating: 0, count: image.pixels.count))
        for y in 0..<image.height {
            for x in 0..<image.width {
                let dstX = y
                let dstY = image.width - 1 - x
                let src = (y * image.width + x) * 4
                let dst = (dstY * out.width + dstX) * 4
                out.pixels.replaceSubrange(dst..<(dst + 4), with: image.pixels[src..<(src + 4)])
            }
        }
        return out
    }

    private static func transpose(_ image: StraightImage) -> StraightImage {
        var out = StraightImage(width: image.height, height: image.width, pixels: [UInt8](repeating: 0, count: image.pixels.count))
        for y in 0..<image.height {
            for x in 0..<image.width {
                let src = (y * image.width + x) * 4
                let dst = (x * out.width + y) * 4
                out.pixels.replaceSubrange(dst..<(dst + 4), with: image.pixels[src..<(src + 4)])
            }
        }
        return out
    }

    private static func transverse(_ image: StraightImage) -> StraightImage {
        var out = StraightImage(width: image.height, height: image.width, pixels: [UInt8](repeating: 0, count: image.pixels.count))
        for y in 0..<image.height {
            for x in 0..<image.width {
                let src = (y * image.width + x) * 4
                let dst = ((out.height - 1 - x) * out.width + (out.width - 1 - y)) * 4
                out.pixels.replaceSubrange(dst..<(dst + 4), with: image.pixels[src..<(src + 4)])
            }
        }
        return out
    }
}
