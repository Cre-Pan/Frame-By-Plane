"""Vector sources for the Frame By Plane effect icons.

Each entry is the inner SVG of a frameless 39x39 icon: a light grey glyph
(``p``) and a half-strength secondary tone (``s``).
Run ``render_icons.py`` to rasterize them into ``icon_<ID>_effect.png``.
"""

import math
import random

P = "#d9d9d9"


def _stroke(d, op=1.0, w=2.0, extra=""):
    return (f'<path d="{d}" fill="none" stroke="{P}" stroke-opacity="{op}" '
            f'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" {extra}/>')


def p(d, w=2.0, extra=""):
    return _stroke(d, 1.0, w, extra)


def s(d, w=2.0, extra=""):
    return _stroke(d, 0.5, w, extra)


def fill(d, op=1.0):
    return f'<path d="{d}" fill="{P}" fill-opacity="{op}"/>'


def circ(cx, cy, r, op=1.0, stroke=False, w=2.0):
    if stroke:
        return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{P}" '
                f'stroke-opacity="{op}" stroke-width="{w}"/>')
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{P}" fill-opacity="{op}"/>'


def rect(x, y, w, h, op=1.0, rx=0.0, stroke=False, sw=2.0, extra=""):
    if stroke:
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="none" '
                f'stroke="{P}" stroke-opacity="{op}" stroke-width="{sw}" {extra}/>')
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{P}" '
            f'fill-opacity="{op}" {extra}/>')


def grect(x, y, w, h, op, rx, grad):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="url(#{grad})"/>'


def text(x, y, t, size=10, op=1.0, weight="bold", anchor="middle"):
    return (f'<text x="{x}" y="{y}" font-family="DejaVu Sans Mono, monospace" '
            f'font-size="{size}" font-weight="{weight}" fill="{P}" fill-opacity="{op}" '
            f'text-anchor="{anchor}">{t}</text>')


def rays(cx, cy, r1, r2, n=8, op=0.5, w=2.0, phase=0.0):
    out = []
    for i in range(n):
        a = phase + i * 2 * math.pi / n
        out.append(_stroke(
            f"M{cx + r1 * math.cos(a):.2f} {cy + r1 * math.sin(a):.2f} "
            f"L{cx + r2 * math.cos(a):.2f} {cy + r2 * math.sin(a):.2f}", op, w))
    return "".join(out)


def poly(points, op=1.0, close=True):
    d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points) + (" Z" if close else "")
    return fill(d, op)


def hexagon(cx, cy, r, rot=0.0):
    return [(cx + r * math.cos(rot + i * math.pi / 3), cy + r * math.sin(rot + i * math.pi / 3))
            for i in range(6)]


def hpath(points, close=True):
    return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points) + (" Z" if close else "")


GRAD_LR = ('<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
           f'<stop offset="0" stop-color="{P}" stop-opacity="0.08"/>'
           f'<stop offset="1" stop-color="{P}" stop-opacity="1"/></linearGradient></defs>')
GRAD_RL = ('<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
           f'<stop offset="0" stop-color="{P}" stop-opacity="1"/>'
           f'<stop offset="1" stop-color="{P}" stop-opacity="0.08"/></linearGradient></defs>')
GRAD_DIAG = ('<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
             f'<stop offset="0" stop-color="{P}" stop-opacity="1"/>'
             f'<stop offset="1" stop-color="{P}" stop-opacity="0.05"/></linearGradient></defs>')


# --------------------------------------------------------------------------
# Generated patterns


def _pixel_circle():
    out = []
    cell = 4.4
    ox = oy = 19.5 - 2.5 * cell
    for j in range(5):
        for i in range(5):
            cx, cy = ox + (i + 0.5) * cell, oy + (j + 0.5) * cell
            d = math.hypot(cx - 19.5, cy - 19.5)
            if d < 11.5:
                op = 1.0 if (i + j) % 2 == 0 else 0.55
                out.append(rect(ox + i * cell + 0.4, oy + j * cell + 0.4, cell - 0.8, cell - 0.8, op))
    return "".join(out)


def _dither():
    out = []
    bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
    step = 3.0
    n = 8
    ox = 19.5 - n * step / 2
    for j in range(n):
        for i in range(n):
            level = (i + 0.5) / n * 16
            if bayer[j % 4][i % 4] < level:
                out.append(rect(ox + i * step + 0.3, ox + j * step + 0.3, step - 0.6, step - 0.6, 1.0))
    return "".join(out)


def _halftone():
    out = []
    n = 5
    step = 5.2
    ox = 19.5 - (n - 1) * step / 2
    for j in range(n):
        for i in range(n):
            t = (i + j) / (2 * (n - 1))
            r = 0.7 + 2.0 * t
            out.append(circ(ox + i * step, ox + j * step, round(r, 2)))
    return "".join(out)


def _dot_matrix():
    shape = ["01110", "10001", "11111", "10001", "10001"]  # "A"
    out = []
    step = 5.2
    ox = 19.5 - 2 * step
    for j, row in enumerate(shape):
        for i, c in enumerate(row):
            out.append(circ(ox + i * step, ox + j * step, 1.9, 1.0 if c == "1" else 0.3))
    return "".join(out)


def _noise_squares(seed, n=7, step=3.6):
    rnd = random.Random(seed)
    out = []
    ox = 19.5 - n * step / 2
    for j in range(n):
        for i in range(n):
            op = rnd.choice((0.0, 0.25, 0.5, 0.8, 1.0))
            if op:
                out.append(rect(ox + i * step, ox + j * step, step, step, op))
    return "".join(out)


