// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PhotoPrepCore",
    platforms: [.macOS(.v14)],
    products: [.library(name: "PhotoPrepCore", targets: ["PhotoPrepCore"])],
    targets: [
        .target(name: "PhotoPrepCore", path: "PhotoPrepNative/Core"),
        .testTarget(name: "PhotoPrepCoreTests", dependencies: ["PhotoPrepCore"], path: "PhotoPrepNativeTests")
    ]
)
