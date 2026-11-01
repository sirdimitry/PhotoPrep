# PhotoPrep Native

[Русский](README.ru.md)

Local photo preparation for macOS: remove an old logo, compose a fixed output frame, add your own PNG branding, and export every open photo.

**[Download PhotoPrep Native 0.3.0](https://github.com/sirdimitry/PhotoPrep/releases/tag/v0.3.0)** · [Latest release](https://github.com/sirdimitry/PhotoPrep/releases/latest)

## Requirements and installation

Apple Silicon Mac, macOS 14 or later. Intel is not supported by this DMG. Drag **PhotoPrep Native.app** from the DMG to **Applications**. Quit an older running copy before opening the new one.

The app is ad-hoc signed, not Developer ID signed or notarized. macOS may prevent opening it; this release does not claim Gatekeeper/notarization approval.

## Workflow

1. Open photos or a folder. Originals are never overwritten.
2. Paint the old logo with the mask brush; use the eraser, undo stroke or clear mask to refine it. Run local LaMa retouch; additional passes and pass undo are available.
3. Move the photo under the fixed yellow frame. Wheel, vertical two-finger scroll and pinch resize the photo; **Fill** restores full coverage. Crop edits apply immediately. Export is blocked if there are empty areas inside the frame.
4. Choose your own PNG in **Logo**, drag and scale it. Use **Apply to all photos** for the entire collection.
5. Choose PNG/JPEG and **Export all (N)**. The result reports saved/total and individual failures. Existing files are not overwritten.

The FP32 Core ML LaMa model is included: no Python runtime or first-run model download is needed. Photos, masks and logos are processed locally. The DMG contains no sample photographs or customer logos. Application artwork is part of the UI.

Workspaces are temporary. Export saves the result; photos and retouch history are not restored after quitting. Logo preferences may be remembered locally. PNG alpha is retained; JPEG is flattened on white. Export removes EXIF and other source metadata and uses area filtering for downscaling.

## Verification and limits

44 Swift tests plus synthetic app-level checks for retaining retouch results and exporting four files passed locally. Physical trackpad gestures, Intel and low-memory Macs have not been comprehensively validated. Retouch quality depends on the image and mask; the full memory stress acceptance is still open.

[Native build and diagnostics](apps/native/README.md) · [Development](DEVELOPMENT.md) · [Changes](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

`apps/python/` is the archived Python implementation. Its source and previous GitHub releases remain available; it is not included in this native DMG. The earlier Python guide is [here](apps/python/README.md).

[MIT license](LICENSE). Bundled LaMa retains Apache-2.0 terms and attribution.