def _grain(seed):
    rnd = random.Random(seed)
    out = []
    for _ in range(70):
        x, y = rnd.uniform(8, 31), rnd.uniform(8, 31)
        out.append(circ(round(x, 2), round(y, 2), round(rnd.uniform(0.5, 1.1), 2),
                        rnd.choice((0.35, 0.6, 1.0))))
    return "".join(out)


def _fibers(seed):
    rnd = random.Random(seed)
    out = []
    for _ in range(11):
        x, y = rnd.uniform(9, 28), rnd.uniform(9, 29)
        a = rnd.uniform(0, math.pi)
        l = rnd.uniform(5, 9)
        x2, y2 = x + l * math.cos(a), y + l * math.sin(a)
        mx, my = (x + x2) / 2 + rnd.uniform(-2.5, 2.5), (y + y2) / 2 + rnd.uniform(-2.5, 2.5)
        out.append(_stroke(f"M{x:.1f} {y:.1f} Q{mx:.1f} {my:.1f} {x2:.1f} {y2:.1f}",
                           rnd.choice((0.5, 1.0)), 1.4))
    return "".join(out)


def _wavy_grid(amp=1.6, n=4):
    out = []
    for k in range(n):
        t = 9 + k * (21 / (n - 1))
        h = "M8 {:.1f}".format(t)
        v = "M{:.1f} 8".format(t)
        for i in range(1, 9):
            x = 8 + i * 23 / 8
            h += f" L{x:.1f} {t + amp * math.sin(i * 1.4 + k):.1f}"
            v += f" L{t + amp * math.sin(i * 1.4 + k + 2):.1f} {x:.1f}"
        out.append(p(h, 1.6) if k % 3 == 0 else s(h, 1.6))
        out.append(p(v, 1.6) if k % 3 == 0 else s(v, 1.6))
    return "".join(out)


def _bulge_grid():
    out = []
    for k, t in enumerate((8.5, 14, 19.5, 25, 30.5)):
        bend = (t - 19.5) * 0.45
        op_fn = p if k in (0, 4) else s
        out.append(op_fn(f"M{t} 8 Q{t + bend:.1f} 19.5 {t} 31", 1.6))
        out.append(op_fn(f"M8 {t} Q19.5 {t + bend:.1f} 31 {t}", 1.6))
    return "".join(out)


def _kaleidoscope():
    out = []
    for i in range(6):
        a1 = i * math.pi / 3 - math.pi / 2
        a2 = a1 + math.pi / 3
        pts = [(19.5, 19.5), (19.5 + 12 * math.cos(a1), 19.5 + 12 * math.sin(a1)),
               (19.5 + 12 * math.cos(a2), 19.5 + 12 * math.sin(a2))]
        out.append(poly(pts, 1.0 if i % 2 == 0 else 0.4))
    out.append(p(hpath(hexagon(19.5, 19.5, 12, -math.pi / 2)), 1.4))
    return "".join(out)


def _honeycomb():
    out = []
    r = 5.0
    centers = [(19.5, 19.5)] + [(19.5 + r * math.sqrt(3) * math.cos(i * math.pi / 3 + math.pi / 6),
                                  19.5 + r * math.sqrt(3) * math.sin(i * math.pi / 3 + math.pi / 6))
                                 for i in range(6)]
    for i, (cx, cy) in enumerate(centers):
        hx = hexagon(cx, cy, r - 0.7, 0)
        out.append(poly(hx, 1.0 if i == 0 else (0.6 if i % 2 else 0.3)))
    return "".join(out)


def _mosaic():
    rnd = random.Random(7)
    out = []
    for j in range(4):
        for i in range(4):
            cx, cy = 10 + i * 6.4 + rnd.uniform(-0.8, 0.8), 10 + j * 6.4 + rnd.uniform(-0.8, 0.8)
            ang = rnd.uniform(-18, 18)
            op = rnd.choice((0.35, 0.6, 1.0))
            out.append(rect(round(cx - 2.6, 2), round(cy - 2.6, 2), 5.2, 5.2, op, 0.6,
                            extra=f'transform="rotate({ang:.0f} {cx:.1f} {cy:.1f})"'))
    return "".join(out)


def _crosshatch():
    out = ['<defs><clipPath id="c"><circle cx="19.5" cy="19.5" r="12"/></clipPath></defs><g clip-path="url(#c)">']
    for k in range(-24, 25, 4):
        out.append(p(f"M{7 + k} 7 L{32 + k} 32", 1.3))
    for k in range(-24, 25, 4):
        if k > -4:
            out.append(s(f"M{32 + k} 7 L{7 + k} 32", 1.3))
    out.append("</g>")
    out.append(circ(19.5, 19.5, 12, 0.5, True, 1.4))
    return "".join(out)


def _histogram(threshold=None):
    heights = [5, 9, 14, 19, 16, 22, 17, 12, 8, 5]
    out = []
    for i, h in enumerate(heights):
        x = 7.5 + i * 2.5
        op = 1.0 if threshold is not None and x >= threshold else 0.45
        out.append(rect(x, 31 - h, 2.0, h, op))
    return "".join(out)


def _knit():
    out = []
    for row in range(4):
        y = 9 + row * 6
        for col in range(3):
            x = 10 + col * 7
            fn = p if (row + col) % 2 == 0 else s
            out.append(fn(f"M{x - 3} {y} Q{x - 1.2} {y + 5} {x} {y + 6} Q{x + 1.2} {y + 5} {x + 3} {y}", 1.6))
    return "".join(out)


