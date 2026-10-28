#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build must run on macOS (requires iconutil and hdiutil)." >&2
  exit 1
fi

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
VERSION="$($PYTHON -c 'from photoprep import __version__; print(__version__)')"
ARCH="$($PYTHON -c 'import platform; print(platform.machine())')"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/work/pyinstaller-cache}"

# Install .[dev] in the active virtual environment before calling this script.
iconutil -c icns assets/PhotoPrep.iconset -o assets/app-icon.icns
"$PYTHON" - <<'ASSETS'
from pathlib import Path
import shutil
from importlib.metadata import distribution
root = Path.cwd()
target = root / "work/runtime-assets"
if target.exists():
    shutil.rmtree(target)
(target / "icons").mkdir(parents=True)
names = ("files", "folder", "export", "settings", "move", "brush", "eraser",
         "crop", "logo", "compare", "info", "zoom-in", "zoom-out", "close", "chevron", "fit")
paths = [Path("app-icon.png"), *(Path("icons") / (name + ".png") for name in names)]
for relative in paths:
    source = root / "assets" / relative
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("Missing or symlinked runtime asset: " + str(relative))
    shutil.copyfile(source, target / relative)
notices = root / 'work/runtime-notices'
if notices.exists():
    shutil.rmtree(notices)
notices.mkdir()
shutil.copyfile(root/'THIRD_PARTY_NOTICES.md',notices/'README.md')
shutil.copyfile(root/'LICENSE',notices/'PhotoPrep-LICENSE')
for name in ('onnxruntime','numpy','protobuf','certifi'):
    package = distribution(name)
    for relative in package.files or ():
        if not any(token in str(relative).lower() for token in ('license','copying','notice')):
            continue
        source = Path(package.locate_file(relative))
        if source.is_file() and not source.is_symlink():
            destination = notices/name/str(relative)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destination)
ASSETS
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --windowed --onedir \
  --name "PhotoPrep" --icon "assets/app-icon.icns" \
  --osx-bundle-identifier "com.sirdimitry.PhotoPrep" \
  --target-architecture "$ARCH" \
  --add-data "work/runtime-assets:assets" \
  --add-data "work/runtime-notices:third-party" \
  launcher.py

"$PYTHON" - <<'PY'
from pathlib import Path
import plistlib
from photoprep import __version__
p = Path("dist/PhotoPrep.app/Contents/Info.plist")
data = plistlib.loads(p.read_bytes())
data.update(CFBundleShortVersionString=__version__.split("-")[0],
            CFBundleVersion=__version__.replace("-alpha.", "."),
            NSHighResolutionCapable=True, LSMinimumSystemVersion="14.0")
p.write_bytes(plistlib.dumps(data))
PY
# Ad-hoc signing (not an Apple Developer ID signature or notarization).
codesign --force --deep --sign - "dist/PhotoPrep.app"
codesign --verify --deep --strict "dist/PhotoPrep.app"
STAGING="$(mktemp -d "$PWD/work/dmg.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
ditto "dist/PhotoPrep.app" "$STAGING/PhotoPrep.app"
ln -s /Applications "$STAGING/Applications"
DMG="PhotoPrep-${VERSION}-macos-${ARCH}.dmg"
hdiutil create -volname "PhotoPrep ${VERSION}" \
  -srcfolder "$STAGING" -ov -format UDZO "dist/$DMG"
(cd dist && shasum -a 256 "$DMG" > "${DMG}.sha256")
echo "Built: dist/$DMG"
