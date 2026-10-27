# Development

Current version: **0.1.0-alpha.3**, Stage 2 photo workspace.
The original alpha.1 source commit is retained in Git history.

## Run and test

Use Python 3.11+ on macOS. The verified release was built on Apple Silicon
with Python 3.12.4 and PySide6 6.12.0; its minimum macOS version is 14.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-deps -e .
python -m pytest -q
python -m photoprep
```

For tests without a window server, use `QT_QPA_PLATFORM=offscreen python -m pytest -q`.
Tests use temporary settings and generated pictures; they do not overwrite personal
preferences or source photographs.

## Layout

- `photoprep/`: image metadata, workspace/history, session storage, preferences and translations.
- `photoprep/ui/`: window, read-only canvas, settings dialog and theme.
- `assets/`: approved icon, banner and interface artwork.
- `tests/`: language, image import, navigation and preference regression checks.
- `scripts/`: macOS packaging.
- `work/`, `.venv/`, `build/`, `dist/`: ignored local working files and build outputs.

## Build and verify a DMG

After installing dependencies in the virtual environment:

```bash
PYTHON="$PWD/.venv/bin/python" bash scripts/build_macos.sh
open dist/PhotoPrep.app
hdiutil verify dist/PhotoPrep-0.1.0-alpha.3-macos-arm64.dmg
cd dist
shasum -a 256 -c PhotoPrep-0.1.0-alpha.3-macos-arm64.dmg.sha256
```

The script reads the application version and Python architecture, generates an
ICNS icon, builds a self-contained app, sets bundle metadata, verifies an ad-hoc
signature, and creates a DMG with an Applications shortcut and a portable SHA256
file. **The app is not Developer ID signed or notarized.** Gatekeeper may warn
when opening a downloaded copy. Intel builds and older macOS releases are not
verified.

## Release

Use `vMAJOR.MINOR.PATCH[-alpha.N]`. Keep the package, application and README
versions aligned. Run tests, launch the app, verify the DMG and inspect its app
before tagging. GitHub Actions runs tests on pushes and can build artifacts on
manual dispatch. It does not replace the verified local release binary.

Publish a GitHub prerelease from the verified tag with the DMG and SHA256 file.
Both READMEs must link to that release. See `CHANGELOG.md` for verified changes
and current limits. There are no model downloads, AI inference, crop or export
operations in Stage 2.

Session files contain private local image paths and are ignored by Git. They are saved atomically with owner-only permissions. Packaging copies only an explicit list of UI images; sessions, working files and the repository are not bundled. Photo decoding runs on two background workers; the decoded image cache is bounded at 128 MiB. There is no automatic session upload or persistence.
