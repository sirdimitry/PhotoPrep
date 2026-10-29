import Foundation
import ImageIO
import UniformTypeIdentifiers

public struct PhotoHeader: Sendable, Equatable, Identifiable {
    public var id: URL { url }
    public let url: URL
    public let width: Int
    public let height: Int
}

/// CGImage is immutable after ImageIO creation. Sharing this read-only reference is
/// safe; mutable pixel storage and CGContext never cross actor boundaries.
public struct PhotoPreview: @unchecked Sendable {
    public let image: CGImage
    public let header: PhotoHeader
}

/// Synchronous decoding on one actor executor bounds outstanding decoder allocations.
/// Callers coalesce selection requests and reject late results by generation.
public actor PreviewDecoder {
    private let policy: ResourcePolicy
    private let memorySnapshot: @Sendable () -> (resident: UInt64?, available: UInt64?)
    public init(policy: ResourcePolicy = ResourcePolicy(),
                memorySnapshot: @escaping @Sendable () -> (resident: UInt64?, available: UInt64?) = {
                    (SystemMemory.residentBytes(), SystemMemory.availableBytes())
                }) {
        self.policy = policy
        self.memorySnapshot = memorySnapshot
    }

    public func header(url: URL) throws -> PhotoHeader {
        try Task.checkCancellation()
        return try autoreleasepool { try inspect(url: url).header }
    }

    public func preview(url: URL) throws -> PhotoPreview {
        try Task.checkCancellation()
        return try autoreleasepool {
            let (source, header) = try inspect(url: url)
            let snapshot = memorySnapshot()
            guard let resident = snapshot.resident else { throw ResourceFailure.insufficientMemory }
            try policy.admit(bytes: policy.previewReservation(width: header.width, height: header.height),
                             residentBytes: resident, availableBytes: snapshot.available, pressure: .normal)
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: policy.previewEdge,
                kCGImageSourceShouldCache: false,
                kCGImageSourceShouldCacheImmediately: false
            ]
            guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
                  image.width > 0, image.height > 0,
                  image.width <= policy.previewEdge, image.height <= policy.previewEdge else {
                throw ResourceFailure.invalidImage
            }
            try Task.checkCancellation()
            return PhotoPreview(image: image, header: header)
        }
    }

    private func inspect(url: URL) throws -> (source: CGImageSource, header: PhotoHeader) {
        guard url.isFileURL else { throw ResourceFailure.invalidImage }
        let url = url.standardizedFileURL.resolvingSymlinksInPath()
        guard
              let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
              let identifier = CGImageSourceGetType(source),
              let type = UTType(identifier as String),
              [UTType.jpeg, .png, .tiff, .bmp, .webP].contains(where: { type.conforms(to: $0) }),
              CGImageSourceGetCount(source) == 1,
              let info = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = info[kCGImagePropertyPixelWidth] as? Int,
              let height = info[kCGImagePropertyPixelHeight] as? Int else { throw ResourceFailure.invalidImage }
        _ = try policy.pixelCount(width: width, height: height)
        let orientation = info[kCGImagePropertyOrientation] as? Int ?? 1
        guard (1...8).contains(orientation) else { throw ResourceFailure.invalidImage }
        return (source, PhotoHeader(url: url, width: orientation >= 5 ? height : width,
                                    height: orientation >= 5 ? width : height))
    }
}
