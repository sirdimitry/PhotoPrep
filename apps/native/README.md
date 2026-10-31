# PhotoPrep Native

SwiftUI macOS application with a **limited native LaMa E1.5 slice**. It has a
straight-RGBA canvas (brush/eraser/undo), one LaMa FP32 pass in a separate
self-exec worker, before/after, progress/cancel/timeout, job-scoped cancellation,
and exact outside-mask / alpha preservation. Quality is close to Python on
coffee/astronaut; grass texture and a few mask pixels remain unresolved. It is
not a release. The working Python application remains in [../python/](../python/).
[Current status and limits](STATUS.md), [E1.5 report](E1.5-SESSION-INTEGRITY.md),
[E1.4 report](E1.4-HISTORY-SESSIONS.md), [E1.3 report](E1.3-QUALITY-HISTORY.md),
[E1.2 acceptance report](E1.2-ACCEPTANCE.md), [E1.1 report](E1.1-QUALITY-STABILITY.md),
[E1 report](E1-LAMA-WORKER.md), and [E0 report](E0-LAMA-COREML.md).

## Build and test

Requires Xcode with Swift 6+, deployment target macOS 14. No external Swift packages.
Use the installed Xcode via a per-command DEVELOPER_DIR if necessary; do not change
the user's global toolchain. From the repository root:

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  swift test --package-path apps/native --scratch-path work/native-tests
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild -project apps/native/PhotoPrepNative.xcodeproj -scheme PhotoPrepNative \
  -configuration Debug -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath work/e1.5-build build CODE_SIGNING_ALLOWED=NO
```

The app target has a build phase that copies the compiled model from
`PHOTOPREP_LAMA_MODEL` or, by default, from
`../../../e0-data/work/e0/models/LaMa-fp32.mlmodelc` into
`Contents/Resources/Models/LaMa-fp32.mlmodelc`. The model is not in Git; without
it the app builds but reports `model_missing` at retouch time. The build script
is not a sandbox bypass of the running app: App Sandbox remains enabled for the
app and its self-exec worker.

End-to-end diagnostics (signed ad-hoc app; no Python):

```bash
"PhotoPrep Native.app/Contents/MacOS/PhotoPrep Native" --photoprep-e1-selftest
"PhotoPrep Native.app/Contents/MacOS/PhotoPrep Native" --photoprep-e1-timeout-selftest
"PhotoPrep Native.app/Contents/MacOS/PhotoPrep Native" --photoprep-e1-crash-selftest
"PhotoPrep Native.app/Contents/MacOS/PhotoPrep Native" --photoprep-e1-cancel-selftest
PHOTOPREP_E1_FILE="<container>/real-coffee.png" \
  "PhotoPrep Native.app/Contents/MacOS/PhotoPrep Native" --photoprep-e1-file-selftest
```

The file self-test decodes a permitted real photo through the same
straight-RGBA decoder, runs the worker on three synthetic edge-mask strokes and
writes `<name>.native.png`; it prints outside/alpha changes. Use files inside the
app container (or otherwise accessible under App Sandbox), not `/tmp`.

Use `PHOTOPREP_E1_WIDTH` / `PHOTOPREP_E1_HEIGHT` to exercise 1024×768,
4000×3000 and 8000×5000 synthetic sources.

Development app: `work/e1.5-build/Build/Products/Debug/PhotoPrep Native.app`.
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
* [E1.5 session integrity report](E1.5-SESSION-INTEGRITY.md)
* [E1.4 history/session report](E1.4-HISTORY-SESSIONS.md)
* [E1.3 quality/history report](E1.3-QUALITY-HISTORY.md)
* [E1.2 acceptance report](E1.2-ACCEPTANCE.md)
* [E1.1 quality/stability report](E1.1-QUALITY-STABILITY.md)
* [E1 worker/UI report](E1-LAMA-WORKER.md)
* [E0 conversion/parity report](E0-LAMA-COREML.md)

Core sources are also a Swift package for tests. The app builds the same files;
it has no developer-Python runtime dependency. Python in Tools is exclusively for
reference benchmarks. Do not commit model weights or `.mlpackage` files.
