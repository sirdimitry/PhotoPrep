import Foundation
import Darwin

public struct SessionError: Error, Equatable, Sendable {
    public let code: String
    public init(_ code: String) { self.code = code }
}

public struct SessionView: Sendable, Equatable {
    public var fit: Bool = true
    public var zoom: Double = 1
    public var centerX: Double = 0.5
    public var centerY: Double = 0.5
}

public struct SessionPass: Sendable, Equatable {
    public var strokes: [MaskStroke]
    public var modelID: String
}

public struct SessionCrop: Sendable, Equatable {
    public var x: Double, y: Double, width: Double, height: Double
}

public struct SessionPhoto: Sendable {
    public var url: URL
    public var view: SessionView = SessionView()
    public var mask: [MaskStroke] = []
    public var passes: [SessionPass] = []
    public var crop: SessionCrop?
    public var hasLogo = false
    public var sourceMissing = false
}

public struct SessionWorkspace: Sendable {
    public var version: Int
    public var photos: [SessionPhoto]
    public var selected: URL?
    public var outputWidth: Int
    public var outputHeight: Int
    public var skipped: Int = 0
    public var readOnlyReason: String?
    public var readOnly: Bool { readOnlyReason != nil }
}

public enum SessionCodec {
    public static let maxBytes = 5 * 1024 * 1024
    public static let maxPhotos = 10_000
    public static let maxPoints = 200_000
    public static let maxPasses = 100

    public static func load(_ url: URL) throws -> SessionWorkspace {
        let handle: FileHandle
        do { handle = try FileHandle(forReadingFrom: url) } catch { throw SessionError("session_unreadable") }
        defer { try? handle.close() }
        let data = try handle.read(upToCount: maxBytes + 1) ?? Data()
        guard data.count <= maxBytes else { throw SessionError("session_too_large") }
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["format"] as? String == "PhotoPrep",
              let version = object["version"] as? Int, (1...7).contains(version),
              let entries = object["photos"] as? [[String: Any]],
              entries.count <= maxPhotos else { throw SessionError("session_invalid") }
        let output = (object["output_size"] as? [Int]) ?? [1136, 710]
        guard output.count == 2, output.allSatisfy({ (128...16000).contains($0) }) else {
            throw SessionError("session_invalid")
        }
        let parent = url.deletingLastPathComponent()
        var photos: [SessionPhoto] = []
        var skipped = 0
        var readOnly: String?
        var totalPoints = 0
        var seen = Set<String>()
        for entry in entries {
            guard let path = entry["path"] as? String else { throw SessionError("session_invalid") }
            let file = parent.appendingPathComponent(path).standardizedFileURL
            guard seen.insert(file.path).inserted else { continue }
            var photo = SessionPhoto(url: file)
            photo.sourceMissing = !FileManager.default.fileExists(atPath: file.path)
            if photo.sourceMissing { skipped += 1 }
            photo.view = parseView(entry["view"])
            if version >= 2, let edits = entry["edits"] as? [String: Any] {
                let parsed = try parseEdits(edits, totalPoints: &totalPoints)
                photo.mask = parsed.mask
                photo.passes = parsed.passes
                photo.crop = parsed.crop
                photo.hasLogo = parsed.hasLogo
                if parsed.crop != nil { readOnly = "unsupported_crop" }
                if parsed.hasLogo { readOnly = readOnly ?? "unsupported_logo" }
                if parsed.passes.contains(where: { $0.modelID != "lama" }) { readOnly = "unsupported_model" }
            }
            photos.append(photo)
        }
        let selectedPath = (object["selected"] as? String).map { parent.appendingPathComponent($0).standardizedFileURL }
        let selected = photos.first(where: { $0.url == selectedPath })?.url ?? photos.first?.url
        return SessionWorkspace(version: version, photos: photos, selected: selected,
                                outputWidth: output[0], outputHeight: output[1],
                                skipped: skipped, readOnlyReason: readOnly)
    }