def _felt():
    out = [circ(19.5, 19.5, 7, 1.0)]
    rnd = random.Random(3)
    for i in range(22):
        a = i * 2 * math.pi / 22 + rnd.uniform(-0.1, 0.1)
        r1, r2 = 8.5, rnd.uniform(11, 13.5)
        out.append(_stroke(f"M{19.5 + r1 * math.cos(a):.1f} {19.5 + r1 * math.sin(a):.1f} "
                           f"L{19.5 + r2 * math.cos(a + 0.15):.1f} {19.5 + r2 * math.sin(a + 0.15):.1f}",
                           rnd.choice((0.5, 1.0)), 1.3))
    return "".join(out)


def _tufts():
    out = [p("M7 31 H32", 2)]
    for i, x in enumerate((10, 15, 20, 25, 30)):
        fn = p if i % 2 == 0 else s
        h = 16 if i % 2 == 0 else 12
        out.append(fn(f"M{x} 31 Q{x - 1} {31 - h / 2} {x - 4} {31 - h}", 1.6))
        out.append(fn(f"M{x} 31 Q{x + 1} {31 - h / 2} {x + 3} {31 - h - 1}", 1.6))
    return "".join(out)


def _textellation():
    chars = ["@#%", "#@#", "%#@"]
    out = []
    for j, row in enumerate(chars):
        for i, c in enumerate(row):
            op = 1.0 if (i + j) % 2 == 0 else 0.5
            out.append(text(11.5 + i * 8, 14.5 + j * 8.5, c, 8.5, op))
    return "".join(out)


def _text_matrix():
    out = []
    for j in range(2):
        for i in range(2):
            x, y = 13 + i * 13, 17.5 + j * 13
            out.append(text(x + 1.2, y + 1.2, "A", 12, 0.4))
            out.append(text(x, y, "A", 12, 1.0))
    return "".join(out)


def _kinetic():
    out = []
    for j in range(3):
        for i in range(3):
            x, y = 8 + i * 8.2, 8 + j * 8.2
            if (i, j) in ((1, 1), (2, 0)):
                out.append(rect(x + 0.3, y + 0.3, 6.4, 6.4, 1.0,
                                extra=f'transform="rotate(30 {x + 3.5} {y + 3.5})"'))
            else:
                out.append(rect(x, y, 7, 7, 0.45, 0.8))
    return "".join(out)


def _iso_cube(x, y, a, op_top=1.0, op_l=0.6, op_r=0.35):
    h = a * 0.5
    top = [(x, y), (x + a, y + h), (x, y + 2 * h), (x - a, y + h)]
    left = [(x - a, y + h), (x, y + 2 * h), (x, y + 2 * h + a), (x - a, y + h + a)]
    right = [(x + a, y + h), (x, y + 2 * h), (x, y + 2 * h + a), (x + a, y + h + a)]
    return poly(top, op_top) + poly(left, op_l) + poly(right, op_r)


def _shards():
    tris = [
        ([(8, 12), (17, 8), (14, 18)], 1.0),
        ([(20, 9), (30, 11), (24, 17)], 0.55),
        ([(9, 22), (17, 21), (12, 31)], 0.55),
        ([(19, 21), (29, 19), (26, 30)], 1.0),
        ([(16, 24), (20, 31), (13, 32)], 0.3),
    ]
    return "".join(poly(pts, op) for pts, op in tris)


