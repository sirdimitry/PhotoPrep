import Foundation
import ImageIO
import CoreGraphics
import UniformTypeIdentifiers

actor ThumbnailCache {
    static let shared = ThumbnailCache()
    private var cache: [URL: CGImage] = [:]
    private var order: [URL] = []
    private let limit = 64

    func image(for url: URL, maxPixel: Int = 240) -> CGImage? {
        if let hit = cache[url] { return hit }
        guard let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary) else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel,
            kCGImageSourceShouldCache: false
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
        cache[url] = image
        order.append(url)
        if order.count > limit, let old = order.first {
            order.removeFirst(); cache.removeValue(forKey: old)
        }
        return image
    }
}

struct PhotoFileInfo {
    let name: String
    let width: Int
    let height: Int
    let format: String
    let bytes: Int64
    let exportWidth: Int
    let exportHeight: Int
}
