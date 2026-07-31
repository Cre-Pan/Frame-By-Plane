"""Color Plane creation names derived from Blender or sRGB colors.

Blender's regular ``COLOR`` RNA subtype stores scene-linear RGB values, while
the hexadecimal field shown by its color picker is sRGB.  The helpers in this
module keep that conversion explicit so callers can also pass web/clipboard
sRGB values without applying gamma twice.
"""

from __future__ import annotations

import colorsys
import math


EXACT_COLOR_OVERRIDES = {
    "#AA2525FF": "Love",
    "#FFA131FF": "Crep",
}

EXACT_BASE_COLORS = {
    "#FF0000FF": "Red",
    "#FFC0CBFF": "Pink",
    "#0000FFFF": "Blue",
    "#00FF00FF": "Green",
    "#FFFF00FF": "Yellow",
    "#000000FF": "Black",
    "#E6E6E6FF": "Pearl",
    "#BFBFBFFF": "Ash",
    "#777777FF": "Mid Grey",
    "#555555FF": "Torino",
    "#222222FF": "Charcoal",
    "#FFFFFFFF": "White",
}

HUE_COLOR_NAMES = (
    ((351, 360), ("Blush", "Red", "Scarlet", "Crimson", "Blood")),
    ((0, 8), ("Blush", "Red", "Scarlet", "Crimson", "Blood")),
    ((9, 26), ("Peach", "Coral", "Terra", "Rust", "Mahogany")),
    ((27, 44), ("Apricot", "Orange", "Pumpkin", "Copper", "Ember")),
    ((45, 62), ("Cream", "Gold", "Honey", "Amber", "Bronze")),
    ((63, 80), ("Butter", "Lemon", "Yellow", "Mustard", "Olive")),
    ((81, 98), ("Tea", "Lime", "Cedro", "Moss", "Swamp")),
    ((99, 116), ("Apple", "Grass", "Leaf", "Fern", "Forest")),
    ((117, 134), ("Celadon", "Spring", "Verde", "Pine", "Bosco")),
    ((135, 152), ("Mint", "Emerald", "Jade", "Malachite", "Bottle")),
    ((153, 170), ("Foam", "Aqua", "Sea", "Teal", "Cypress")),
    ((171, 188), ("Frost", "Turquoise", "Laguna", "Ocean", "Petrol")),
    ((189, 206), ("Ice", "Cyan", "Pool", "Capri", "Ink")),
    ((207, 224), ("Sky", "Azzurro", "Cerulean", "Azure", "Night")),
    ((225, 242), ("Peri", "Royal", "Cobalt", "Navy", "Marine")),
    ((243, 260), ("Lilac", "Indigo", "Iris", "Sapphire", "Midnight")),
    ((261, 278), ("Lavender", "Violet", "Amethyst", "Plum", "Aubergine")),
    ((279, 296), ("Orchid", "Purple", "Magenta", "Mulberry", "Mora")),
    ((297, 314), ("Candy", "Fuchsia", "Cyclamen", "Wine", "Burgundy")),
    ((315, 332), ("Rose", "Pink", "Raspberry", "Cherry", "Garnet")),
    ((333, 350), ("Powder", "Flamingo", "Antique", "Ruby", "Maroon")),
)


