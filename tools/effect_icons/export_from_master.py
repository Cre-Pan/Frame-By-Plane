"""Export every ``icon_<ID>_effect`` group of the master SVG to a 39x39 PNG.

Usage (needs Node + Playwright with Chromium, and Pillow):
    python tools/effect_icons/export_from_master.py [master.svg] [output_dir]

Works on the sheet written by ``build_master.py`` and on a copy re-exported
from Figma/Inkscape, as long as each icon keeps its layer name/id. Each icon
is cropped to a 39x39 square centred on its group, rendered at 8x, then
re-centred, enlarged and downsampled like ``render_icons.py``.
"""

import io
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_icons import fit_glyph  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_MASTER = os.path.join(HERE, "effect_icons_master.svg")
DEFAULT_OUT = os.path.join(ROOT, "frame_by_plane", "assets", "icons")
SCALE = 8

NODE_SCRIPT = r"""
const fs = require('fs');
const {chromium} = require('playwright');
(async () => {
  const [svgPath, outDir, scale] = process.argv.slice(2);
  const size = 39 * Number(scale);
  const browser = await chromium.launch();
  const page = await browser.newPage({viewport: {width: size, height: size}});
  await page.setContent('<html><body style="margin:0;background:transparent">'
    + fs.readFileSync(svgPath, 'utf8') + '</body></html>');
  const ids = await page.evaluate(() => {
    const svg = document.querySelector('svg');
    // Hide the sheet (background, panels, labels) but keep text drawn inside icons.
    svg.querySelectorAll('#background, [id^="panel_"] > rect, text').forEach(n => {
      if (!n.closest('g[id^="icon_"]')) n.style.display = 'none';
    });
    return [...svg.querySelectorAll('g[id^="icon_"][id$="_effect"]')].map(g => {
      const box = g.getBBox();
      const m = g.getCTM();
      const cx = m.a * (box.x + box.width / 2) + m.c * (box.y + box.height / 2) + m.e;
      const cy = m.b * (box.x + box.width / 2) + m.d * (box.y + box.height / 2) + m.f;
      return {id: g.id, x: cx - 19.5, y: cy - 19.5};
    });
  });
  for (const item of ids) {
    await page.evaluate(({x, y, size}) => {
      const svg = document.querySelector('svg');
      svg.setAttribute('viewBox', `${x} ${y} 39 39`);
      svg.setAttribute('width', size);
      svg.setAttribute('height', size);
    }, {x: item.x, y: item.y, size});
    await page.screenshot({path: `${outDir}/${item.id}.png`, omitBackground: true,
                           clip: {x: 0, y: 0, width: size, height: size}});
  }
  fs.writeFileSync(`${outDir}/ids.json`, JSON.stringify(ids.map(i => i.id)));
  await browser.close();
})();
"""


def main():
    master = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MASTER)
    out_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "export.js")
        with open(script, "w") as handle:
            handle.write(NODE_SCRIPT)
        subprocess.run(["node", script, master, tmp, str(SCALE)], check=True)
        with open(os.path.join(tmp, "ids.json")) as handle:
            ids = json.load(handle)
        for icon_id in ids:
            with open(os.path.join(tmp, icon_id + ".png"), "rb") as handle:
                big = Image.open(io.BytesIO(handle.read())).convert("RGBA")
            fit_glyph(big).resize((39, 39), Image.LANCZOS).save(os.path.join(out_dir, icon_id + ".png"), optimize=True)
    print(f"Exported {len(ids)} icons into {out_dir}")


if __name__ == "__main__":
    main()