ICONS = {
    # ---------------------------------------------------------------- Color
    "CROP": rect(13, 13, 13, 13, 0.35) + p("M13 7 V26 H32") + p("M7 13 H26 V32"),
    "EXTEND": (rect(7, 7, 25, 25, 0.5, 3, True, 1.6, 'stroke-dasharray="3 2.5"')
               + rect(14, 14, 11, 11, 1.0, 1.5)
               + p("M25 14 L30 9 M30 9 H26 M30 9 V13") + p("M14 25 L9 30 M9 30 H13 M9 30 V26")),
    "HUE_SATURATION": "".join(
        poly([(19.5, 19.5)] + [(19.5 + 12 * math.cos(a), 19.5 + 12 * math.sin(a))
                               for a in [i * math.pi / 3 + k * math.pi / 30 for k in range(11)]],
             (1.0, 0.75, 0.5, 0.3, 0.5, 0.75)[i])
        for i in range(6)) + circ(19.5, 19.5, 4, 0.0) + circ(19.5, 19.5, 3.2, 1.0),
    "WHITE_BALANCE": (p("M15 23 V10 a3 3 0 0 1 6 0 V23") + circ(18, 27, 4.5, 1.0)
                      + rect(16.8, 14, 2.4, 10, 1.0) + s("M25 10 H30 M25 15 H29 M25 20 H30", 1.6)),
    "BRIGHTNESS_CONTRAST": (circ(19.5, 19.5, 7, 1.0, True) + fill("M19.5 12.5 a7 7 0 0 0 0 14 Z")
                            + rays(19.5, 19.5, 10, 13, 8, 0.5)),
    "CURVES": (rect(7, 7, 25, 25, 0.5, 3, True, 1.4) + s("M7 32 L32 7", 1.2, 'stroke-dasharray="2 2"')
               + p("M8 31 C18 31 15 8 31 8") + circ(13.5, 27, 2.2) + circ(25.5, 11, 2.2)),
    "FAMILY_COLORIZE": (fill("M19.5 6 C19.5 6 10 17 10 23.5 a9.5 9.5 0 0 0 19 0 C29 17 19.5 6 19.5 6 Z", 0.35)
                        + p("M19.5 6 C19.5 6 10 17 10 23.5 a9.5 9.5 0 0 0 19 0 C29 17 19.5 6 19.5 6 Z")
                        + p("M14.5 24 a5 5 0 0 0 5 5", 1.6)),
    "SOLID_MASK": rect(9, 9, 21, 21, 0.45, 4) + rect(9, 9, 21, 21, 1.0, 4, True),
    "DUOTONE": circ(15, 19.5, 8, 1.0) + circ(24, 19.5, 8, 0.45) + circ(24, 19.5, 8, 1.0, True, 1.4),
    "FALSE_COLOR": ('<defs><clipPath id="c"><rect x="8" y="8" width="23" height="23" rx="3"/></clipPath></defs>'
                    '<g clip-path="url(#c)">' + rect(8, 8, 23, 6, 1.0) + rect(8, 14, 23, 6, 0.7)
                    + rect(8, 20, 23, 6, 0.45) + rect(8, 26, 23, 5, 0.2) + "</g>"),
    "TRITONE": rect(8, 9, 6.5, 21, 1.0, 1.5) + rect(16.25, 9, 6.5, 21, 0.6, 1.5) + rect(24.5, 9, 6.5, 21, 0.3, 1.5),
    "RECOLOR": (GRAD_LR + grect(7, 11, 25, 10, 1.0, 2, "g")
                + poly([(10, 31), (12.5, 26), (15, 31)]) + poly([(18, 31), (20.5, 26), (23, 31)], 0.5)
                + poly([(26, 31), (28.5, 26), (31, 31)])),
    "GRADIENT_MAP": (GRAD_LR + grect(7, 7, 25, 7, 1.0, 2, "g")
                     + rect(7, 18, 25, 14, 0.5, 2.5, True, 1.4)
                     + fill("M9 31 L16 23 L21 28 L25 24 L30 31 Z", 1.0) + circ(25.5, 21.8, 1.6)),
    "CHANNEL_MIXER": (circ(15.5, 15.5, 7, 1.0, True, 1.8) + circ(23.5, 15.5, 7, 1.0, True, 1.8)
                      + circ(19.5, 22.5, 7, 1.0, True, 1.8) + circ(19.5, 18, 2.4, 0.5)),
    "FILTER_PRESETS": (rect(13, 7, 18, 15, 0.3, 2.5) + rect(10.5, 10.5, 18, 15, 0.55, 2.5)
                       + rect(8, 14, 18, 16, 1.0, 2.5)
                       + '<path d="M10 28 L15 22 L18.5 25 L21 22.5 L24 28 Z" fill="#000" fill-opacity="0.55"/>'),
    "VIGNETTE": ('<defs><radialGradient id="v" cx="0.5" cy="0.5" r="0.62">'
                 f'<stop offset="0.45" stop-color="{P}" stop-opacity="0"/>'
                 f'<stop offset="1" stop-color="{P}" stop-opacity="1"/></radialGradient></defs>'
                 + grect(7, 7, 25, 25, 1.0, 3, "v") + rect(7, 7, 25, 25, 1.0, 3, True, 1.4)),
    # ---------------------------------------------------------------- Light
    "BLOOM": ('<defs><radialGradient id="b"><stop offset="0" stop-color="#d9d9d9" stop-opacity="0.75"/>'
              '<stop offset="1" stop-color="#d9d9d9" stop-opacity="0"/></radialGradient></defs>'
              + '<circle cx="19.5" cy="19.5" r="13" fill="url(#b)"/>'
              + circ(19.5, 19.5, 4.5) + rays(19.5, 19.5, 7.5, 12, 8, 1.0, 1.6, math.pi / 8)),
    "GRADIENT_LIGHT": (GRAD_DIAG + grect(7, 7, 25, 25, 1.0, 3, "g")
                       + rect(7, 7, 25, 25, 0.5, 3, True, 1.4)),
    "RIM": circ(19.5, 19.5, 10, 0.3) + p("M19.5 7 a12.5 12.5 0 0 1 0 25", 3),
    "SHADOW": rect(14, 14, 17, 17, 0.4, 2.5) + rect(8, 8, 17, 17, 1.0, 2.5, True),
    "GOBO_SHADOWS": (p("M9 7 L14 12", 2.4) + circ(9.5, 7.5, 2.6)
                     + poly([(15, 17), (22, 15.5), (20.5, 22), (13, 23.5)], 0.6)
                     + poly([(24, 15), (31, 13.5), (29.5, 20.5), (22.5, 21.5)], 0.6)
                     + poly([(12.5, 25.5), (20, 24), (18.5, 31), (11, 32)], 0.6)
                     + poly([(22, 23.5), (29, 22), (27.5, 29.5), (20.5, 30.5)], 0.6)),
    "EMISSION": rect(13, 13, 13, 13, 1.0, 2) + rays(19.5, 19.5, 10.5, 14, 8, 0.5, 1.8),
    # ---------------------------------------------------------------- Blur
    "GAUSSIAN_BLUR": circ(19.5, 19.5, 12.5, 0.15) + circ(19.5, 19.5, 9.5, 0.3) + circ(19.5, 19.5, 6.5, 0.55) + circ(19.5, 19.5, 3.5, 1.0),
    "FAMILY_DIRECTIONAL_BLUR": (circ(25, 19.5, 6.5) + s("M7 14 H17 M9 19.5 H16 M7 25 H17", 2)),
    "DIRECTIONAL_BLUR": (circ(25, 19.5, 6.5) + s("M7 14 H17 M9 19.5 H16 M7 25 H17", 2)),
    "TILT_SHIFT": ('<defs><linearGradient id="t1" x1="0" y1="0" x2="0" y2="1">'
                   f'<stop offset="0" stop-color="{P}" stop-opacity="0.6"/><stop offset="1" stop-color="{P}" stop-opacity="0"/></linearGradient>'
                   '<linearGradient id="t2" x1="0" y1="1" x2="0" y2="0">'
                   f'<stop offset="0" stop-color="{P}" stop-opacity="0.6"/><stop offset="1" stop-color="{P}" stop-opacity="0"/></linearGradient></defs>'
                   + grect(7, 7, 25, 9, 1.0, 2, "t1") + grect(7, 23, 25, 9, 1.0, 2, "t2")
                   + p("M7 17 H32") + p("M7 22 H32")),
    "DEPTH_BLUR": circ(26, 12.5, 4, 0.25) + circ(20.5, 18.5, 5, 0.5) + circ(14, 25, 6.5, 1.0, True, 2.2),
    "TRIANGLE_BLUR": (poly([(19.5, 6.5), (33, 31), (6, 31)], 0.15) + poly([(19.5, 10.5), (29.5, 28.5), (9.5, 28.5)], 0.3)
                      + p("M19.5 13.5 L27 26.5 H12 Z")),
    # ---------------------------------------------------------------- Pixel / Print
    "FAMILY_PIXELATE_MOSAIC": _pixel_circle(),
    "PIXELATE": _pixel_circle(),
    "HEX_PIXELATE": _honeycomb(),
    "MOSAIC_JITTER": _mosaic(),
    "DITHER": _dither(),
    "HALFTONE": _halftone(),
    "RISO_PRINT": circ(16.5, 16.5, 9, 0.45) + circ(22.5, 22.5, 9, 1.0, True),
    "DOT_MATRIX": _dot_matrix(),
    "CROSSHATCH": _crosshatch(),
    # ---------------------------------------------------------------- Deform
    "UV_DISTORTION": _wavy_grid(),
    "FAMILY_WAVE": (rect(8, 8, 23, 23, 0.4, 1, True, 1.3, 'stroke-dasharray="2 2"')
                    + fill("M11 11 Q20 15 29 9 Q25 19.5 30 30 Q19.5 26 9 29 Q14 19.5 11 11 Z", 0.35)
                    + p("M11 11 Q20 15 29 9 Q25 19.5 30 30 Q19.5 26 9 29 Q14 19.5 11 11 Z", 1.8)
                    + circ(11, 11, 2.2) + circ(29, 9, 2.2) + circ(30, 30, 2.2) + circ(9, 29, 2.2)),
    "WAVE_WARP": p("M7 17 Q10.5 9 14 17 T21 17 T28 17 T35 17") + s("M7 24 Q10.5 16 14 24 T21 24 T28 24 T35 24"),
    "SWIRL": p("M19.5 19.5 m0 0 a1.5 1.5 0 0 1 3 0 a4.5 4.5 0 0 1 -9 0 a7.5 7.5 0 0 1 15 0 a10.5 10.5 0 0 1 -21 0"),
    "BULGE_PINCH": _bulge_grid(),
    "RIPPLE_DISTORTION": (circ(19.5, 19.5, 3) + circ(19.5, 19.5, 7, 1.0, True) + circ(19.5, 19.5, 11, 0.5, True)
                          + '<path d="M7 19.5 a12.5 12.5 0 0 0 25 0" fill="none"/>'),
    "LENS_WARP": (circ(19.5, 19.5, 12.5, 1.0, True) + s("M13 9 Q10 19.5 13 30 M26 9 Q29 19.5 26 30 M9 13 Q19.5 10 30 13 M9 26 Q19.5 29 30 26", 1.5)
                  + s("M19.5 7 V32 M7 19.5 H32", 1.5)),
    "SLICE_SHIFT": (rect(6, 8, 18, 4, 1.0, 1) + rect(12, 13.5, 18, 4, 0.5, 1) + rect(8, 19, 18, 4, 1.0, 1)
                    + rect(15, 24.5, 18, 4, 0.5, 1) + rect(10, 30, 18, 2.5, 1.0, 1)),
    "KALEIDOSCOPE": _kaleidoscope(),
    # ---------------------------------------------------------------- Edges
    "FAMILY_EDGE": (fill("M10 29 C6 22 10 12 18 10 C26 8 33 14 30 22 C28 28 20 33 10 29 Z", 0.25)
                    + p("M10 29 C6 22 10 12 18 10 C26 8 33 14 30 22 C28 28 20 33 10 29 Z")),
    "EDGE_DETECT": (p("M12 27 C9 22 12 15 18 14 C24 13 28 17 26 22 C25 26 19 29 12 27 Z")
                    + s("M7 11 V7 H11 M28 7 H32 V11 M32 28 V32 H28 M11 32 H7 V28", 1.6)),
    "EDGE_WORK": (p("M10 29 C6 22 10 12 18 10 C26 8 33 14 30 22 C28 28 20 33 10 29 Z", 2.4)
                  + s("M13 26 C10 21 13 15 18.5 13.5 C24 12 29 16 27 21 C25.5 25 20 28 13 26 Z", 1.4)),
    "POSTER_EDGES": ('<defs><clipPath id="c"><circle cx="19.5" cy="19.5" r="11.5"/></clipPath></defs>'
                     '<g clip-path="url(#c)">' + rect(7, 7, 25, 8.5, 1.0) + rect(7, 15.5, 25, 8, 0.55)
                     + rect(7, 23.5, 25, 9, 0.25) + "</g>" + circ(19.5, 19.5, 12, 1.0, True, 2.2)),
    "ADAPTIVE_THRESHOLD": (rect(7, 7, 25, 25, 0.5, 3, True, 1.4)
                           + fill("M7 10 Q7 7 10 7 H17 L21 12 L16 17 L22 22 L17 27 L20 32 H10 Q7 32 7 29 Z")),
    "FAMILY_STYLIZE": ('<defs><mask id="m"><rect width="39" height="39" fill="#fff"/>'
                       '<circle cx="13" cy="16" r="2.4" fill="#000"/><circle cx="19" cy="11.5" r="2.4" fill="#000"/>'
                       '<circle cx="26" cy="13" r="2.4" fill="#000"/><circle cx="23" cy="25" r="3.2" fill="#000"/></mask></defs>'
                       '<path mask="url(#m)" fill="#d9d9d9" d="M19.5 6.5 C29 6.5 33 12 33 17 C33 22 27 21 25.5 23 '
                       'C24 25 29 28 25 31 C22 33 19 32.5 17 32.5 C10 32.5 6 27 6 19.5 C6 12 12 6.5 19.5 6.5 Z"/>'),
    "INK": (fill("M7 28 C12 18 18 30 24 16 C26 12 29 10 32 11 C28 13 27 17 25 22 C21 31 13 25 9 30 Z")
            + fill("M27 25 C27 25 24 29 24 31 a3 3 0 0 0 6 0 C30 29 27 25 27 25 Z", 0.5)),
    "PENCIL_SKETCH": (p("M23 9 L30 16 L16 30 L9 30 L9 23 Z") + p("M20 12 L27 19", 1.6)
                      + s("M7 14 Q10 11 13 13 M6 19 Q9 16 12 18", 1.4)),
    "EMBOSS": (rect(9, 9, 21, 21, 0.25, 2) + p("M9 30 V11 Q9 9 11 9 H30", 2.4) + s("M30 9 V28 Q30 30 28 30 H9", 2.4)
               + rect(14, 14, 11, 11, 0.6, 1)),
    "OIL_PAINT": (fill("M8 24 C11 20 15 26 19 22 C23 18 26 25 31 21 L31 28 C26 32 22 26 18 30 C14 33 11 28 8 31 Z", 0.5)
                  + fill("M21 6 L27 6 L27 13 L21 13 Z") + p("M21 13.5 L20.5 16 H27.5 L27 13.5", 1.4)
                  + p("M24 16 V19", 2.6)),
    # ---------------------------------------------------------------- Digital
    "CHROMATIC_ABERRATION": circ(16, 19.5, 8, 0.5, True) + circ(23, 19.5, 8, 0.5, True) + circ(19.5, 19.5, 8, 1.0, True, 2.2),
    "DIGITAL_NOISE": _noise_squares(11),
    "CRT_SCANLINES": (p("M9 8 H30 Q33 8 33 11 V26 Q33 29 30 29 H9 Q6 29 6 26 V11 Q6 8 9 8 Z")
                      + s("M10 12.5 H29 M10 16.5 H29 M10 20.5 H29 M10 24.5 H29", 1.6) + p("M14 33 H25", 2)),
    "ASCII_MATRIX": _textellation(),
    "ASCII": (rect(6, 8, 27, 23, 0.5, 3, True, 1.4) + p("M10 14 L14 17.5 L10 21", 2) + text(24, 25, "A#", 9.5, 1.0)),
    # ---------------------------------------------------------------- Film
    "SOLARIZE": rect(7, 7, 25, 25, 0.5, 3, True, 1.4) + s("M8 31 L31 8", 1.2, 'stroke-dasharray="2 2"') + p("M8 31 L19.5 9 L31 31", 2.2),
    "FILM_FADE": (GRAD_RL
                  + grect(6, 12, 27, 15, 1.0, 1, "g")
                  + "".join(rect(7 + i * 5.4, 7.5, 3, 2.6, 0.5, 0.6) + rect(7 + i * 5.4, 29, 3, 2.6, 0.5, 0.6) for i in range(5))),
    "GRAIN": _grain(5),
    "PAPER_FIBERS": rect(7, 7, 25, 25, 0.5, 3, True, 1.4) + _fibers(9),
    # ---------------------------------------------------------------- Magic
    "CHROMA_KEY": (rect(7, 7, 25, 25, 0.35, 3) + circ(19.5, 15, 4.5, 1.0)
                   + fill("M10.5 32 C10.5 25 14 21.5 19.5 21.5 C25 21.5 28.5 25 28.5 32 Z")),
    "INVERT": ('<defs><mask id="m"><rect x="0" y="0" width="39" height="39" fill="#fff"/>'
               '<circle cx="19.5" cy="19.5" r="7" fill="#000"/></mask></defs>'
               + rect(7, 7, 12.5, 25, 1.0, 0, extra='mask="url(#m)"')
               + fill("M19.5 12.5 a7 7 0 0 1 0 14 Z") + rect(7, 7, 25, 25, 1.0, 3, True, 1.6)),
    "UNSHARP_MASK": s("M6 31 L19.5 6 L33 31", 1.4) + p("M9.5 31 L19.5 12 L29.5 31", 2.2) + p("M7 31 H32", 1.6),
    "THRESHOLD": _histogram(threshold=19) + p("M19 6 V33", 1.6),
    "COLOR_ISOLATE": "".join(circ(11 + i * 8.5, 11 + j * 8.5, 3.2, 0.4, True, 1.4)
                             for j in range(3) for i in range(3) if (i, j) != (1, 1)) + circ(19.5, 19.5, 4.2),
    # ---------------------------------------------------------------- Posterize family
    "FAMILY_POSTERIZE": ('<defs><clipPath id="c"><circle cx="19.5" cy="19.5" r="12"/></clipPath></defs>'
                         '<g clip-path="url(#c)">' + rect(7, 7, 25, 8.5, 1.0) + rect(7, 15.5, 25, 8, 0.6)
                         + rect(7, 23.5, 25, 9, 0.3) + "</g>"),
    "POSTERIZE": ('<defs><clipPath id="c"><circle cx="19.5" cy="19.5" r="12"/></clipPath></defs>'
                  '<g clip-path="url(#c)">' + rect(7, 7, 25, 8.5, 1.0) + rect(7, 15.5, 25, 8, 0.6)
                  + rect(7, 23.5, 25, 9, 0.3) + "</g>"),
    "SMOOTH_TOON": (circ(19.5, 19.5, 11.5, 1.0, True) + fill("M24 9.5 a11.5 11.5 0 0 1 0 20 a13 13 0 0 0 0 -20 Z", 0.5)
                    + fill("M19.5 31 a11.5 11.5 0 0 0 11.5 -11.5 a9 9 0 0 1 -11.5 11.5 Z", 0.5) + circ(14.5, 14.5, 2.4)),
    # ---------------------------------------------------------------- Misc / stack only
    "LAYER_BLEND": (rect(7, 7, 16, 16, 0.4, 2.5) + rect(16, 16, 16, 16, 0.4, 2.5) + rect(16, 16, 7, 7, 1.0)
                    + rect(7, 7, 16, 16, 1.0, 2.5, True, 1.4) + rect(16, 16, 16, 16, 1.0, 2.5, True, 1.4)),
    "EDGE_DISTANCE_MASK": (rect(14, 14, 11, 11, 1.0, 2) + rect(10, 10, 19, 19, 0.6, 4, True, 1.6)
                           + rect(6.5, 6.5, 26, 26, 0.3, 5.5, True, 1.6)),
    # ---------------------------------------------------------------- Mesh · Camera & layout
    "CAMERA_SCALE_LOCK": (p("M7 12 H22 Q24 12 24 14 V24 Q24 26 22 26 H9 Q7 26 7 24 Z") + p("M24 16 L31 12 V26 L24 22")
                          + rect(23, 28, 9, 6, 1.0, 1) + s("M25 28 V26 a2.5 2.5 0 0 1 5 0 V28", 1.4)),
    "CAMERA_BILLBOARD": (p("M6 15 H14 Q15.5 15 15.5 16.5 V22.5 Q15.5 24 14 24 H6", 1.8) + p("M15.5 17.5 L19 15.5 V23.5 L15.5 21.5", 1.8)
                         + rect(25, 9, 7, 21, 0.5, 1) + rect(25, 9, 7, 21, 1.0, 1, True, 1.6)
                         + s("M20 19.5 H23", 1.6) + poly([(23, 17), (25.5, 19.5), (23, 22)], 0.6)),
    "MIRROR": (s("M19.5 6 V33", 1.4, 'stroke-dasharray="2 2"') + poly([(16.5, 10), (16.5, 29), (7, 29)])
               + p("M22.5 10 V29 H32 Z", 1.8)),
    "MOTION": (s("M8 30 Q10 14 22 16", 1.6, 'stroke-dasharray="2.2 2.2"') + circ(13, 22, 2.2, 0.3) + circ(17, 17.5, 2.6, 0.55)
               + circ(26, 14, 5)),
    "INFINITE_ROTATION": (p("M19.5 19.5 C15 13 7 13 7 19.5 C7 26 15 26 19.5 19.5 C24 13 32 13 32 19.5 C32 26 24 26 19.5 19.5 Z", 2.2)
                          + poly([(26, 11), (30.5, 13.5), (26.5, 17)], 1.0)),
    "LAYERED_ECHO": rect(6, 13, 13, 13, 0.3, 2) + rect(13, 13, 13, 13, 0.6, 2) + rect(20, 13, 13, 13, 1.0, 2),
    "FRAME_STACK": (poly([(19.5, 23), (32, 28), (19.5, 33), (7, 28)], 0.3) + poly([(19.5, 16), (32, 21), (19.5, 26), (7, 21)], 0.6)
                    + poly([(19.5, 7), (32, 12), (19.5, 17), (7, 12)], 1.0)),
    # ---------------------------------------------------------------- Mesh · Deform
    "LATTICE": (p("M8 9 Q19.5 13 31 9 Q27 19.5 31 30 Q19.5 26 8 30 Q12 19.5 8 9 Z", 1.8)
                + s("M19.5 11 Q17.5 19.5 19.5 28 M10 19.5 Q19.5 17.5 29 19.5", 1.4)
                + circ(8, 9, 2.2) + circ(31, 9, 2.2) + circ(31, 30, 2.2) + circ(8, 30, 2.2)),
    "MESH_WIGGLE": (fill("M8 11 Q13 7 19.5 11 T31 11 Q34 19.5 31 28 Q25 32 19.5 28 T8 28 Q5 19.5 8 11 Z", 0.3)
                    + p("M8 11 Q13 7 19.5 11 T31 11 Q34 19.5 31 28 Q25 32 19.5 28 T8 28 Q5 19.5 8 11 Z")),
    "STOP_MOTION_CRUMPLE": (poly([(8, 10), (16, 7), (23, 11), (31, 8), (29, 18), (32, 28), (22, 31), (14, 28), (7, 31), (10, 20)], 0.3)
                            + p("M8 10 L16 7 L23 11 L31 8 L29 18 L32 28 L22 31 L14 28 L7 31 L10 20 Z", 1.8)
                            + s("M16 7 L18 19 L10 20 M18 19 L29 18 M18 19 L22 31", 1.3)),
    "WIND_BENDER": (p("M20 31 Q20 18 31 9", 2.4) + fill("M20 31 Q20 18 31 9 L33 14 Q24 20 25 31 Z", 0.4)
                    + s("M6 13 H17 M8 19 H16 M6 25 H14", 1.8)),
    "ACCORDION_FOLD": (poly([(7, 12), (13, 9), (13, 27), (7, 30)], 1.0) + poly([(13, 9), (19.5, 12), (19.5, 30), (13, 27)], 0.45)
                       + poly([(19.5, 12), (26, 9), (26, 27), (19.5, 30)], 1.0) + poly([(26, 9), (32, 12), (32, 30), (26, 27)], 0.45)),
    "SURFACE_CONFORM": (fill("M6 32 a13.5 13.5 0 0 1 27 0 Z", 0.35) + p("M5 25 Q8 13 19.5 12 Q31 13 34 25", 2.2)
                        + s("M19.5 5 V9 M12 7 L13.5 10.5 M27 7 L25.5 10.5", 1.4)),
    "IMAGE_RELIEF": (fill("M7 30 L13 19 L17 24 L24 11 L32 30 Z", 0.4) + p("M7 30 L13 19 L17 24 L24 11 L32 30", 1.8)
                     + p("M6 31 H33", 1.8) + circ(12, 11, 2.4, 0.6)),
    # ---------------------------------------------------------------- Mesh · Surface & volume
    "CUTOUT_OUTLINE": (p("M9 29 C4 21 9 9 19 8 C29 7 35 16 31 24 C28 31 18 34 9 29 Z", 2.4)
                       + fill("M12.5 26.5 C9 21 12.5 13 19 12 C26 11.5 30.5 17 28 22.5 C26 27.5 19 30 12.5 26.5 Z", 0.45)),
    "THICKNESS": (poly([(8, 14), (14, 8), (31, 8), (25, 14)], 0.6) + poly([(25, 14), (31, 8), (31, 25), (25, 31)], 0.3)
                  + rect(8, 14, 17, 17, 1.0, 0, True, 1.8)),
    "FELT_FUZZ": _felt(),
    "FIBER_TUFTS": _tufts(),
    "KNIT_CROCHET": _knit(),
    "PAPER_SHARDS": _shards(),
    "GLASS": (rect(7, 7, 25, 25, 0.25, 2) + rect(7, 7, 25, 25, 0.5, 2, True, 1.4)
              + p("M17 18 L8 12 M17 18 L14 7 M17 18 L31 11 M17 18 L27 32 M17 18 L7 25 M17 18 L18 32", 1.4)
              + s("M11 14 L13 21 L21 23 L22 14 Z", 1.2)),
    "CRYSTAL": (poly([(12, 8), (27, 8), (33, 15), (19.5, 32), (6, 15)], 0.3)
                + p("M12 8 H27 L33 15 L19.5 32 L6 15 Z", 1.8) + s("M6 15 H33 M12 8 L15.5 15 L19.5 8 L23.5 15 L27 8 M15.5 15 L19.5 32 L23.5 15", 1.3)),
    # ---------------------------------------------------------------- Mesh · Artistic / image geometry
    "SCULPT_WAVES": (fill("M6 26 Q11 18 16 24 T26 24 T33 22 V31 H6 Z", 0.35) + p("M6 26 Q11 18 16 24 T26 24 T33 22", 2)
                     + s("M8 18 Q12 12 16.5 16.5 T25 16 T31 14.5", 1.6) + s("M10 11 Q13.5 7 17 10 T24 9.5 T29 8.5", 1.3)),
    "KINETIC_TILES": _kinetic(),
    "SPHERE_SCREEN": _iso_cube(19.5, 6, 7) + _iso_cube(12.5, 17.5, 6, 0.9, 0.5, 0.3) + _iso_cube(26.5, 17.5, 6, 0.9, 0.5, 0.3),
    "TEXT_MATRIX": _text_matrix(),
}

# Effects Ale chose to keep on their native Blender icon (effects_registry.py).
NATIVE_ONLY = (
    "CROP",
    "EXTEND",
    "WHITE_BALANCE",
    "BRIGHTNESS_CONTRAST",
    "CURVES",
    "PIXELATE",
    "SWIRL",
    "KALEIDOSCOPE",
    "FAMILY_STYLIZE",
    "UNSHARP_MASK",
    "OIL_PAINT",
    "MIRROR",
    "INFINITE_ROTATION",
    "LAYERED_ECHO",
    "LATTICE",
    "MESH_WIGGLE",
    "WIND_BENDER",
    "FELT_FUZZ",
    "FIBER_TUFTS",
    "CRYSTAL",
    "TEXT_MATRIX",
)
for _effect_id in NATIVE_ONLY:
    ICONS.pop(_effect_id, None)

# Effect icons are frameless (Ale's call); the mask icons keep their own frame.
FRAME = ""


def svg(effect_id, scale=1):
    size = 39 * scale
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 39 39">'
            f'{FRAME}{ICONS[effect_id]}</svg>')
