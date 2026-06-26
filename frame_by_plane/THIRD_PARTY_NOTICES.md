# Third-Party Notices

## Blender-Image-To-ASCII

The Frame By Plane **Ascii** effect adapts the fill/edge atlas concept and uses
`fillASCII.png` and `edgesASCII.jpg` from **Blender-Image-To-ASCII**.

- Author: J. M Areeb Uzair
- Copyright: 2025 J. M Areeb Uzair
- License: MIT
- Source: https://github.com/areebuzair/Blender-Image-To-ASCII

See `licenses/Blender-Image-To-ASCII-MIT.txt`.

## psd-tools

Frame By Plane bundles platform-specific wheels of **psd-tools 1.17.3** to read
and composite Photoshop PSD/PSB documents locally inside Blender.

- Project: psd-tools
- License: MIT
- Source: https://github.com/psd-tools/psd-tools

See `licenses/psd-tools-MIT.txt`.

## Pillow

The layered-document backend bundles **Pillow 12.2.0** for PSD/PSB and
Procreate image decoding plus PNG cache creation.

- Project: Pillow
- License: MIT-CMU
- Source: https://python-pillow.github.io/

See `licenses/Pillow-MIT-CMU.txt`.

## attrs

The PSD backend bundles **attrs 26.1.0**, a runtime dependency of psd-tools.

- Project: attrs
- License: MIT
- Source: https://www.attrs.org/

See `licenses/attrs-MIT.txt`.

## typing_extensions

The PSD backend bundles **typing_extensions 4.15.0**, a runtime dependency of
psd-tools.

- Project: typing_extensions
- License: PSF-2.0
- Source: https://github.com/python/typing_extensions

See `licenses/typing_extensions-PSF-2.0.txt`.

## ProcreateViewer reader

Frame By Plane's experimental `.procreate` metadata and tile decoder is a
modified, defensive adaptation of the MIT-licensed **ProcreateViewer** reader.
The integration adds archive limits, a pure-Python LZ4 block decoder, group
best-effort parsing, cache manifests and Frame By Plane Multiplane metadata.

- Project: ProcreateViewer
- Copyright: 2026 ProcreateViewer
- License: MIT
- Source: https://github.com/NothingData/ProcreateViewer

See `licenses/ProcreateViewer-MIT.txt`.

## Algorithmic references for Frame By Plane 6.0.12

Frame By Plane 6.0.12 independently implements Blender node graphs inspired by established real-time image-processing techniques documented by the following open-source projects. No source file, shader file, binary, or bundled asset from these projects is redistributed in the extension.

- GPUImage — Copyright Brad Larson and contributors — BSD 3-Clause License — Gaussian, selective blur, unsharp-mask and edge-filter research reference.
- glfx.js — Copyright Evan Wallace — MIT License — triangle blur, tilt-shift and real-time image-filter research reference.

The generated Blender node graphs remain part of Frame By Plane and are distributed under the extension's GPL-3.0-or-later license.


## Frame By Plane 6.0.13 Ink & Line research notes

The Sobel edge, local-average threshold, pencil-sketch and multi-scale edge techniques in this release were independently implemented as Blender shader node graphs from standard image-processing equations. GPUImage (BSD-3-Clause) and glfx.js (MIT) remain algorithmic references only; no source file, shader file or binary from those projects is bundled.

## Frame By Plane 6.0.14 Warp & Pixel research notes

Swirl, bulge/pinch, radial lens distortion, wave displacement, kaleidoscope folding and staggered mosaic sampling were independently implemented as Blender shader node graphs from standard UV-mapping equations. glfx.js (MIT) remains an algorithmic reference for real-time warp and pixel effects; no JavaScript source, shader file, binary or bundled asset from that project is redistributed.

