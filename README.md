<div align="right">
  <a href="README.ru.md"><img src="https://img.shields.io/badge/Русский-Read%20in%20Russian-FACC15?style=for-the-badge&labelColor=17191d" alt="Читать на русском"></a>
</div>

<p align="center">
  <img src="assets/app-icon.png" width="104" alt="PhotoPrep app icon"><br>
  <strong style="font-size:26px">PhotoPrep</strong><br>
  <i>Clean photos for real work.</i>
</p>

![PhotoPrep — AI cleanup, cropping, branding and batch workflows](assets/github-banner.png)

<p align="center">
  <img alt="Release" src="https://img.shields.io/badge/version-0.1.0--alpha.16-FACC15?style=flat-square&labelColor=202227">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-33373d?style=flat-square">
  <img alt="Language" src="https://img.shields.io/badge/UI-English%20%2B%20Русский-33373d?style=flat-square">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-33373d?style=flat-square"></a>
</p>

## What is PhotoPrep?

**PhotoPrep** is a free, local-first photo preparation app for macOS. Its goal is to simplify repetitive website-image work: mask and remove unwanted logos with local inpainting models, crop to a consistent frame, optionally add your own brand mark, then export clean files without hidden metadata.

**Current status: early alpha / Stage 6.** The present build is a **working desktop workspace**, with an initial local AI preview. Only the features marked *Available now* below are implemented. No external image upload is performed.

### Features

| Feature | Status |
|:--|:--|
| Open individual photos or an image folder; photo filmstrip | ✅ Available now |
| Save/open a local workspace, remember per-photo zoom/pan | ✅ Available now |
| Undo/redo photo imports and removals; previous/next navigation | ✅ Available now |
| Dark/light appearance with yellow accents | ✅ Available now |
| English/Russian UI, switchable in Preferences | ✅ Available now |
| Zoom with mouse wheel, drag to pan, 100%, Fit view | ✅ Available now |
| Default export preset **1136 × 710**, editable in Advanced Preferences | ✅ Available now |
| Always-visible yellow output outline, output-pixel rulers and subtle checkerboard canvas | ✅ Available now |
| Paint and erase a mask, preview it over the photo | ✅ Available now |
| Local LaMa / MI-GAN removal preview, mask-only compositing, Before/After and cancellation | ✅ Available now |
| Verified LaMa / MI-GAN catalogue; select, download, check, remove and reinstall | ✅ Available now |
| Fixed output frame; pan/zoom the photo underneath, fill and center controls | ✅ Available now |
| Remember a PNG logo; drag, resize, adjust opacity, apply to all photos | ✅ Available now |
| Current/batch JPEG / PNG export; quality control, metadata removal, cancellation | ✅ Available now |

### Get it

