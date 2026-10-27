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
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --windowed --onedir \
  --name "PhotoPrep" --icon "assets/app-icon.icns" \
  --osx-bundle-identifier "com.sirdimitry.PhotoPrep" \
  --target-architecture "$ARCH" \
  --add-data "assets:assets" \
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
