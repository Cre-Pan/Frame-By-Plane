"""Character gradients shared by Textellation and Text Matrix.

Every built-in preset is raster-density sorted from visually light to dense.
Textellation uses a fixed 32-column atlas. Text Matrix samples those same 32 atlas
levels down to a smaller vector-glyph set, so both effects choose matching
characters for the same luminance.
"""

ASCII_ATLAS_COLUMNS = 32
ASCII_ATLAS_CELL_WIDTH = 64
ASCII_ATLAS_CELL_HEIGHT = 80
ASCII_TEXT_GLYPH_LIMIT = 16
ASCII_ATLAS_VERSION = 485
ASCII_ATLAS_REVISION = "4f984a2d07903e02"

# Keep identifiers stable: they are stored in .blend files.
ASCII_PRESETS = (
    ('CLASSIC', 'Classic', 'Mixed letters, numbers, punctuation and graphic symbols', ' .,:;!L11itCf☺G$#8%&BW0♦@★♠♥♣▓▓█'),
    ('ALPHABETIC', 'Alphabetic', 'Alphabetic characters ordered by visual density', ' JcLvzixrYtIljZnoXaekhUwmbOpqdQ0'),
    ('ALPHANUMERIC', 'Alphanumeric', 'Letters and numbers ordered by visual density', ' .cLv7z1ixtClfZ32a54khw96OpqdQg0'),
    ('ARROW', 'Arrow', 'Directional arrows and chevrons', ' .·˂˃←←→↓›‹↑↗↖↘↙↔↕⇒⇐⇓⇑➛➢▶➟➙➔➠➤➤➜'),
    ('CODE_PAGE_437', 'Code Page 437', 'Classic DOS-style blocks and symbols', ' .·▫↕○○▪□░☺●◘▒▲▼◄►♦¶■◙♠♥☻▌▄▀▐♣▓█'),
    ('EXTENDED_HIGH', 'Extended High', 'Accented and extended Latin characters', ' .`´¨:~;¡!^ìíïçîÇÞñøÄðæÜÅßÖÆþÐØÑ'),
    ('GRAY_SCALE', 'Gray Scale', 'A long grayscale ramp from blank to solid', " ':~_!\\^(v}]z1rYCIfnohmbOq#%QW@█"),
    ('MINIMALIST', 'Minimalist', 'Small clean set with broad tonal separation', '      ...---:::+++***==###%%%@@@'),
    ('MATH_SYMBOLS', 'Math Symbols', 'Mathematical operators and notation', ' .·−÷∩+=×≈∨∧∞⊃⊂±≤≥√∪≠∓∫∑∈∀∃∇∂∆∏∉'),
    ('NORMAL', 'Normal', 'Balanced general-purpose ASCII gradient', ' .-:+*=JYZoXakhUwmOpqd$#8&QBW0M@'),
    ('NORMAL_2', 'Normal 2', 'Alternative balanced ASCII gradient', ' .`-,:~;_!+\\/^|()?cv}[]z1xrtfjnu'),
    ('NUMERICAL', 'Numerical', 'Numerals only, repeated by visual density', ' 7711133322255444999666888888000'),
    ('MAX', 'Max', 'Dense high-detail symbols and blocks', ' .,:;░L1itCf◆G●$#8%▒&B0@★■▌▄▀▐▓█'),
    ('BLACK_WHITE', 'Black and White', 'Two-level black-and-white mapping', '                ████████████████'),
    ('BINARY', 'Binary', 'Binary digits for terminal and code looks', '                1111111100000000'),
    ('SYMBOLS', 'Symbols', 'Punctuation and graphic symbols', " .`'-,:~;_<>!+\\/^*=|()?{}[]$#%&@"),
)

ASCII_PRESET_MAP = {identifier: chars for identifier, _label, _description, chars in ASCII_PRESETS}
ASCII_PRESET_ROWS = {identifier: index for index, (identifier, *_rest) in enumerate(ASCII_PRESETS)}
ASCII_ATLAS_ROWS = len(ASCII_PRESETS)
ASCII_ATLAS_SIZE = (
    ASCII_ATLAS_COLUMNS * ASCII_ATLAS_CELL_WIDTH,
    ASCII_ATLAS_ROWS * ASCII_ATLAS_CELL_HEIGHT,
)


def _fit_gradient(value: str, length: int = ASCII_ATLAS_COLUMNS) -> str:
    """Resample a gradient to an exact size while preserving both endpoints."""
    value = str(value or " ")
    length = max(1, int(length))
    if len(value) == length:
        return value
    if len(value) == 1:
        return value * length
    if length <= 1:
        return value[:1]
    last = len(value) - 1
    return "".join(value[round(index * last / (length - 1))] for index in range(length))


def ascii_gradient(identifier: str, *, length: int = ASCII_ATLAS_COLUMNS, custom: str = "") -> str:
    """Return one light-to-dense gradient resampled to ``length`` glyphs."""
    if identifier == "CUSTOM":
        source = custom or " .:-=+*#%@"
    else:
        source = ASCII_PRESET_MAP.get(identifier, ASCII_PRESET_MAP["CLASSIC"])
    return _fit_gradient(source, max(2, int(length)))


def ascii_level_gradient(identifier: str, *, levels: int, custom: str = "") -> str:
    """Return vector glyph levels matching Textellation's raster-atlas picks.

    Built-in presets first become the exact 32 glyphs stored in the atlas and
    are then sampled down. This prevents Text Matrix from selecting subtly
    different characters than Textellation at the same Character Count.
    Custom strings are not atlas-backed and are sampled directly.
    """
    levels = max(2, int(levels))
    if identifier == "CUSTOM":
        return _fit_gradient(custom or " .:-=+*#%@", levels)
    atlas_row = ascii_gradient(identifier, length=ASCII_ATLAS_COLUMNS)
    return _fit_gradient(atlas_row, levels)


def ascii_enum_items(*, include_custom: bool = False):
    items = [
        (identifier, label, description)
        for identifier, label, description, _chars in ASCII_PRESETS
    ]
    if include_custom:
        items.append(("CUSTOM", "Custom", "Use the custom character string below"))
    return tuple(items)
