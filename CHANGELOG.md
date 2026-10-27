# Changelog

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