    public static func save(_ workspace: SessionWorkspace, to url: URL) throws {
        guard !workspace.readOnly else { throw SessionError("session_read_only") }
        guard workspace.photos.count <= maxPhotos else { throw SessionError("session_too_large") }
        var points = 0
        for photo in workspace.photos {
            guard photo.crop == nil, !photo.hasLogo else { throw SessionError("session_read_only") }
            guard photo.passes.count <= maxPasses,
                  photo.passes.allSatisfy({ $0.modelID == "lama" }) else {
                throw SessionError("session_read_only")
            }
            points += photo.mask.reduce(0) { $0 + $1.points.count }
            points += photo.passes.reduce(0) { $0 + $1.strokes.reduce(0) { $0 + $1.points.count } }
        }
        guard points <= maxPoints else { throw SessionError("session_too_large") }
        let version = workspace.photos.contains(where: { !$0.passes.isEmpty }) ? 3 : 2
        let parent = url.deletingLastPathComponent()
        func relative(_ target: URL) -> String {
            let base = parent.standardizedFileURL.pathComponents
            let path = target.standardizedFileURL.pathComponents
            var common = 0
            while common < base.count && common < path.count && base[common] == path[common] { common += 1 }
            let up = Array(repeating: "..", count: max(0, base.count - common))
            let down = Array(path.dropFirst(common))
            let joined = (up + down).joined(separator: "/")
            return joined.isEmpty ? target.lastPathComponent : joined
        }
        let photoObjects: [[String: Any]] = workspace.photos.map { photo in
            var edits: [String: Any] = ["strokes": encodeStrokes(photo.mask)]
            if !photo.passes.isEmpty {
                edits["passes"] = photo.passes.map { encodeStrokes($0.strokes) }
                edits["pass_models"] = photo.passes.map(\.modelID)
            }
            let view: [String: Any] = ["fit": photo.view.fit, "zoom": photo.view.zoom,
                                       "center_x": photo.view.centerX, "center_y": photo.view.centerY]
            return ["path": relative(photo.url), "view": view, "edits": edits]
        }
        let document: [String: Any] = [
            "format": "PhotoPrep", "version": version,
            "output_size": [workspace.outputWidth, workspace.outputHeight],
            "selected": workspace.selected.map(relative) ?? NSNull(),
            "photos": photoObjects
        ]
        let data = try JSONSerialization.data(withJSONObject: document, options: [.prettyPrinted, .sortedKeys])
        guard data.count <= maxBytes else { throw SessionError("session_too_large") }
        try atomicPrivateWrite(data, to: url)
    }

