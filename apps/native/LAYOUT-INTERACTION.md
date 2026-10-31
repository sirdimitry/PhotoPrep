# Layout interaction pass

**Branch:** `v1/layout-interaction`  
**Commit:** `f816ce3` (canvas transform, pan, crop frame contrast, compact bottom)  
**Build:** `work/PhotoPrep-Native-v1-layout-interaction.app` (ad-hoc, model inside).  
Previous layout build and `v1-candidate` are preserved.

## Changes

* one viewport transform for canvas/rulers/mask: `SessionView` stores fit/zoom/center per photo;
* 100% means one image pixel per backing pixel (`1 / backingScale`), Fit computes the actual fit;
* +/- and 100% preserve the viewport; image position persists through tool switches;
* Move tool pans the viewport; Space is handled by the canvas for temporary pan (view only, never changes crop recipe);
* crop mode keeps its fixed output-aspect frame; image moves/scales under it;
* normal mode output frame is drawn from the same `effectiveCrop` used by export;
* rulers are in image-pixel coordinates and follow the same transform;
* graphite surfaces, yellow tint, yellow Open Photos/Export, secondary Open Folder;
* filmstrip title/count fixed one line; status moved into the filmstrip footer so it remains visible at 900×620.

## Verified in UI

* portrait 400×600 and landscape 600×400 synthetic photos opened;
* window-only captures at 1160×760 and 900×620;
* 100% button changed image scale; Move tool drag moved the image; frame and mask followed;
* brush mask drawn on portrait;
* crop tool activated, fixed frame shown, right panel context switched without changing canvas area;
* filmstrip, count, status, zoom controls and header actions remain visible at 900×620.

Screenshots in `work/layout-interaction-artifacts/`:
`portrait-1160.png`, `portrait-900.png`, `landscape-1160.png`, `landscape-900.png`, `mask-portrait-900.png`, `crop-portrait-900.png`.

## Not verified / limitations

* Space-held temporary pan is implemented but was not separately automated (Move-tool drag is verified).
* A full export from this UI and pixel comparison of the yellow frame against that exported result were **not** completed. The frame and export share `effectiveCrop`, but this is not claimed as a UI-verified export comparison.
* Crop/logo/export/session behavior was not otherwise changed.
* No public release, no LaMa/session/engine changes.
