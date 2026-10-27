#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build must run on macOS (requires iconutil and hdiutil)." >&2
  exit 1
fi

cd "$(dirname "$0")/.."
VERSION="0.1.0-alpha.1"

python3 -m pip install -e '.[dev]'
iconutil -c icns assets/PhotoPrep.iconset -o assets/app-icon.icns
python3 -m PyInstaller \
  --noconfirm --clean --windowed --onedir \
  --name "PhotoPrep" --icon "assets/app-icon.icns" \
  --add-data "assets:assets" \
  launcher.py

# Ad-hoc signing (not an Apple Developer ID signature or notarization).
codesign --force --deep --sign - "dist/PhotoPrep.app"
DMG="dist/PhotoPrep-${VERSION}-macos-arm64.dmg"
hdiutil create -volname "PhotoPrep ${VERSION}" \
  -srcfolder "dist/PhotoPrep.app" -ov -format UDZO "$DMG"
shasum -a 256 "$DMG" > "${DMG}.sha256"
echo "Built: $DMG"
