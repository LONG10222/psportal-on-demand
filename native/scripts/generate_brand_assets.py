#!/usr/bin/env python3
"""Mechanically resize the reviewed StarPass artwork; never downloads anything.

Run --verify using only the standard library. Regeneration requires the reviewed
Pillow version in assets/branding/requirements-assets.txt, not at app runtime.
All paths are relative to the native source root, including in source archives.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "assets/branding/starpass-original.png"
MANIFEST = "assets/branding/manifest.json"
SOURCE_SHA256 = "c2c78755d5b73fc5e2897bfbc418525956932add2222319bb21cc3ec5fe3aa54"
PILLOW_VERSION = "12.3.0"
ANDROID = "android/app/src/main/res"
CATALOG = "ios/PSPortalHost/Assets.xcassets"
DESKTOP = "assets/branding/desktop"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = ((b"icp4", 16), (b"icp5", 32), (b"icp6", 64),
              (b"ic07", 128), (b"ic08", 256), (b"ic09", 512),
              (b"ic10", 1024), (b"ic11", 32), (b"ic12", 64),
              (b"ic13", 256), (b"ic14", 512))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def generate(root=ROOT):
    from PIL import Image, __version__
    if __version__ != PILLOW_VERSION:
        raise ValueError(f"Regenerate with Pillow {PILLOW_VERSION}; found {__version__}")
    original = (root / SOURCE).read_bytes()
    if sha256(original) != SOURCE_SHA256:
        raise ValueError("Original artwork changed; review before regenerating icons")
    source = Image.open(io.BytesIO(original))
    if source.mode != "RGB" or source.size != (1254, 1254):
        raise ValueError("Expected reviewed opaque RGB 1254×1254 artwork")
    cache = {}

    def png(size):
        if size not in cache:
            image = source.resize((size, size), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            image.save(out, "PNG", optimize=False, compress_level=9)
            cache[size] = out.getvalue()
        return cache[size]

    outputs = {}
    for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        outputs[f"{DESKTOP}/starpass-{size}.png"] = png(size)

    # PNG-compressed ICO entries are supported on every targeted Windows release.
    entries, payload = [], b""
    offset = 6 + 16 * len(ICO_SIZES)
    for size in ICO_SIZES:
        data = png(size)
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                   1, 32, len(data), offset))
        payload += data
        offset += len(data)
    outputs[f"{DESKTOP}/starpass.ico"] = struct.pack("<HHH", 0, 1, len(entries)) + b"".join(entries) + payload

    # Native ICNS PNG chunks, including standard and Retina representations.
    chunks = b"".join(kind + struct.pack(">I", len(png(size)) + 8) + png(size)
                      for kind, size in ICNS_SIZES)
    outputs[f"{DESKTOP}/starpass.icns"] = b"icns" + struct.pack(">I", len(chunks) + 8) + chunks

    for density, scale in (("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)):
        outputs[f"{ANDROID}/mipmap-{density}/ic_launcher.png"] = png(int(48 * scale))
        # Fit the untouched square artwork into the adaptive 72/108dp viewport.
        # Black padding is mechanical safe-zone adaptation, not a new illustration.
        edge, artwork = int(108 * scale), int(72 * scale)
        foreground = Image.new("RGB", (edge, edge), (0, 0, 0))
        foreground.paste(source.resize((artwork, artwork), Image.Resampling.LANCZOS),
                         ((edge - artwork) // 2, (edge - artwork) // 2))
        out = io.BytesIO()
        foreground.save(out, "PNG", optimize=False, compress_level=9)
        outputs[f"{ANDROID}/mipmap-{density}/ic_launcher_foreground.png"] = out.getvalue()
    adaptive = b'''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/starpass_icon_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
'''
    outputs[f"{ANDROID}/mipmap-anydpi-v26/ic_launcher.xml"] = adaptive
    outputs[f"{ANDROID}/mipmap-anydpi-v26/ic_launcher_round.xml"] = adaptive
    outputs[f"{ANDROID}/values/branding.xml"] = b'''<?xml version="1.0" encoding="utf-8"?>
<resources><color name="starpass_icon_background">#000000</color></resources>
'''

    icons = []
    for idiom, points, scales in (
        ("iphone", (20, 29, 40, 60), (2, 3)),
        ("ipad", (20, 29, 40, 76), (1, 2)),
        ("ipad", (83.5,), (2,)),
        ("ios-marketing", (1024,), (1,)),
    ):
        for point in points:
            for scale in scales:
                filename = f"starpass-{int(point * scale)}.png"
                icons.append({"filename": filename, "idiom": idiom,
                              "size": f"{point}x{point}", "scale": f"{scale}x"})
                outputs[f"{CATALOG}/AppIcon.appiconset/{filename}"] = png(int(point * scale))
    info = {"author": "xcode", "version": 1}
    outputs[f"{CATALOG}/AppIcon.appiconset/Contents.json"] = json_bytes({"images": icons, "info": info})
    marks = []
    for scale in (1, 2, 3):
        filename = f"starpass-{64 * scale}.png"
        marks.append({"filename": filename, "idiom": "universal", "scale": f"{scale}x"})
        outputs[f"{CATALOG}/StarPassMark.imageset/{filename}"] = png(64 * scale)
    outputs[f"{CATALOG}/StarPassMark.imageset/Contents.json"] = json_bytes({"images": marks, "info": info})
    outputs[f"{CATALOG}/Contents.json"] = json_bytes({"info": info})
    return outputs


def manifest_for(outputs):
    return {
        "brand": "星渡 StarPass", "source": SOURCE, "source_sha256": SOURCE_SHA256,
        "source_size": [1254, 1254], "source_mode": "RGB",
        "recipe": "Pillow 12.3.0 LANCZOS resize; RGB PNG compress_level=9, optimize=False; Android 72/108dp black safe-zone padding; PNG-frame ICO/ICNS",
        "outputs": {path: {"sha256": sha256(data), "bytes": len(data)}
                    for path, data in sorted(outputs.items())},
    }


def verify(root=ROOT):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if manifest["source"] != SOURCE or manifest["source_sha256"] != SOURCE_SHA256:
        raise ValueError("Unexpected artwork identity in manifest")
    if sha256((root / SOURCE).read_bytes()) != SOURCE_SHA256:
        raise ValueError("Original artwork hash differs")
    for path, expected in manifest["outputs"].items():
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Asset path leaves native source root")
        data = (root / relative).read_bytes()
        if len(data) != expected["bytes"] or sha256(data) != expected["sha256"]:
            raise ValueError(f"Generated asset differs: {path}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Check all retained hashes without Pillow")
    parser.add_argument("--check-reproducible", action="store_true", help="Recreate and compare every byte using pinned Pillow")
    parser.add_argument("--root", type=Path, default=ROOT, help="Native source root")
    args = parser.parse_args()
    if args.verify:
        manifest = verify(args.root)
    else:
        outputs = generate(args.root)
        manifest = manifest_for(outputs)
        if args.check_reproducible:
            verify(args.root)
            for path, data in outputs.items():
                if (args.root / path).read_bytes() != data:
                    raise ValueError(f"Reproduction differs: {path}")
            if (args.root / MANIFEST).read_bytes() != json_bytes(manifest):
                raise ValueError("Generated asset manifest differs")
        else:
            for path, data in outputs.items():
                destination = args.root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            (args.root / MANIFEST).write_bytes(json_bytes(manifest))
            verify(args.root)
    print(f"Verified {len(manifest['outputs'])} StarPass assets and unchanged original")


if __name__ == "__main__":
    main()