    private static func atomicPrivateWrite(_ data: Data, to url: URL) throws {
        let directory = url.deletingLastPathComponent()
        let temp = directory.appendingPathComponent(".\(url.lastPathComponent).tmp.\(UUID().uuidString)")
        do {
            try data.write(to: temp, options: [])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temp.path)
            let handle = try FileHandle(forWritingTo: temp)
            try handle.synchronize()
            try handle.close()
            guard rename(temp.path, url.path) == 0 else { throw SessionError("session_save_failed") }
        } catch let error as SessionError {
            try? FileManager.default.removeItem(at: temp)
            throw error
        } catch {
            try? FileManager.default.removeItem(at: temp)
            throw SessionError("session_save_failed")
        }
    }

    private static func parseView(_ value: Any?) -> SessionView {
        guard let item = value as? [String: Any] else { return SessionView() }
        let zoom = (item["zoom"] as? NSNumber)?.doubleValue ?? 1
        let x = (item["center_x"] as? NSNumber)?.doubleValue ?? 0.5
        let y = (item["center_y"] as? NSNumber)?.doubleValue ?? 0.5
        guard zoom.isFinite, x.isFinite, y.isFinite else { return SessionView() }
        return SessionView(fit: item["fit"] as? Bool ?? true,
                           zoom: min(16, max(0.05, zoom)),
                           centerX: min(1, max(0, x)), centerY: min(1, max(0, y)))
    }

    private struct ParsedEdits { var mask: [MaskStroke]; var passes: [SessionPass]; var crop: SessionCrop?; var hasLogo: Bool }

    private static func parseEdits(_ value: [String: Any], totalPoints: inout Int) throws -> ParsedEdits {
        guard let strokeArray = value["strokes"] as? [[String: Any]] else {
            if value["strokes"] == nil { return ParsedEdits(mask: [], passes: [], crop: nil, hasLogo: false) }
            throw SessionError("session_invalid")
        }
        var points = 0
        let mask = try parseStrokes(strokeArray, total: &points)
        totalPoints += points
        guard totalPoints <= maxPoints else { throw SessionError("session_too_large") }
        let passArrays = value["passes"] as? [[[String: Any]]] ?? []
        guard passArrays.count <= maxPasses else { throw SessionError("session_invalid") }
        let models = value["pass_models"] as? [String] ?? []
        guard models.isEmpty || models.count == passArrays.count else { throw SessionError("session_invalid") }
        var passes: [SessionPass] = []
        for (index, group) in passArrays.enumerated() {
            var groupPoints = 0
            let strokes = try parseStrokes(group, total: &groupPoints)
            guard !strokes.isEmpty else { throw SessionError("session_invalid") }
            totalPoints += groupPoints
            guard totalPoints <= maxPoints else { throw SessionError("session_too_large") }
            passes.append(SessionPass(strokes: strokes, modelID: models.isEmpty ? "lama" : models[index]))
        }
        var crop: SessionCrop?
        if let raw = value["crop"] as? [String: Any] {
            let c = SessionCrop(x: (raw["x"] as? NSNumber)?.doubleValue ?? .nan,
                                y: (raw["y"] as? NSNumber)?.doubleValue ?? .nan,
                                width: (raw["width"] as? NSNumber)?.doubleValue ?? .nan,
                                height: (raw["height"] as? NSNumber)?.doubleValue ?? .nan)
            guard c.x.isFinite, c.y.isFinite, c.width.isFinite, c.height.isFinite,
                  c.x >= 0, c.y >= 0, c.width > 0, c.height > 0,
                  c.x + c.width <= 1.000001, c.y + c.height <= 1.000001 else { throw SessionError("session_invalid") }
            crop = c
        }
        let hasLogo = value["logo"] is [String: Any]
        return ParsedEdits(mask: mask, passes: passes, crop: crop, hasLogo: hasLogo)
    }

    private static func parseStrokes(_ array: [[String: Any]], total: inout Int) throws -> [MaskStroke] {
        var result: [MaskStroke] = []
        for item in array {
            guard let rawPoints = item["points"] as? [[Any]], !rawPoints.isEmpty,
                  let width = (item["width"] as? NSNumber)?.doubleValue,
                  width.isFinite, width > 0, width <= 512 else { throw SessionError("session_invalid") }
            var points: [MaskPoint] = []
            for pair in rawPoints {
                guard pair.count == 2, let x = (pair[0] as? NSNumber)?.doubleValue,
                      let y = (pair[1] as? NSNumber)?.doubleValue,
                      x.isFinite, y.isFinite, abs(x) <= 1_000_000, abs(y) <= 1_000_000 else {
                    throw SessionError("session_invalid")
                }
                points.append(MaskPoint(x: x, y: y))
            }
            let erase = item["erase"] as? Bool ?? false
            result.append(MaskStroke(points: points, width: width, erase: erase))
            total += points.count
            guard total <= maxPoints else { throw SessionError("session_too_large") }
        }
        return result
    }

    private static func encodeStrokes(_ strokes: [MaskStroke]) -> [[String: Any]] {
        strokes.map { stroke in
            ["points": stroke.points.map { [$0.x, $0.y] }, "width": stroke.width, "erase": stroke.erase]
        }
    }
}
