#!/usr/bin/env python3
"""Convert PNG screenshots in images/ to WebP, keeping only the smaller of the two.

Usage:
    python3 convert_screenshots.py [path ...]            # convert + delete losing PNGs
    python3 convert_screenshots.py --dry-run [path ...]  # report only, change nothing
    python3 convert_screenshots.py --keep-png  [path ...]  # keep both formats

Default behavior:
  - Walks each given path (default: ./images) for *.png files.
  - Encodes WebP at quality=85, method=6 (visually lossless, slow/best compression).
  - If WebP is smaller, deletes the source PNG. If WebP is larger or equal,
    deletes the WebP and keeps the PNG (some screenshots — flat tables with
    crisp text — already compress better as PNG than WebP).
  - Skips files that already have a sibling WebP.

Tunables: QUALITY, METHOD below. For screenshots with sharp text where
visible chroma artifacts matter, run once with LOSSLESS=True instead.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

QUALITY = 85
METHOD = 6
LOSSLESS = False


def encode_webp(png: Path, dry_run: bool) -> Path:
    out = png.with_suffix(".webp")
    if dry_run:
        return out
    img = Image.open(png)
    if LOSSLESS:
        img.save(out, "WEBP", lossless=True, method=METHOD)
    else:
        img.save(out, "WEBP", quality=QUALITY, method=METHOD)
    return out


def fmt(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=["images"], help="files or directories to scan (default: images/)")
    ap.add_argument("--dry-run", action="store_true", help="report only; do not write or delete anything")
    ap.add_argument("--keep-png", action="store_true", help="keep both .png and .webp regardless of which is smaller")
    ap.add_argument("--force", action="store_true", help="always replace PNG with WebP, even if WebP is larger (use for format consistency)")
    args = ap.parse_args()

    pngs: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_file() and p.suffix.lower() == ".png":
            pngs.append(p)
        elif p.is_dir():
            pngs.extend(sorted(p.rglob("*.png")))

    if not pngs:
        print("No PNG files found.")
        return

    total_before = total_after = 0
    skipped = converted = kept_png = 0

    print(f"Scanning {len(pngs)} PNG file(s)…  (quality={QUALITY} method={METHOD} lossless={LOSSLESS})\n")
    print(f"{'ratio':>6}  {'before':>10}  {'after':>10}  result  path")

    for png in pngs:
        webp = png.with_suffix(".webp")
        if webp.exists():
            skipped += 1
            continue

        before = png.stat().st_size
        encode_webp(png, args.dry_run)

        if args.dry_run:
            # Encode a temporary version just to measure
            tmp = png.with_suffix(".webp.tmp")
            img = Image.open(png)
            if LOSSLESS:
                img.save(tmp, "WEBP", lossless=True, method=METHOD)
            else:
                img.save(tmp, "WEBP", quality=QUALITY, method=METHOD)
            after = tmp.stat().st_size
            tmp.unlink()
        else:
            after = webp.stat().st_size

        total_before += before
        total_after += after
        ratio = after / before
        print(f"{ratio * 100:5.1f}%  {fmt(before):>10}  {fmt(after):>10}", end="  ")

        if args.dry_run:
            print(f"(dry-run)  {png}")
            continue

        if args.keep_png:
            print(f"keep-both  {png}")
            converted += 1
        elif after < before or args.force:
            png.unlink()
            tag = "->webp" if after < before else "->webp*"  # * marks a forced convert
            print(f"{tag:<10} {png} -> {webp.name}")
            converted += 1
        else:
            webp.unlink()
            print(f"keep png   {png}  (webp would be larger; use --force to convert anyway)")
            kept_png += 1

    print()
    print(f"Total: {fmt(total_before)} -> {fmt(total_after)}  "
          f"({100 * (total_before - total_after) / max(total_before, 1):.1f}% saved)")
    print(f"Converted: {converted}   Kept as PNG: {kept_png}   Skipped (had sibling .webp): {skipped}")


if __name__ == "__main__":
    main()