def _clamp_unit(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _linear_channel_to_srgb(value):
    value = _clamp_unit(value)
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (value ** (1.0 / 2.4)) - 0.055


def _srgb_channel_to_linear(value):
    value = _clamp_unit(value)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _normalized_hex_text(value):
    raw = str(value or "").strip().lstrip("#")
    if len(raw) in {3, 4}:
        raw = "".join(character * 2 for character in raw)
    if len(raw) == 6:
        raw += "FF"
    if len(raw) != 8 or any(
        character not in "0123456789abcdefABCDEF" for character in raw
    ):
        raise ValueError("Expected an RGB or RGBA hexadecimal color")
    return f"#{raw.upper()}"


def srgb_rgba_to_linear(color):
    """Convert an sRGB numeric RGB/RGBA sequence to Blender scene-linear RGBA."""
    values = tuple(color or ())
    if len(values) not in {3, 4}:
        raise ValueError("Expected three or four color channels")
    alpha = _clamp_unit(values[3]) if len(values) == 4 else 1.0
    return (
        _srgb_channel_to_linear(values[0]),
        _srgb_channel_to_linear(values[1]),
        _srgb_channel_to_linear(values[2]),
        alpha,
    )


def normalize_color_hex(color, *, color_space="LINEAR"):
    """Return uppercase ``#RRGGBBAA`` matching Blender's visible color-picker hex.

    ``color_space='LINEAR'`` is correct for values read from Blender properties
    declared with subtype ``COLOR``.  Use ``'SRGB'`` for web, clipboard or other
    already display-referred numeric colors.  Hex strings are inherently sRGB.
    """
    if isinstance(color, str):
        return _normalized_hex_text(color)

    values = tuple(color or ())
    if len(values) not in {3, 4}:
        raise ValueError("Expected three or four color channels")
    space = str(color_space or "LINEAR").strip().upper()
    if space not in {"LINEAR", "SRGB"}:
        raise ValueError("color_space must be LINEAR or SRGB")
    rgb = tuple(_clamp_unit(value) for value in values[:3])
    if space == "LINEAR":
        rgb = tuple(_linear_channel_to_srgb(value) for value in rgb)
    alpha = _clamp_unit(values[3]) if len(values) == 4 else 1.0
    channels = rgb + (alpha,)
    encoded = tuple(
        max(0, min(255, int(value * 255.0 + 0.5))) for value in channels
    )
    return "#" + "".join(f"{channel:02X}" for channel in encoded)


def _rounded_scale_value(value, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return max(0, min(maximum, int(math.floor(number + 0.5))))


def color_name_from_hsv(hue, saturation, value):
    """Resolve one name from HSV values expressed as degrees and percentages."""
    hue_value = _rounded_scale_value(hue, 360)
    if hue_value == 360:
        hue_value = 0
    saturation_value = _rounded_scale_value(saturation, 100)
    value_value = _rounded_scale_value(value, 100)

    if saturation_value <= 14:
        if value_value >= 95:
            return "White"
        if value_value >= 80:
            return "Pearl"
        if value_value >= 60:
            return "Ash"
        if value_value >= 45:
            return "Mid Grey"
        if value_value >= 25:
            return "Torino"
        if value_value >= 10:
            return "Charcoal"
        return "Black"

    if value_value >= 80:
        variant_index = 0 if saturation_value <= 49 else 1
    elif value_value >= 55:
        variant_index = 2
    elif value_value >= 30:
        variant_index = 3
    else:
        variant_index = 4

    for (minimum, maximum), names in HUE_COLOR_NAMES:
        if minimum <= hue_value <= maximum:
            return names[variant_index]
    return "Color"


def color_plane_name_from_color(color, *, color_space="LINEAR"):
    """Resolve a creation-time Color Plane name from a Blender or sRGB color."""
    normalized = normalize_color_hex(color, color_space=color_space)
    override = EXACT_COLOR_OVERRIDES.get(normalized)
    if override:
        return override
    base_name = EXACT_BASE_COLORS.get(normalized)
    if base_name:
        return base_name
    red = int(normalized[1:3], 16) / 255.0
    green = int(normalized[3:5], 16) / 255.0
    blue = int(normalized[5:7], 16) / 255.0
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    return color_name_from_hsv(
        hue * 360.0,
        saturation * 100.0,
        value * 100.0,
    )


__all__ = (
    "EXACT_BASE_COLORS",
    "EXACT_COLOR_OVERRIDES",
    "HUE_COLOR_NAMES",
    "color_name_from_hsv",
    "color_plane_name_from_color",
    "normalize_color_hex",
    "srgb_rgba_to_linear",
)
