# Development

Current working Python release: **0.2.0**, based on **0.1.0-alpha.18**.
The main future development direction is [PhotoPrep Native](apps/native/README.md).
Native implementation is not part of v0.2.0; follow its [roadmap](apps/native/ROADMAP.md).

## Layout and identities

- `apps/native/`: planned SwiftUI/Core ML application and staged acceptance gates.
- `apps/python/photoprep/`: complete maintained Python/PySide6 application.
- `apps/python/tests/`, `assets/`, `scripts/`: Python tests, approved artwork and packaging.
- Root documentation, licence, third-party notices and `.github/`: shared project records.
- Ignored `.venv/`, `models/`, `work/`, `build/`, `dist/`: local data; never publish them wholesale.

Python keeps `PhotoPrep.app` / `com.sirdimitry.PhotoPrep`. Native must have its own
app name, identifier, preferences and distribution artifacts. Neither version may
silently change the other's data. Previous root-level Python commands now run from
`apps/python`; Git history retains the original paths and releases.

## Run and test Python

Python 3.11+ on macOS. The existing packaging target is Apple Silicon, macOS 14+.

```bash
cd apps/python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-deps -e .
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m photoprep
```

Tests use temporary settings and generated images. Do not run personal sessions
as fixtures. An existing compatible environment can be selected via `PYTHON` for
packaging; run from `apps/python` to import this checkout's source.

## Build and verify the Python DMG

```bash
PYTHON="$PWD/.venv/bin/python" bash scripts/build_macos.sh
open dist/PhotoPrep.app
hdiutil verify dist/PhotoPrep-0.2.0-macos-arm64.dmg
(cd dist && shasum -a 256 -c PhotoPrep-0.2.0-macos-arm64.dmg.sha256)
codesign --verify --deep --strict dist/PhotoPrep.app
```

The script refuses to overwrite existing app/DMG/checksum outputs. Fresh build
and staging directories remain under `work/` for inspection. Preserve previous
outputs separately before a subsequent build; never clean another person's files.
It generates icons, bundles dependencies and selected artwork/licences, sets bundle
versions and creates the DMG plus a portable checksum. The canonical build entry
point is the script; generated PyInstaller specs are ignored build products.
The app is **ad-hoc signed, not Developer ID signed or notarized**. Intel and
older macOS versions require their own verification.

## Application and session contract

v0.2.0 retains LaMa as default, MI-GAN and optional SDXL; Retouch/Crop/Logo/Batch,
mask-only RGBA composition, cumulative passes, cancellation, restore and undo/redo.
Session formats **1–7** remain readable. The writer selects the format required
by the content, including 7 for SDXL. The release number does not change the schema.
Session JSON contains private local paths and must not be published. Saves are
atomic with owner-only permissions; original photos remain read-only.

Weights and logos load locally. Downloaded weights use pinned revisions and
size/SHA256 validation; SDXL inference disables hub networking/telemetry. Templates,
photos, settings, sessions, logs, credentials and model weights must not enter a
release. Packaging uses an explicit UI asset list and includes model licences.

## Safe release procedure

1. Inspect status, branch, remotes, tags and version sources; record the base SHA.
   Preserve all existing work. Use an isolated checkout and `release/<version>`.
2. Align `apps/python/pyproject.toml`, `photoprep/__init__.py`, READMEs and this guide.
   Add a changelog entry without rewriting historical entries.
3. Run pytest, build with the existing script, verify signature, Info.plist,
   DMG and checksum. Smoke-test the packaged app and real model workers; record
   exactly which backends and flows ran, including any limitations.
4. Inspect bundled source identity, allowed assets, licences, private paths and
   credentials; inspect the mounted DMG as well as the build directory.
5. Commit and push the release branch normally. If review is required, open a PR
   and wait for approval before merge. Never force push or move existing tags.
6. Only after successful gates, create a new annotated `v<version>` tag on the
   verified commit, push that tag and publish its DMG and SHA256. v0.2.0 is a
   regular Python release. Do not replace assets in existing releases.
7. Verify the remote tag/commit, release status, asset names/sizes/digest and CI.
   Keep detailed local validation logs; publish only the intended artifacts.

Python CI uses `apps/python` as its working directory and runs on main, release
branches and tags. Manual dispatch also builds artifacts. A native CI job and
`native-v<version>` tags will be introduced when that implementation exists.
