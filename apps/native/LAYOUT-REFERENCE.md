# Native layout — reference recomposition

**Branch:** `v1/layout-reference`, commit `8c4042c` (layout). Previous candidate is unchanged on `v1/native-usable`.
**Build:** `work/PhotoPrep-Native-v1-layout-reference.app` (ad-hoc, 202 MiB).

## Что изменено

* compact top header: PhotoPrep Native, version, current file name, Open Photos, Open Folder, Export, appearance settings;
* narrow 54 pt icon rail: brush, eraser, crop, move, logo, before/after; active tool yellow;
* large centered canvas with checkerboard, horizontal/vertical rulers and visible output frame;
* right “Параметры” panel is context-sensitive: brush settings/actions/progress/cancel, crop actions, logo controls, before/after, export; no simultaneous settings for all tools;
* horizontal filmstrip with thumbnails, active outline, count, zoom controls, previous/next and close;
* compact status bar with photo/size/output/phase/read-only/errors;
* left vertical photo list removed.

Tool selection changes only the right panel content; center canvas uses the same fixed area. Logo tool screenshot confirms image/frame position remains.

## Проверки

* 36 Swift tests pass.
* UI compilation and signed app; model inside bundle.
* Open synthetic `layout-one.png` (400×300), displayed in new canvas.
* Normal and reduced window screenshots:
  * `work/layout-reference-artifacts/layout-normal.png`
  * `work/layout-reference-artifacts/layout-reduced.png` (900×620)
  * `work/layout-reference-artifacts/layout-logo-tool.png`
* No clipped header buttons at reduced width; canvas and filmstrip remain inside window; right panel fixed width; status visible.
* Existing actions retained: import photos/folder, retouch, undo/clear/pass undo, crop, logo, export, before/after, session/export menus.

## Ограничения / замечания

* Move tool is a UI entry with an explanatory hint; no new image-pan engine was added. Crop mode provides pan/scroll.
* Zoom controls scale the canvas view; they do not introduce a new viewport model.
* This is a layout build, not a new functional acceptance. The earlier v1 candidate and its session/export limitations remain.
* No public release; no model/FP16/XPC changes.

## Run

```bash
open "/Users/sirdimitry/Documents/ChatGPT/PhotoPrep/release-0.2.0/work/PhotoPrep-Native-v1-layout-reference.app"
```
