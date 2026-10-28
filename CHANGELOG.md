# Changelog

## v0.1.0-alpha.9 — 2026-10-28

- Report first-use download failures as model-download errors, including the
  automatic download path used by inference. Preserve existing installed weights.

Validation: 69 tests passed offscreen and with native macOS rendering, including
  an offline download failure without replacing the installed model.

## v0.1.0-alpha.8 — 2026-10-28

Stage 5: verified model catalogue and management.

- Add a compact Models tab in bilingual Preferences with LaMa (208.0 MB) and
  MI-GAN (28.1 MB), installed size, full verification, download, cancel, remove
  and atomic reinstall. Save commits model selection; file operations act immediately.
- Keep installed files on interrupted reinstall, use model locks and process-specific
  partial files so cancelling one process cannot remove another process download.
- Adapt the MIT-licensed MI-GAN ONNX pipeline to the existing mask-only compositor.
  Reuse the current Python, ONNX Runtime and dependencies; include the weights licence.
- Record each pass model and preserve accumulated retouch when switching models.
  Mixed recipes use session format 4; formats 1/2/3 remain readable. Restore with the
  original model per pass, downloading missing weights and loading one model at a time.
- Keep model files outside the repository/package and downloads outside the GUI process.

Validation: 68 tests passed offscreen and with native macOS rendering. Native GUI
verification exercised delete/download/verify/cancel-reinstall and persisted selection.
A real LaMa → MI-GAN recipe restored with exactly matching pixels and unchanged source
file. On the generated test image the passes took about 6.3s and 0.6s respectively;
these timings are not general performance guarantees. Image export remains pending.

## v0.1.0-alpha.7 — 2026-10-28

- Accumulate removal passes: draw on the processed image and apply a new mask to
  the last result. Keep previous retouch outside the new selection unchanged.
- Clear only the pending mask after success, return to the brush, and keep the
  previous result and pending selection after cancellation or failure.
- Compare the untouched original with the accumulated result. Clear mask affects
  only the current selection; successful passes participate in undo/redo.
- Save ordered removal masks in session format 3; restore all passes after
  reopening or preview-cache eviction. Formats 1/2 remain readable; older apps
  cannot open format 3. Limit recipes to 100 passes and the existing point budget.
- Keep staged base images private and clean them with other temporary job files.

Validation: 59 tests passed with native macOS rendering. Real LaMa GUI smoke
verification completed two accumulated passes, kept every pixel outside each new
mask identical to the previous result, and restored the saved two-pass recipe
with exactly matching pixels. Original source hashes stayed unchanged.

## v0.1.0-alpha.6 — 2026-10-28

Stage 4: initial local LaMa inpainting preview.

- Add a pinned 208 MB ONNX model download over HTTPS, atomic installation and full
  SHA256 verification before inference. Bundle a certificate store for standalone Macs.
- Run inference/downloads in cancellable child processes; keep the GUI responsive,
  clean temporary masks/results, and leave source files read-only.
- Infer a 512px context region and composite only inside the original full-resolution
  mask. Preserve every unmasked RGBA pixel and the original alpha channel.
- Add compact inspector processing/cancel and Before/After controls; enable the compare
  rail button after processing. Invalidate stale previews when source or mask changes.
- Bound preview memory, support up to 40MP, report failures in RU/EN, and retry corrupt
  model downloads. Keep model weights, private jobs and all photos out of the package.
- Add dependency/model notices; reuse the existing Python and project virtual environment.

Validation: 51 tests passed offscreen and with native macOS rendering. Real LaMa
removed a generated mark, with all pixels outside the mask unchanged. Processing
through the native GUI completed in about 6.4 seconds on the development Mac.
Previews are temporary and not stored in sessions; image export remains pending.

## v0.1.0-alpha.5 — 2026-10-27

- Show the yellow output outline in every editing tool, including brush and eraser.
- Add thin top/left rulers in output pixels, with exact edges such as 1136 and 710.
  Rulers follow the planned crop during viewing and the fixed frame during cropping.
- Paint a subtle checkerboard outside the image, with saved dark/light appearance
  choices in bilingual Preferences. Recolour controls and icons for each theme.
