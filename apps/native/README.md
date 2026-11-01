# PhotoPrep Native 0.3.0

[User guide and download](../../README.md) · [Русское руководство](../../README.ru.md)

SwiftUI/AppKit photo preparation for Apple Silicon, macOS 14+. Core ML LaMa runs in a separate self-exec worker. The Release DMG bundles the model and licences, without Python, sample photos or user logo assets. Ad-hoc signed; not notarized.

## Build and tests

Xcode / Swift 6 required. From the repository root:

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path apps/native
PHOTOPREP_LAMA_MODEL=/path/to/LaMa-fp32.mlmodelc \
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
xcodebuild -project apps/native/PhotoPrepNative.xcodeproj -scheme PhotoPrepNative \
  -configuration Release -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath work/native-release build CODE_SIGNING_ALLOWED=NO ONLY_ACTIVE_ARCH=YES ARCHS=arm64
```

Release builds fail when the model is missing. Debug can build without it for core/UI development. The build phase packages application artwork and licence notices. Model conversion/provenance is documented in [E0](E0-LAMA-COREML.md) and [third-party notices](../../THIRD_PARTY_NOTICES.md). Model weights stay outside Git.

## Current workflow

One temporary collection; immediate crop edits; fixed output frame; mask/eraser retouch; movable PNG; apply Logo to all; batch PNG/JPEG export. No session open/save commands in the user workflow. Historical session compatibility code remains in Core.

Retouch results remain visible while editing masks and switching tools. An evicted result is restored from its recipe instead of displaying the original as a completed edit. Export snapshots all open photos and settings; one failed file does not stop the others. Hidden PNG assets do not block export. Output files are published atomically without overwriting existing files.

## Diagnostics and verification

44 Swift tests; 11 app-state checks; 9 batch-export checks. Debug flags `--photoprep-display-state-selftest` and `--photoprep-batch-export-selftest` use disposable synthetic images in an isolated test instance. Model diagnostics include `--photoprep-e1-selftest`; cancellation/timeout checks are implemented in WorkerMain.

Release logs are local under the app container's Application Support/PhotoPrep Native: `retouch-events.json` (last 100 events) and `export-report.json` (last batch). No photos are embedded in these logs.

Current verification notes: [retouch state](RETOUCH-STABLE-2026-11-01.md), [batch export](BATCH-EXPORT-2026-11-01.md), [resampling](FILL-QUALITY-2026-11-01.md). Earlier E0/E1/UI reports are historical, not statements of the latest UI.

Physical gestures, low-memory/Intel hardware and the full repeated-retouch memory acceptance remain unclosed. Do not describe an ad-hoc signature as notarization.
