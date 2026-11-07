"""Build one editable SVG sheet with every effect icon laid out like the menus.

Usage:
    python tools/effect_icons/build_master.py [output.svg]

Every icon is a group with id ``icon_<ID>_effect`` holding a 39x39 frame and
its glyph, with the menu label next to it. The file opens in Figma, Inkscape
or Illustrator; after editing, ``export_from_master.py`` turns each group back
into ``frame_by_plane/assets/icons/icon_<ID>_effect.png``.
"""

import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from designs import FRAME, ICONS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(ROOT, "frame_by_plane", "effects_registry.py")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "effect_icons_master.svg")

ROW_H = 52
COL_W = 330
SECTION_GAP = 18
FONT = "Inter, 'DejaVu Sans', Arial, sans-serif"


def _registry():
    src = open(REGISTRY, encoding="utf-8").read()
    ns = dict(re.findall(r'^(FBP_EFFECT_\w+) = "(\w+)"', src, re.M))

    def block(name, closer):
        start = src.index(name + " = ")
        end = src.index(closer, start) + len(closer)
        return eval(src[start + len(name) + 3:end], {}, ns)  # noqa: S307 - trusted repo source

    labels = {ns[m.group(1)]: m.group(2) for m in re.finditer(
        r'^    (FBP_EFFECT_\w+): \{\s*"label": "([^"]+)"', src, re.M)}
    return (block("FBP_IMAGE_EFFECT_MENU_SECTIONS", "\n)\n"),
            block("FBP_MESH_EFFECT_MENU_SECTIONS", "\n)\n"),
            block("FBP_EFFECT_FAMILIES", "\n}\n"), labels)


def _unique_ids(body, prefix):
    """Give gradient/clip/mask ids a per-icon prefix so groups never clash."""
    ids = set(re.findall(r'id="([^"]+)"', body))
    for old in sorted(ids, key=len, reverse=True):
        body = body.replace(f'id="{old}"', f'id="{prefix}{old}"')
        body = body.replace(f"url(#{old})", f"url(#{prefix}{old})")
    return body


def _icon_group(effect_id, x, y):
    body = _unique_ids(ICONS[effect_id], f"{effect_id.lower()}_")
    return (f'<g id="icon_{effect_id}_effect" transform="translate({x} {y})">'
            f'{FRAME}{body}</g>')


def _label(x, y, value, size=15, color="#e6e6e6", weight="400"):
    return (f'<text class="label" x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}">{html.escape(value)}</text>')


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    image_sections, mesh_sections, families, labels = _registry()
    family_of = {eid: (fid, lab) for fid, fam in families.items() for eid, lab in fam["variants"]}

    def entry(token):
        if token.startswith("FAMILY:"):
            fid = token.split(":", 1)[1]
            return f"FAMILY_{fid}", families[fid]["label"]
        label = labels.get(token, token)
        if token in family_of:
            fid, variant = family_of[token]
            label = f"{families[fid]['label']} · {variant}"
        return token, label

    panels = [
        ("Image Effects", image_sections, 2),
        ("Mesh Effects", mesh_sections, 2),
        ("Altri", (
            ("Mask", "", ("EDGE_DISTANCE_MASK",)),
            ("Famiglie e stack effetti", "", ("FAMILY:WAVE", "FAMILY:POSTERIZE", "EMISSION",
                                              "GOBO_SHADOWS", "LAYER_BLEND")),
        ), 1),
    ]

    parts, placed = [], set()
    panel_x = 40
    total_h = 0
    for title, sections, columns in panels:
        # Distribute sections over columns by running height.
        cols = [[] for _ in range(columns)]
        heights = [0] * columns
        for name, _icon, tokens in sections:
            tokens = [t for t in tokens if not str(t).endswith("_CONTROL")]
            h = 40 + len(tokens) * ROW_H + SECTION_GAP
            target = heights.index(min(heights))
            cols[target].append((name, tokens))
            heights[target] += h
        panel_w = columns * COL_W + 30
        panel_h = max(heights) + 70
        parts.append(f'<g id="panel_{re.sub(r"[^A-Za-z]+", "_", title).strip("_")}">')
        parts.append(f'<rect x="{panel_x}" y="40" width="{panel_w}" height="{panel_h}" rx="10" '
                     f'fill="#181818" stroke="#333" stroke-width="1"/>')
        parts.append(_label(panel_x + 20, 76, title, 18, "#aaaaaa"))
        for ci, col in enumerate(cols):
            x = panel_x + 20 + ci * COL_W
            y = 100
            for name, tokens in col:
                parts.append(_label(x, y + 18, name.title() if name.isupper() else name, 14, "#8f8f8f"))
                parts.append(f'<rect x="{x}" y="{y + 28}" width="{COL_W - 30}" height="1" fill="#333"/>')
                y += 40
                for token in tokens:
                    eid, label = entry(str(token))
                    if eid not in ICONS or eid in placed:
                        continue
                    parts.append(_icon_group(eid, x, y))
                    parts.append(_label(x + 52, y + 25, label))
                    placed.add(eid)
                    y += ROW_H
                y += SECTION_GAP
        parts.append("</g>")
        panel_x += panel_w + 40
        total_h = max(total_h, panel_h + 80)

    missing = sorted(set(ICONS) - placed)
    if missing:
        raise SystemExit(f"Icons not placed on the sheet: {missing}")
    width = panel_x
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h}" '
           f'viewBox="0 0 {width} {total_h}">'
           f'<rect id="background" width="{width}" height="{total_h}" fill="#232323"/>'
           + "".join(parts) + "</svg>\n")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(svg)
    print(f"Wrote {len(placed)} icons to {out_path}")


if __name__ == "__main__":
    main()
