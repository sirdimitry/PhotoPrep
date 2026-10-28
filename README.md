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
  <img alt="Release" src="https://img.shields.io/badge/version-0.1.0--alpha.7-FACC15?style=flat-square&labelColor=202227">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-33373d?style=flat-square">
  <img alt="Language" src="https://img.shields.io/badge/UI-English%20%2B%20Русский-33373d?style=flat-square">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-33373d?style=flat-square"></a>
</p>

## What is PhotoPrep?

**PhotoPrep** is a free, local-first photo preparation app for macOS. Its goal is to simplify repetitive website-image work: mask and remove unwanted logos with local inpainting models, crop to a consistent frame, optionally add your own brand mark, then export clean files without hidden metadata.

**Current status: early alpha / Stage 4.** The present build is a **working desktop workspace**, with an initial local AI preview. Only the features marked *Available now* below are implemented. No external image upload is performed.

### Features

| Feature | Status |
|:--|:--|
| Open individual photos or an image folder; photo filmstrip | ✅ Available now |
| Save/open a local workspace, remember per-photo zoom/pan | ✅ Available now |
| Undo/redo photo imports and removals; previous/next navigation | ✅ Available now |
| Dark/light appearance with yellow accents | ✅ Available now |
| English/Russian UI, switchable in Preferences | ✅ Available now |
| Zoom with mouse wheel, drag to pan, 100%, Fit view | ✅ Available now |
| Default export preset **1136 × 710**, editable in Advanced Preferences | ✅ Saved with workspace; export pending |
| Always-visible yellow output outline, output-pixel rulers and subtle checkerboard canvas | ✅ Available now |
| Paint and erase a mask, preview it over the photo | ✅ Available now |
| Local LaMa removal preview, mask-only compositing, Before/After and cancellation | ✅ Available now |
| Select and download compatible compact AI models | 🛠 Planned |
| Fixed output frame; pan/zoom the photo underneath, fill and center controls | ✅ Saved with workspace; export pending |
| Add a remembered user logo | 🛠 Planned |
| Batch JPEG / PNG export, remove EXIF and other metadata | 🛠 Planned |

### Get it

**[Download v0.1.0-alpha.7 for macOS Apple Silicon](https://github.com/sirdimitry/PhotoPrep/releases/tag/v0.1.0-alpha.7)** — DMG and SHA256 checksum. Requires **macOS 14+**; Python is bundled. Drag PhotoPrep into Applications.

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
| Change brush size | `[` / `]`, or the brush slider |
| Fit photo in view | `⌘ 0` |
| Actual pixels (100%) | `⌘ 1` |

Workspace files (`.photoprep.json`) store local image paths and viewing positions, not image copies. Missing sources are reported when reopening; removing a photo from the workspace keeps its original file. Workspace history covers adding/removing photos, mask strokes, removal passes, crop plans and output dimensions. Originals remain read-only. Workspaces with removal passes use session format 3; earlier formats 1/2 remain readable. Alpha.6 and older apps cannot open format 3. Workspaces without removal passes retain format 2.

Tool controls live in the existing inspector, zoom controls sit above the filmstrip, and a shortened photo filename appears beside the app name. Switching tools does not reduce the photo viewport. The output frame stays fixed: drag the photo and scroll to zoom it beneath the frame; output dimensions change only in Settings.

Paint a mask, then choose **Remove selected area** in the inspector. The first run downloads the pinned 208 MB LaMa model from Hugging Face with HTTPS and SHA256 verification. Photos never leave the Mac. Processing runs in a cancellable child process on the CPU; use **Before / After** or the compare icon to switch views. After each successful pass the current mask clears. Paint over the processed image to remove remaining artifacts; each new pass starts from the previous result. Clear mask affects only the next selection. Undo/redo also covers successful removal passes.

AI results are temporary previews, limited to images up to 40 megapixels. A 512 × 512 context region is inferred and blended only inside the original full-resolution mask; unmasked pixels and alpha remain unchanged. Results depend on the scene and selection. Removal masks are saved in order. After reopening, **Restore retouch** rebuilds the accumulated result; previews evicted from memory can be restored the same way. Up to 100 removal passes are supported per photo. Crop frames remain saved plans; image export is not implemented. Settings use two language buttons with immediate dialog translation and padded numeric fields.

### Roadmap

- **Stage 0** — brand identity, app icon, GitHub banner.
- **Stage 1** — desktop UI, photo import/preview, thumbnails, preferences, bilingual interface. Complete.
- **Stage 2** — workspace sessions, collection history, background photo decoding and bounded cache. Complete.
- **Stage 3** — mask painting, eraser, fixed output frame and edit history. Complete.
- **Stage 4** — LaMa-based local inpainting; preview and masked-only compositing. **Current**.
- **Stage 5** — curated model catalog and validated downloads from Hugging Face.
- **Stage 6** — new logo placement, optimized batch output and metadata stripping.
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
