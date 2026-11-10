"""Install new release-splash artwork (cross-platform twin of update_splash_assets.ps1).

Usage:
    python tools/update_splash_assets.py path/to/splash.png

The artwork must be a 903x1010 PNG: button positions in feedback.py are laid
out for those dimensions. The PNG is copied byte-for-byte to
assets/splash/splash_bg_NORMAL.png, the four fallback slices are regenerated
without resampling, and the button assets are checked to be untouched.
Requires Pillow.
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

from PIL import Image

WIDTH, HEIGHT = 903, 1010
SLICES = (("top", 0, 88), ("upper", 88, 360), ("lower", 448, 480), ("footer", 928, 82))
ASSET_DIR = Path(__file__).resolve().parent.parent / "frame_by_plane" / "assets" / "splash"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artwork", type=Path)
    args = parser.parse_args(argv)

    source = args.artwork.resolve()
    destination = ASSET_DIR / "splash_bg_NORMAL.png"
    buttons = {p.name: sha256(p) for p in ASSET_DIR.glob("splash_button_*.png")}

    with Image.open(source) as image:
        if image.format != "PNG":
            sys.exit(f"Expected a PNG; got {image.format}.")
        if image.size != (WIDTH, HEIGHT):
            sys.exit(f"Expected {WIDTH}x{HEIGHT} artwork; got {image.width}x{image.height}. "
                     "Button positions require the original dimensions.")
        rgba = image.convert("RGBA")
        for name, top, height in SLICES:
            rgba.crop((0, top, WIDTH, top + height)).save(ASSET_DIR / f"splash_bg_slice_{name}.png")

    if source != destination.resolve():
        shutil.copyfile(source, destination)
    if sha256(destination) != sha256(source):
        sys.exit("The installed splash does not match the supplied PNG.")
    for name, digest in buttons.items():
        if sha256(ASSET_DIR / name) != digest:
            sys.exit(f"Button asset unexpectedly changed: {name}")

    print(f"Installed original {WIDTH}x{HEIGHT} splash: {sha256(destination)}")
    print("Regenerated four fallback slices; all button assets unchanged.")


if __name__ == "__main__":
    main()
