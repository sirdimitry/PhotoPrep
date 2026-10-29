# PhotoPrep

[Русский](README.ru.md)

![PhotoPrep](apps/python/assets/github-banner.png)

PhotoPrep prepares photos locally on your Mac: Retouch → Crop → Logo → Batch export.
Original photos stay unchanged and are never uploaded for processing.

## PhotoPrep Native — the main development direction

The future macOS application will use **SwiftUI + Core ML**. It has its own
[application directory](apps/native/README.md) and a detailed
[migration roadmap](apps/native/ROADMAP.md). Native implementation has not started
in this repository; no native download is available yet. Python v0.2.0 remains
the working application and the behavior reference throughout migration.

## Available now: PhotoPrep Python v0.2.0

**[Download the Apple Silicon DMG and SHA256](https://github.com/sirdimitry/PhotoPrep/releases/tag/v0.2.0)**

Requires macOS 14+. Python is bundled. The app is ad-hoc signed and is not
notarized. Intel and other macOS versions have not been verified.

The Python/PySide6 application retains LaMa, MI-GAN, optional SDXL, cumulative
retouch, crop, local PNG branding, JPEG/PNG batch export, RU/EN and light/dark themes.
It reads session formats 1–7. v0.2.0 packages the working alpha.18 behavior;
it does not introduce a new session format or a native runtime.

Read the [Python user guide](apps/python/README.md), [development guide](DEVELOPMENT.md)
and [release history](CHANGELOG.md).

## Repository layout

| Directory | Purpose | Status |
| --- | --- | --- |
| [`apps/native/`](apps/native/README.md) | Primary future SwiftUI/Core ML app | Roadmap only |
| [`apps/python/`](apps/python/README.md) | Working Python/PySide6 app, tests, assets, packaging | v0.2.0 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Build, validation and release instructions | Both directions |
| [CHANGELOG.md](CHANGELOG.md) | Additive release history | Earlier entries preserved |

Both applications belong in this repository and will coexist. Native migration
must preserve Python sources, published releases and session compatibility.
Future native builds must use a distinct app name, bundle identifier and artifact
name so both apps can be installed together without sharing preferences by accident.

[MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
