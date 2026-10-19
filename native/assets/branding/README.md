# 星渡 StarPass artwork

The retained original is the requested **minimal monochrome sci-fi emblem**
(revision 2). The discarded anime portrait is not included. This is original
generated artwork, not a Wuthering Waves game asset or official mark.

`starpass-original.png` is the original unmodified 1254×1254 opaque RGB PNG.
Its SHA-256 is recorded in `manifest.json` and the conversion script. All app
icons are deterministic size/format conversions, with no manual retouching.

## Reproduce and verify

From `native/` (also works inside the corresponding-source archive):

```
python scripts/generate_brand_assets.py --verify
python scripts/generate_brand_assets.py --check-reproducible
python scripts/generate_brand_assets.py
python -m unittest discover -s scripts -p test_brand_assets.py -v
```

Verification uses only the Python standard library. The last generation and
reproduction steps use developer-only Pillow **12.3.0**, pinned in
`requirements-assets.txt`. No application runtime or ordinary app-build
dependency on Pillow is added. Nothing is downloaded by the script.

## Retained formats

- Desktop: opaque RGB PNG at 16, 24, 32, 48, 64, 128, 256, 512, and 1024 pixels
- Windows: ICO with PNG entries at 16, 24, 32, 48, 64, 128, and 256 pixels
- macOS: ICNS standard/Retina PNG entries covering 16 through 1024 pixels
- Android: 48dp legacy icons and 108dp adaptive foregrounds at mdpi through
  xxxhdpi; the artwork occupies 72dp with black safe-zone padding. Launchers
  apply their own masks. Notification glyphs remain the dedicated monochrome
  notification resource, not the launcher artwork
- iOS: complete iPhone/iPad/marketing AppIcon catalog, opaque RGB 20–1024 pixel
  representations, plus 64/128/192 pixel UI mark images

PyInstaller retains the desktop PNGs for the Tk window/sidebar on Linux and
other desktops, embeds the Windows executable ICO, and sets the macOS bundle
ICNS. Executable names, bundle IDs, Android package ID, configuration locations,
network behavior, and signing settings remain unchanged. No desktop entry or
host icon setting is installed automatically. The checked-in legacy local
macOS launcher is preserved rather than modifying an existing signed binary.

Checks prove retained bytes, format dimensions, packaging references, and
source-archive inclusion. Actual OS launcher appearance and physical-device
acceptance remain separate checks.
