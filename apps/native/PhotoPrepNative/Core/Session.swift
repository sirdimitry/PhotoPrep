import Foundation
import Darwin
import CoreFoundation

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

public struct SessionLogo: Sendable, Equatable {
    public var path: String
    public var width: Double
    public var opacity: Double
    public var x: Double
    public var y: Double
    public var enabled: Bool
    public var mode: String
}

public struct SessionPhoto: Sendable {
    public var url: URL
    public var view: SessionView = SessionView()
    public var mask: [MaskStroke] = []
    public var passes: [SessionPass] = []
    public var crop: SessionCrop?
    public var logo: SessionLogo?
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
              let version = integer(object["version"]), (1...7).contains(version),
              let entries = object["photos"] as? [[String: Any]],
              entries.count <= maxPhotos else { throw SessionError("session_invalid") }
        let output: [Int]
        if let rawOutput = object["output_size"] {
            guard let array = rawOutput as? [Any], array.count == 2,
                  let w = integer(array[0]), let h = integer(array[1]),
                  (128...16000).contains(w), (128...16000).contains(h) else {
                throw SessionError("session_invalid")
            }
            output = [w, h]
        } else {
            output = [1136, 710]
        }
        let parent = url.deletingLastPathComponent()
        var photos: [SessionPhoto] = []
        var skipped = 0
        var readOnly: String?
        var totalPoints = 0
        var seen = Set<String>()
        for entry in entries {
            guard let path = entry["path"] as? String else { throw SessionError("session_invalid") }
            let file = path.hasPrefix("/") ? URL(fileURLWithPath: path).standardizedFileURL
                : parent.appendingPathComponent(path).standardizedFileURL
            guard seen.insert(file.path).inserted else { continue }
            var photo = SessionPhoto(url: file)
            photo.sourceMissing = !FileManager.default.fileExists(atPath: file.path)
            if photo.sourceMissing { skipped += 1 }
            photo.view = parseView(entry["view"])
            if version >= 2, let rawEdits = entry["edits"], !(rawEdits is NSNull) {
                guard let edits = rawEdits as? [String: Any] else { throw SessionError("session_invalid") }
                let parsed = try parseEdits(edits, totalPoints: &totalPoints)
                photo.mask = parsed.mask
                photo.passes = parsed.passes
                photo.crop = parsed.crop
                photo.logo = parsed.logo.map { logo in
                    var value = logo
                    value.path = logo.path.hasPrefix("/") ? logo.path
                        : parent.appendingPathComponent(logo.path).standardizedFileURL.path
                    return value
                }
                if parsed.passes.contains(where: { $0.modelID != "lama" }) { readOnly = "unsupported_model" }
            }
            photos.append(photo)
        }
        let selectedPath = (object["selected"] as? String).map { raw -> URL in
            raw.hasPrefix("/") ? URL(fileURLWithPath: raw).standardizedFileURL
                : parent.appendingPathComponent(raw).standardizedFileURL
        }
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
            guard !photo.sourceMissing else { throw SessionError("session_incomplete") }
            guard photo.passes.count <= maxPasses,
                  photo.passes.allSatisfy({ $0.modelID == "lama" }) else {
                throw SessionError("session_read_only")
            }
            points += photo.mask.reduce(0) { $0 + $1.points.count }
            points += photo.passes.reduce(0) { $0 + $1.strokes.reduce(0) { $0 + $1.points.count } }
        }
        guard points <= maxPoints else { throw SessionError("session_too_large") }
        let hasTemplate = workspace.photos.contains { $0.logo?.mode == "template" }
        let hasLogo = workspace.photos.contains { $0.logo != nil }
        let version = hasTemplate ? 6 : hasLogo ? 5 : workspace.photos.contains(where: { !$0.passes.isEmpty }) ? 3 : 2
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
            if let crop = photo.crop {
                edits["crop"] = ["x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height]
            }
            if var logo = photo.logo {
                logo.path = relative(URL(fileURLWithPath: logo.path))
                edits["logo"] = ["path": logo.path, "width": logo.width, "opacity": logo.opacity,
                                 "x": logo.x, "y": logo.y, "enabled": logo.enabled, "mode": logo.mode]
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

    private struct ParsedEdits { var mask: [MaskStroke]; var passes: [SessionPass]; var crop: SessionCrop?; var logo: SessionLogo? }

    private static func parseEdits(_ value: [String: Any], totalPoints: inout Int) throws -> ParsedEdits {
        // Missing strokes means an empty current mask; passes/crop/logo are
        // still parsed (Python schema 2+ behavior).
        var points = 0
        var mask: [MaskStroke] = []
        if let rawStrokes = value["strokes"], !(rawStrokes is NSNull) {
            guard let strokeArray = rawStrokes as? [[String: Any]] else { throw SessionError("session_invalid") }
            mask = try parseStrokes(strokeArray, total: &points)
        }
        totalPoints += points
        guard totalPoints <= maxPoints else { throw SessionError("session_too_large") }

        var passes: [SessionPass] = []
        if let rawPasses = value["passes"], !(rawPasses is NSNull) {
            guard let array = rawPasses as? [Any] else { throw SessionError("session_invalid") }
            let passArrays: [[[String: Any]]]
            if array.isEmpty {
                passArrays = []
            } else {
                guard let nested = rawPasses as? [[[String: Any]]] else { throw SessionError("session_invalid") }
                passArrays = nested
            }
            guard passArrays.count <= maxPasses else { throw SessionError("session_invalid") }
            let models: [String]
            if let rawModels = value["pass_models"], !(rawModels is NSNull) {
                guard let parsed = rawModels as? [String], parsed.count == passArrays.count else {
                    throw SessionError("session_invalid")
                }
                models = parsed
            } else {
                models = Array(repeating: "lama", count: passArrays.count)
            }
            for (index, group) in passArrays.enumerated() {
                var groupPoints = 0
                let strokes = try parseStrokes(group, total: &groupPoints)
                guard !strokes.isEmpty else { throw SessionError("session_invalid") }
                totalPoints += groupPoints
                guard totalPoints <= maxPoints else { throw SessionError("session_too_large") }
                passes.append(SessionPass(strokes: strokes, modelID: models[index]))
            }
        } else if value["pass_models"] != nil {
            throw SessionError("session_invalid")
        }

        var crop: SessionCrop?
        if let rawCrop = value["crop"], !(rawCrop is NSNull) {
            guard let raw = rawCrop as? [String: Any],
                  let x = number(raw["x"]), let y = number(raw["y"]),
                  let width = number(raw["width"]), let height = number(raw["height"]),
                  x >= 0, y >= 0, width > 0, height > 0,
                  x + width <= 1.000001, y + height <= 1.000001 else {
                throw SessionError("session_invalid")
            }
            crop = SessionCrop(x: x, y: y, width: width, height: height)
        }

        var logo: SessionLogo?
        if let rawLogo = value["logo"], !(rawLogo is NSNull) {
            guard let raw = rawLogo as? [String: Any],
                  let path = raw["path"] as? String, !path.isEmpty, !path.contains("\0"), path.count <= 4096,
                  let width = number(raw["width"], default: 0.15),
                  let opacity = number(raw["opacity"], default: 1),
                  let x = number(raw["x"], default: 1),
                  let y = number(raw["y"], default: 1),
                  (0.01...0.94).contains(width), (0...1).contains(opacity),
                  (0...1).contains(x), (0...1).contains(y) else {
                throw SessionError("session_invalid")
            }
            let enabled: Bool
            if let rawEnabled = raw["enabled"] {
                guard let n = rawEnabled as? NSNumber,
                      CFGetTypeID(n) == CFBooleanGetTypeID() else { throw SessionError("session_invalid") }
                enabled = n.boolValue
            } else { enabled = true }
            let mode: String
            if let rawMode = raw["mode"] {
                guard let m = rawMode as? String, ["logo", "template"].contains(m) else {
                    throw SessionError("session_invalid")
                }
                mode = m
            } else { mode = "logo" }
            logo = SessionLogo(path: path, width: width, opacity: opacity, x: x, y: y,
                               enabled: enabled, mode: mode)
        }
        return ParsedEdits(mask: mask, passes: passes, crop: crop, logo: logo)
    }

    private static func integer(_ value: Any?) -> Int? {
        guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
        let d = n.doubleValue
        guard d.isFinite, d == d.rounded() else { return nil }
        return Int(d)
    }

    private static func number(_ value: Any?, default fallback: Double? = nil) -> Double? {
        if value == nil { return fallback }
        guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
        let d = n.doubleValue
        return d.isFinite ? d : nil
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
            let erase: Bool
            if let rawErase = item["erase"] {
                guard let n = rawErase as? NSNumber,
                      CFGetTypeID(n) == CFBooleanGetTypeID() else { throw SessionError("session_invalid") }
                erase = n.boolValue
            } else { erase = false }
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
