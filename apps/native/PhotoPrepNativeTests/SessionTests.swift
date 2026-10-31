import XCTest
@testable import PhotoPrepCore

final class SessionTests: XCTestCase {
    private func fixture(_ version: Int, edits: String = "{}") throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: false)
        try Data("img".utf8).write(to: dir.appendingPathComponent("photo.png"))
        let json = """
        {"format":"PhotoPrep","version":\(version),"output_size":[1136,710],
         "selected":"photo.png","photos":[{"path":"photo.png","view":{"fit":true,"zoom":1,"center_x":0.5,"center_y":0.5},
         "edits":\(edits)}]}
        """
        let url = dir.appendingPathComponent("set.photoprep.json")
        try Data(json.utf8).write(to: url)
        return url
    }

    func testLoadsSchemasOneThroughSevenWithoutLosingUnsupportedFeatures() throws {
        let v1 = try fixture(1)
        XCTAssertEqual(try SessionCodec.load(v1).version, 1)
        let v2 = try fixture(2, edits: #"{"strokes":[{"points":[[0.1,0.2],[0.3,0.4]],"width":0.1}]}"#)
        let loaded2 = try SessionCodec.load(v2)
        XCTAssertEqual(loaded2.photos[0].mask.count, 1)
        XCTAssertEqual(loaded2.photos[0].mask[0].points.count, 2)
        let v3 = try fixture(3, edits: #"{"strokes":[],"passes":[[{"points":[[0.5,0.5]],"width":0.2}]],"pass_models":["lama"]}"#)
        let loaded3 = try SessionCodec.load(v3)
        XCTAssertEqual(loaded3.photos[0].passes.count, 1)
        XCTAssertEqual(loaded3.photos[0].passes[0].modelID, "lama")
        let v4 = try fixture(4, edits: #"{"strokes":[],"passes":[[{"points":[[0.5,0.5]],"width":0.2}]],"pass_models":["migan"]}"#)
        XCTAssertTrue(try SessionCodec.load(v4).readOnly)
        let v5 = try fixture(5, edits: #"{"strokes":[],"logo":{"path":"logo.png","width":0.2,"opacity":1,"x":1,"y":1}}"#)
        XCTAssertTrue(try SessionCodec.load(v5).readOnly)
        let v6 = try fixture(6, edits: #"{"strokes":[],"logo":{"path":"logo.png","width":0.2,"opacity":1,"x":1,"y":1,"mode":"template"}}"#)
        XCTAssertTrue(try SessionCodec.load(v6).readOnly)
        let v7 = try fixture(7, edits: #"{"strokes":[],"passes":[[{"points":[[0.5,0.5]],"width":0.2}]],"pass_models":["sdxl"]}"#)
        XCTAssertTrue(try SessionCodec.load(v7).readOnly)
    }

    func testCropIsReadOnlyAndNotSilentlyDiscarded() throws {
        let url = try fixture(2, edits: #"{"strokes":[],"crop":{"x":0.1,"y":0.1,"width":0.5,"height":0.5}}"#)
        let loaded = try SessionCodec.load(url)
        XCTAssertTrue(loaded.readOnly)
        XCTAssertEqual(loaded.readOnlyReason, "unsupported_crop")
        XCTAssertNotNil(loaded.photos[0].crop)
        XCTAssertThrowsError(try SessionCodec.save(loaded, to: url)) { error in
            XCTAssertEqual((error as? SessionError)?.code, "session_read_only")
        }
    }

    func testSaveIsMinimalAtomicPrivateAndRoundTrips() throws {
        let url = try fixture(1)
        var workspace = try SessionCodec.load(url)
        workspace.photos[0].mask = [MaskStroke(points: [MaskPoint(x: 0.2, y: 0.3)], width: 0.1)]
        workspace.photos[0].passes = [SessionPass(strokes: [MaskStroke(points: [MaskPoint(x: 0.5, y: 0.5)], width: 0.2)], modelID: "lama")]
        try SessionCodec.save(workspace, to: url)
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        XCTAssertEqual((attrs[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        let reloaded = try SessionCodec.load(url)
        XCTAssertEqual(reloaded.version, 3)
        XCTAssertEqual(reloaded.photos[0].mask.count, 1)
        XCTAssertEqual(reloaded.photos[0].passes[0].modelID, "lama")
    }

    func testUnsupportedPassModelCannotBeSaved() throws {
        let url = try fixture(4, edits: #"{"strokes":[],"passes":[[{"points":[[0.5,0.5]],"width":0.2}]],"pass_models":["migan"]}"#)
        let loaded = try SessionCodec.load(url)
        XCTAssertThrowsError(try SessionCodec.save(loaded, to: url))
    }
}
