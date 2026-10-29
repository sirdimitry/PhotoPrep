# PhotoPrep Native

Primary future development direction: a native macOS application using SwiftUI
and Core ML. **Status: planning only; no Swift implementation, Xcode project or
native release is included in v0.2.0.**

Основное будущее направление — нативное приложение SwiftUI + Core ML.
Сейчас здесь план разработки; рабочая версия находится в [../python/](../python/).

Follow the [staged roadmap and acceptance criteria](ROADMAP.md). Implement in
this directory when migration work is authorized. Preserve the Python
application as the reference and supported parallel product.

Proposed native identity: `PhotoPrep Native.app`, bundle identifier
`com.sirdimitry.PhotoPrep.Native`, artifact `PhotoPrep-Native-<version>-macos-arm64.dmg`.
Python retains `PhotoPrep.app` / `com.sirdimitry.PhotoPrep` and its existing artifact
names. Native preferences, caches and logs must have separate storage; never
silently migrate, replace or delete Python user data.