- Draw thumbnail selection borders around images only; place filenames in a separate
  row below, with enough room even when the horizontal scrollbar is visible.

Validation: 45 tests passed offscreen and in a native macOS GUI session, including
rendered yellow borders in all tools, ruler mapping, fixed-frame zoom, checkerboard
colours, thumbnail caption clearance and appearance save/cancel/restart.
Original images remain read-only; AI inference and image export remain pending.

## v0.1.0-alpha.4 — 2026-10-27

Stage 3: mask tools, a fixed output frame and compact controls.

- Fix macOS Preferences with separate language choices, complete immediate
  translation, validated numeric fields and visible inner padding.
- Move tool options into the existing inspector and zoom controls above the
  filmstrip. Remove both toolbars above the image; switching tools preserves
  the full viewport height. Compact buttons and the top header; show a shortened
  two-word photo filename with the full name on hover.
- Paint/erase per-photo masks, change brush size, show/clear overlays and pan
  temporarily with Space. Keep original files read-only.
- Keep the output frame fixed in the viewport. Drag and zoom the photograph
  underneath it; preserve the output dimensions, constrain the image to fill
  the frame, and provide compact Fill/Center controls.
- Undo/redo mask gestures, crop positioning/zoom, clearing and output-size changes.
- Store normalized mask/crop plans and output dimensions in session format 2.
  Format 1 remains readable; older app versions cannot open format 2.

Validation: 43 tests passed offscreen and in a macOS GUI session with existing
Python/PySide6 dependencies. Tests cover bilingual layout, unchanged viewport
height, fixed-frame pan/zoom, mask precision, source integrity, history and sessions.
AI inference and image export remain unavailable.

## v0.1.0-alpha.3 — 2026-10-27

Stage 2: persistent workspaces and photo navigation.

- Save/open a local `.photoprep.json` workspace with relative image paths,
  current selection, and each photo's zoom/pan. Source pixels are never copied
  into the session or modified.
- Undo/redo imports and removals (up to 100 collection changes); removal keeps
  the original file. Previous/next buttons, keyboard navigation and native
  File/Edit/View menus are available in English and Russian.
- Decode previews on two background workers; ignore late results from an older
  selection and bound the decoded-image cache to 128 MiB.
- Display 100% using physical pixels on Retina screens and preserve viewing
  positions when navigating or reopening a workspace.
- Ask to save unsaved workspaces; preserve existing session files on failed
  saves and report missing source photos. Session files use owner-only access
  and are excluded from Git.
- Bundle only a named list of UI artwork, excluding workspaces and working files.

Validation: 29 automated tests passed both offscreen and in a macOS GUI session
with the existing Python 3.12.4 / PySide6 6.12.0 environment. No new system Python
or dependencies were installed for Stage 2. The packaged app opened a generated
workspace, navigated photos, retained 100% zoom, undid removal via Cmd+Z and saved
via Cmd+S. DMG integrity, the enclosed app signature and runtime asset allowlist
were verified; local sessions were absent from the bundle.

AI cleanup, mask painting, crop, logo placement and image export remain unavailable.

## v0.1.0-alpha.2 — 2026-10-27

- Restore the original alpha.1 Git history and retain the approved black/yellow artwork.
- Translate the status bar after changing language and localize Save/Cancel.
- Recover safely from invalid stored output dimensions.
- Show EXIF-oriented photo dimensions consistently with the preview.
- Remove label background blocks and keep the alpha badge compact.
- Package a versioned Apple Silicon app and DMG, with Applications shortcut and SHA256.
- Add regression checks for import deduplication, zoom, preferences, languages,
  original-file integrity and EXIF rotation.

Validation: 10 tests passed with PySide6 6.12.0 both offscreen and in a macOS
GUI session. The standalone app launched and opened an EXIF-rotated JPEG with
the correct dimensions; the 100% control worked. DMG integrity and the enclosed
application's ad-hoc signature were verified on macOS 27.2 / Apple Silicon.

Limits: Stage 1 is a photo viewer/workspace. AI cleanup, masking, crop, logo
placement and export remain unavailable. The app is not notarized; macOS 14+
is required by the bundled Qt build, and only the current Mac was tested.

## v0.1.0-alpha.1

Original Stage 1 source scaffold, commit `6586357`.
