# PhotoPrep Native

SwiftUI macOS application, **development foundation only**. No Native release or
Core ML retouch engine is available yet. The working Python application remains
in [../python/](../python/), unchanged by this foundation.

29.10.2026: Xcode project, distinct app identity, RU/EN, dark/light themes, file
import and bounded ImageIO preview. [Current status and limits](STATUS.md).
The primary quality candidate is LaMa; model quality is evaluated separately from
speed and binary size. [Measured Python reference](REFERENCE-RESULTS.md).

## Build and test

Requires Xcode with Swift 6+, deployment target macOS 14. No external Swift packages.
Use the installed Xcode via a per-command DEVELOPER_DIR if necessary; do not change
the user's global toolchain. From the repository root:

```bash
swift test --package-path apps/native --scratch-path work/native-tests
xcodebuild -project apps/native/PhotoPrepNative.xcodeproj -scheme PhotoPrepNative \
  -configuration Debug -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath work/native-build build
```

Development app: `work/native-build/Build/Products/Debug/PhotoPrep Native.app`.
It is not installed over Python. The project uses ad-hoc development signing,
not Developer ID/notarization. Internal build version 0.0.1 is not a release number.
Native CI checks build/core tests; real UI/inference/release checks remain separate.

`PhotoPrep Native.app` / `com.sirdimitry.PhotoPrep.Native` use their own sandbox
container and standard UserDefaults. No Python settings or files are migrated.
App Sandbox grants read-only access to user-selected files; there is currently no
network entitlement. Later model installation/export will need explicit, scoped
capabilities and their own verification.

## Contracts and next work

* [Verified Python behavior](BEHAVIOR.md)
* [Quality and resource acceptance](QUALITY-SAFETY.md)
* [Roadmap](ROADMAP.md)

Core sources are also a Swift package for tests. The app builds the same files;
it has no developer-Python runtime dependency. Python in Tools is exclusively for
reference benchmarks. Do not commit model weights or `.mlpackage` files.
