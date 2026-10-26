"""Rasterize designs.py into 39x39 PNG effect icons.

Usage (needs Node + Playwright with Chromium, and Pillow):
    python tools/effect_icons/render_icons.py [output_dir]

Each icon is rendered at 8x in Chromium and downsampled, which keeps the soft
edges consistent with the hand-made mask icons.
"""

import io
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from designs import ICONS, svg  # noqa: E402

SCALE = 8
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUT = os.path.join(ROOT, "frame_by_plane", "assets", "icons")

NODE_SCRIPT = r"""
const fs = require('fs');
const {chromium} = require('playwright');
(async () => {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch();
  const page = await browser.newPage({viewport: {width: %d, height: %d}});
  for (const job of jobs) {
    await page.setContent('<html><body style="margin:0;background:transparent">' + job.svg + '</body></html>');
    await page.screenshot({path: job.out, omitBackground: true, clip: {x: 0, y: 0, width: %d, height: %d}});
  }
  await browser.close();
})();
"""


# Glyphs smaller than this (longest side, in 39 px icon units) are enlarged so
# frameless icons read as large as Blender's native ones at 16-20 px.
GLYPH_TARGET = 33.0


def fit_glyph(big):
    """Centre the glyph of a SCALE-sized render and grow it to GLYPH_TARGET."""
    size = big.size[0]
    alpha = big.getchannel("A").point(lambda a: 255 if a > 20 else 0)
    box = alpha.getbbox()
    if box is None:
        return big
    glyph = big.crop(box)
    longest = max(glyph.size) / size * 39
    factor = max(1.0, GLYPH_TARGET / longest)
    if factor > 1.0:
        glyph = glyph.resize((round(glyph.size[0] * factor), round(glyph.size[1] * factor)), Image.LANCZOS)
    out = Image.new("RGBA", big.size, (0, 0, 0, 0))
    out.alpha_composite(glyph, ((size - glyph.size[0]) // 2, (size - glyph.size[1]) // 2))
    return out


def icon_filename(effect_id):
    return f"icon_{effect_id}_effect.png"


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    size = 39 * SCALE
    with tempfile.TemporaryDirectory() as tmp:
        jobs = [{"svg": svg(eid, SCALE), "out": os.path.join(tmp, eid + ".png")} for eid in ICONS]
        jobs_path = os.path.join(tmp, "jobs.json")
        with open(jobs_path, "w") as handle:
            json.dump(jobs, handle)
        script = os.path.join(tmp, "render.js")
        with open(script, "w") as handle:
            handle.write(NODE_SCRIPT % (size, size, size, size))
        subprocess.run(["node", script, jobs_path], check=True)
        for eid in ICONS:
            with open(os.path.join(tmp, eid + ".png"), "rb") as handle:
                big = Image.open(io.BytesIO(handle.read())).convert("RGBA")
            fit_glyph(big).resize((39, 39), Image.LANCZOS).save(os.path.join(out_dir, icon_filename(eid)), optimize=True)
    print(f"Rendered {len(ICONS)} icons into {out_dir}")


if __name__ == "__main__":
    main()
