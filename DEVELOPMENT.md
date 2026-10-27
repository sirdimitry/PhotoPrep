# Developer notes / Заметки разработчика

Current version: **0.1.0-alpha.1**, Stage 1 UI scaffold.

This archive is a checkout-ready source tree; it is not installed on your Mac and has not been pushed to GitHub by this environment. Copy/extract it into your local clone, review the changes, run it on macOS, then commit/push when satisfied.

## Test the app on macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m photoprep
```

## Build `.dmg` (only on macOS)

```bash
bash scripts/build_macos.sh
```

This creates `dist/PhotoPrep-0.1.0-alpha.1-macos-arm64.dmg` and `.sha256`. The app is **ad-hoc signed, not notarized**. Public releases should ideally use Apple Developer ID signing and notarization to avoid Gatekeeper warnings.

## Git versioning

Use `vMAJOR.MINOR.PATCH[-alpha.N]`. Increment alpha when a verified stage or hotfix is completed.

```bash
git remote add origin https://github.com/sirdimitry/PhotoPrep.git  # only if origin missing
git add .
git commit -m "feat(ui): stage 1 desktop workspace (v0.1.0-alpha.1)"
git push -u origin main
# After verifying the macOS alpha application:
git tag v0.1.0-alpha.1
git push origin v0.1.0-alpha.1
```

Pushing a `v*` tag triggers a macOS GitHub Actions build and adds DMG + SHA256 to a prerelease. **Do not tag untested builds.** The project currently does not include model downloads or inference.