**[Download v0.1.0-alpha.16 for macOS Apple Silicon](https://github.com/sirdimitry/PhotoPrep/releases/tag/v0.1.0-alpha.16)** — DMG and SHA256 checksum. Requires **macOS 14+**; Python is bundled. Drag PhotoPrep into Applications.

This early alpha is **ad-hoc signed and not notarized**, so macOS may display a security warning. Verified on macOS 27.2 / Apple Silicon; Intel and other macOS versions have not been tested. See [verified changes](CHANGELOG.md).

To try the source version on **macOS (Apple Silicon)**:

```bash
git clone https://github.com/sirdimitry/PhotoPrep.git
cd PhotoPrep
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m photoprep
```

Requires **Python 3.11+** and installs **PySide6**. The application does not download model weights at this stage.

### Interface shortcuts

| Action | Shortcut |
|:--|:--|
| Open photos | `⌘ O` |
| Open folder | `⌘ Shift O` |
| Open / save workspace | `⌘ ⌥ O` / `⌘ S` |
| Previous / next photo | `←` / `→` |
| Remove from workspace | `Delete` |
| Undo / redo collection changes | `⌘ Z` / `⌘ Shift Z` |
| Zoom | Mouse wheel / trackpad scroll, or toolbar `+ / −` |
| Pan | Select tool (`V`), or hold `Space` while using another tool |
| Mask brush / eraser / crop | `B` / `E` / `C` |
| Logo tool / Export | `L` / `⌘ Shift E` |
| Change brush size | `[` / `]`, or the brush slider |
| Fit photo in view | `⌘ 0` |
| Actual pixels (100%) | `⌘ 1` |

Workspace files (`.photoprep.json`) store local image paths and viewing positions, not image copies. Missing sources are reported when reopening; removing a photo from the workspace keeps its original file. Workspace history covers adding/removing photos, mask strokes, removal passes, crop plans and output dimensions. Originals remain read-only. Workspaces with templates use session format 6; separate logos use format 5, storing a relative PNG path and output-relative placement. Formats 1/2/3/4/5 remain readable. Without a logo, mixed-model recipes use format 4, LaMa-only recipes format 3 and basic workspaces format 2. Older apps cannot open newer session formats.

Tool controls live in the existing inspector, zoom controls sit above the filmstrip, and a shortened photo filename appears beside the app name. Switching tools does not reduce the photo viewport. The output frame stays fixed: drag the photo and scroll to zoom it beneath the frame; output dimensions change only in Settings.

Paint a mask, then choose **Remove selected area** in the inspector. Choose **Preferences → Models** to select LaMa (208.0 MB) or MI-GAN (28.1 MB). Download, check, remove and reinstall each model, or let missing models download on first processing. Downloads use pinned Hugging Face revisions, HTTPS and SHA256 verification. A cancelled reinstall preserves the installed file. Photos never leave the Mac. Processing runs in a cancellable child process on the CPU; use **Before / After** or the compare icon to switch views. After each successful pass the current mask clears. Paint over the processed image to remove remaining artifacts; each new pass starts from the previous result. Clear mask affects only the next selection. Undo/redo also covers successful removal passes.

AI results are temporary previews, limited to images up to 40 megapixels. A 512 × 512 context region is inferred and blended only inside the original full-resolution mask; unmasked pixels and alpha remain unchanged. Results depend on the scene and selection. Removal masks are saved in order. After reopening, **Restore retouch** rebuilds the accumulated result; previews evicted from memory can be restored the same way. Up to 100 removal passes are supported per photo. Each pass retains its model, so changing the active model does not change earlier retouch. Restoring a recipe downloads any missing models it needs, then loads one model at a time. Export applies the crop frame to exact output dimensions. Settings use two language buttons with immediate dialog translation and padded numeric fields.

### Roadmap

- **Stage 0** — brand identity, app icon, GitHub banner.
- **Stage 1** — desktop UI, photo import/preview, thumbnails, preferences, bilingual interface. Complete.
- **Stage 2** — workspace sessions, collection history, background photo decoding and bounded cache. Complete.
- **Stage 3** — mask painting, eraser, fixed output frame and edit history. Complete.
- **Stage 4** — local inpainting, iterative retouch and masked-only compositing. Complete.
- **Stage 5** — curated model catalogue and validated downloads from Hugging Face. Complete.
- **Stage 6** — PNG logo placement, sequential batch output and metadata stripping. Complete.
- **Stage 7** — performance, macOS packaging and release testing.

### Privacy and principles

- **Local-first:** photo editing and AI inference are designed to stay on your Mac.
- **Non-destructive:** originals are never overwritten. Local temporary mask/result files are cleaned after processing or cancellation.
- **Precise control:** inpainting results are limited to user-approved masks.
- **Honest status:** download-ready models and finished exports will not be advertised until implemented.

### Contributing & feedback

Found a bug or have a suggestion? [Open an issue](https://github.com/sirdimitry/PhotoPrep/issues). This project is **free** and open source under the MIT license.

If you like the idea, please **⭐ star the repository** to support further development.

---

<p align="center"><strong>PhotoPrep</strong> · Made for real, repeatable image work.</p>

Model attribution and dependency notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Logo and export

Use the logo tool (`L`) to choose a PNG, reuse the last logo, drag it within the
output frame, adjust size/opacity or apply its placement to every photo. Undo/redo
covers logo changes. Before/After compares the original with the edited view.
Choose **Folder…** in the logo inspector to connect a local PNG template folder.
Horizontal 16:9 templates with left placement are listed first, followed by right
placement; other templates remain available. The app detects transparent layout
canvases and keeps the visible mark's relative width and edge offsets when the
output frame changes. Its proportions stay intact. **Separate logo** mode accepts
a standalone transparent PNG; both modes allow position, size and opacity edits.
Your output dimensions stay unchanged when choosing a template. Local template
paths stay in preferences/workspaces; the artwork is not copied into the app or
repository.

Logo PNGs are limited to 32 megapixels and 32 MB; missing assets must be relinked.

Choose **Export** (`⌘ Shift E`), current photo or all photos, JPEG/PNG
and JPEG quality. Output uses the exact frame dimensions, such as 1136 × 710.
Applied retouch is restored using each pass's original model; pending masks must
be applied or cleared first. Source/asset changes during export are reported.

Files are named `original-logo.jpg` / `.png`; batches use `-logo01`, `-logo02`,
and so on. Occupied names are skipped by selecting the next free number. Atomic exclusive commits never replace existing files or originals.
Export runs sequentially in a child process, keeps one decoded logo/model at a
time and can be cancelled. Completed files remain; own temporary files are cleaned.

Output is 8-bit JPEG or RGBA PNG in sRGB. JPEG flattens transparency on white.
Fresh encoders omit source EXIF/GPS, XMP, comments, embedded profiles and source
text. Colour is converted to sRGB before profiles are stripped. Source files stay
read-only. Inputs and output dimensions are limited to 40 megapixels per image.

### Export locations and comparison

Export writes next to each original, without creating a destination subfolder.
A single image uses `photo-logo.jpg` (or `.png`). A batch starts at
`photo-logo01.jpg`, `other-logo02.jpg`, and so on. If a name exists, the next
available number is used; existing files are never replaced. Photos from different
folders are saved in their respective source folders.

The left-side Before/After button is the single comparison control. It becomes
available for masks, crop plans, retouch, logos and output-size changes. Before
shows original pixels, hides mask/logo overlays and uses the initial crop guide;
After restores the planned edits. Switching views does not discard edits.

### Workflow and About

New imports start with the removal mask tool. The left tools follow the workflow:
mask, mask eraser, fixed-frame crop, pan, own logo, comparison. Crop keeps the
configured output dimensions while the image moves and scales underneath.
The header shows the full filename whenever it fits, using the space up to Open
photos; longer names retain the beginning and end with `...` in the middle.

Preferences → About includes the full MIT License, a logo-use notice and
[@sirdimitry on X](https://x.com/sirdimitry). Third-party logos and branded templates
are not bundled. Users choose their own artwork and are responsible for permission
to use it; PhotoPrep's MIT licence grants no rights to third-party marks.

### Logos across a collection

Logo controls reflect the current photo. If no logo is applied, detailed placement
controls are hidden and the template list has no active selection. **Enable logo
on all photos** uses the current or last configured mark, enables it throughout the
current collection and refreshes the visible photo immediately, preserving retouch
and crop plans. The operation is one undo step.

Export defaults to **all photos** when a collection contains multiple images.
Choose JPEG or PNG once for the entire selection; the current-photo option remains
available. Files still save beside their originals with collision-safe `-logo` names.

### Optional SDXL Inpainting

Preferences → Models offers SDXL Inpainting alongside LaMa and MI-GAN. The card
explains before download: if smears remain, refine the mask and retry a lightweight
model, or try SDXL for complex backgrounds. SDXL is slower and results vary.
Its pinned FP16 download contains 18 files totaling **6,941,218,469 bytes (6.94 GB)**.
Weights download separately; the full app bundles the required runtime libraries.

SDXL uses the Apple Silicon GPU via Metal, a 1024 × 1024 context, 20 sampling steps,
a fixed background-removal prompt and a fixed seed. Processing remains local;
only the exact original mask is composited, preserving all unmasked RGBA pixels.
Passes can mix SDXL, LaMa and MI-GAN. SDXL recipes use session format 7; formats
1–6 remain readable. Models load one at a time during restore/export.

A test pass on M3 Max / 36 GB took about 56 seconds including model verification
and loading. This is one test, not a speed or quality guarantee. Memory-heavy apps
may need to be closed. Source installs may use `pip install -e ".[dev,sdxl]"` in the
existing environment; no additional Python version is required. Model terms are
CreativeML Open RAIL++-M, separate from PhotoPrep's MIT licence.

### Private diagnostics

A local service log records starts, model operations, worker failures and network
errors. It has no GUI entry and no upload mechanism. The single log resets when
the next write would exceed 10 MiB; credentials and signed URL queries are redacted.
SDXL downloads retry transient failures and resume partial files within the active
operation. A failed/cancelled replacement preserves the installed pinned model.

### Use existing weights

Each model card has **Choose from disk…**. Pick the supported ONNX file for
LaMa/MI-GAN or the complete official FP16 folder for SDXL. Only the pinned, tested
inpainting versions are accepted after size/SHA256 verification; arbitrary text-to-
image checkpoints, FP32 variants and incomplete folders are rejected. Existing
files stay unchanged. Same-volume files can be linked without a second physical
copy; other volumes are copied into private application storage.

Ordinary downloads first verify installed weights, then check remembered local
sources and the exact official Hub cache. Compatible existing weights are reused
without a network request. A fresh download is forced only by explicit Reinstall.
