# Native 0.3.0 release verification

Date: 2026-11-01. Apple Silicon / macOS 14+ deployment target.

- Clean Release build, version 0.3.0 (30), arm64.
- 44 Swift tests passed; prior app-level checks: 11 retouch-state and 9 batch-export checks.
- Strict ad-hoc signature verification passed. No Developer ID/notarization claim.
- Built-in FP32 Core ML LaMa; checkpoint source, conversion notice and Apache-2.0 licence included.
- Bundle resource allowlist: AppIcon.icns, LogoGlyph.png (public UI tool artwork), Models, Licenses.
- No user/sample photos, user PNG branding, Python runtime, sessions, preferences or caches in the bundle.
- No tracked JPEG/video files or credential-pattern hits; no new-history Git blobs over 5 MB. New native PNG source is only the public Logo tool glyph.
- DMG integrity passed hdiutil verify.
- DMG SHA256: `26e2f0fda9e53d9bae4cb8962a07f869f0ccfb949bb8c8e7a7b23439a112fe2e`.

The DMG contains PhotoPrep Native.app and the Applications shortcut. GitHub distribution has a DMG and SHA256SUMS.txt; model weights stay outside source Git.

Known limits: physical gestures and full repeated-retouch memory acceptance remain incomplete; Intel/low-memory Macs have not been validated. Earlier reports document iteration-specific checks and are not a promise of complete hardware acceptance.
