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
  <img alt="Release" src="https://img.shields.io/badge/version-0.1.0--alpha.2-FACC15?style=flat-square&labelColor=202227">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-33373d?style=flat-square">
  <img alt="Language" src="https://img.shields.io/badge/UI-English%20%2B%20Русский-33373d?style=flat-square">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-33373d?style=flat-square"></a>
</p>

## What is PhotoPrep?

**PhotoPrep** is a free, local-first photo preparation app for macOS. Its goal is to simplify repetitive website-image work: mask and remove unwanted logos with local inpainting models, crop to a consistent frame, optionally add your own brand mark, then export clean files without hidden metadata.

**Current status: early alpha / Stage 1.** The present build is a **working desktop workspace**, not yet an AI remover. Only the features marked *Available now* below are implemented. No external image upload is performed.

### Features

| Feature | Status |
|:--|:--|
| Open individual photos or an image folder; photo filmstrip | ✅ Available now |
| Dark graphite interface with yellow accents | ✅ Available now |
| English/Russian UI, switchable in Preferences | ✅ Available now |
| Zoom with mouse wheel, drag to pan, 100%, Fit view | ✅ Available now |
| Default export preset **1136 × 710**, editable in Advanced Preferences | ✅ Preset saved; crop/export pending |
| Paint an exact inpainting mask (brush / eraser) | 🛠 Planned |
| Local-only AI logo removal, change pixels only inside mask | 🛠 Planned |
| Select and download compatible compact AI models | 🛠 Planned |
| Interactive fixed-frame crop, wheel zoom and Fill frame | 🛠 Planned |
| Add a remembered user logo | 🛠 Planned |
| Batch JPEG / PNG export, remove EXIF and other metadata | 🛠 Planned |

### Get it

**[Download v0.1.0-alpha.2 for macOS Apple Silicon](https://github.com/sirdimitry/PhotoPrep/releases/tag/v0.1.0-alpha.2)** — DMG and SHA256 checksum. Requires **macOS 14+**; Python is bundled. Drag PhotoPrep into Applications.

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
| Zoom | Mouse wheel / trackpad scroll, or toolbar `+ / −` |
| Pan | Drag on the photo |
| Fit photo in view | `⌘ 0` |
| Actual pixels (100%) | `⌘ 1` |

### Roadmap

- **Stage 0** — brand identity, app icon, GitHub banner.
- **Stage 1** — desktop UI, photo import/preview, thumbnails, preferences, bilingual interface. **Current**.
- **Stage 2** — document state, interaction history, high-quality photo navigation.
- **Stage 3** — mask painting and crop frame tools.
- **Stage 4** — LaMa-based local inpainting; preview and masked-only compositing.
- **Stage 5** — curated model catalog and validated downloads from Hugging Face.
- **Stage 6** — new logo placement, optimized batch output and metadata stripping.
- **Stage 7** — performance, macOS packaging and release testing.

### Privacy and principles

- **Local-first:** photo editing and AI inference are designed to stay on your Mac.
- **Non-destructive:** originals are never overwritten.
- **Precise control:** inpainting results will be limited to user-approved masks.
- **Honest status:** download-ready models and finished exports will not be advertised until implemented.

### Contributing & feedback

Found a bug or have a suggestion? [Open an issue](https://github.com/sirdimitry/PhotoPrep/issues). This project is **free** and open source under the MIT license.

If you like the idea, please **⭐ star the repository** to support further development.

---

<p align="center"><strong>PhotoPrep</strong> · Made for real, repeatable image work.</p>
