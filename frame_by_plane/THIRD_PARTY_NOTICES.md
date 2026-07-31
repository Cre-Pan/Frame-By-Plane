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

Frame By Plane bundles platform-appropriate wheels of **psd-tools 1.17.3** to read
and composite Photoshop PSD/PSB documents locally inside Blender. The extension
uses psd-tools' supported pure-Python RLE fallback when its optional native
acceleration module is unavailable.

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

The PSD backend bundles **typing_extensions 4.15.0**, a pure-Python runtime
dependency used by psd-tools on Python 3.13.

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

## Algorithmic references for Frame By Plane image effects

Frame By Plane independently implements Blender node graphs inspired by established real-time image-processing techniques documented by the following open-source projects. No source file, shader file, binary, or bundled asset from these projects is redistributed in the extension.

- GPUImage — Copyright Brad Larson and contributors — BSD 3-Clause License — Gaussian, selective blur, unsharp-mask and edge-filter research reference.
- glfx.js — Copyright Evan Wallace — MIT License — triangle blur, tilt-shift and real-time image-filter research reference.

The generated Blender node graphs remain part of Frame By Plane and are distributed under the extension's GPL-3.0-or-later license.

## Ink & Line research notes

The Sobel edge, local-average threshold, pencil-sketch and multi-scale edge techniques in this release were independently implemented as Blender shader node graphs from standard image-processing equations. GPUImage (BSD-3-Clause) and glfx.js (MIT) remain algorithmic references only; no source file, shader file or binary from those projects is bundled.

## Warp & Pixel research notes

Swirl, bulge/pinch, radial lens distortion, wave displacement, kaleidoscope folding and staggered mosaic sampling were independently implemented as Blender shader node graphs from standard UV-mapping equations. glfx.js (MIT) remains an algorithmic reference for real-time warp and pixel effects; no JavaScript source, shader file, binary or bundled asset from that project is redistributed.

## Dither & instanced mesh research notes

The ordered Bayer/noise threshold workflow was independently implemented as a
Blender shader-node graph. The open-source **makew0rld/dither** project
(MPL-2.0) was consulted as a correctness and performance reference for ordered
dithering; no Go source, binary or asset is redistributed.

- Project: https://github.com/makew0rld/dither
- License: MPL-2.0

Fiber Tufts and Paper Shards were independently implemented as Geometry Nodes
graphs from Blender's documented Distribute Points on Faces and Instance on
Points contracts. The graphs deliberately keep instances unrealized, following
Blender's open documentation on shared-instance memory and evaluation costs. No
third-party `.blend`, node group, mesh, texture or source file is redistributed.

- Blender Geometry Nodes manual: https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/
- Documentation license: CC-BY-SA-4.0

## Image Solids, Image Relief & Surface Conform research notes

Image Solids, Image Relief and Surface Conform were independently implemented as
native Blender Geometry Nodes graphs. Image Solids transfers source-image color
as a named point attribute before instancing shared sphere, cube, cylinder or
cone geometry. Image Relief samples luminance, inverse luminance, saturation or
a custom depth image on a subdivided UV-preserving mesh, then optionally uses
Blender's native Blur Attribute field to soften the displacement before moving
vertices. Surface Conform uses
relative object coordinates, nearest-surface sampling and normal offset. No
third-party node group, `.blend`, mesh, texture, script or binary is
redistributed.

The open-source **geometry-script** project (GPL-3.0) was consulted only as a
general Geometry Nodes authoring reference; no Python or node-construction code
was copied into Frame By Plane.

- Project: https://github.com/carson-katri/geometry-script
- Blender Geometry Nodes manual: https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/

## Accordion Fold & Array research notes

Accordion Fold and Array are original native Geometry Nodes graphs.
Accordion Fold uses standard triangular-wave mathematics (`asin(sin(x))`) to
deform a subdivided UV-preserving mesh. Array uses Blender's documented Mesh
Line and Instance on Points fields to reuse the textured source geometry without
realizing it at runtime. No third-party node group, `.blend`, script, mesh,
texture or binary is copied or redistributed.

## Sculpt Waves & Kinetic Tiles research notes

Sculpt Waves and Kinetic Tiles are original native Geometry Nodes graphs.
Sculpt Waves combines normalized mesh-position fields with sine, radial and
polar-coordinate mathematics to offer radial, moiré and spiral deformation.
Kinetic Tiles subdivides the original textured plane, separates and scales its
faces, then applies individual face extrusion driven by wave, checker or ripple
fields. Both effects retain source UV and material data and expose independent
viewport, playback and render quality. No third-party node group, `.blend`,
script, mesh, texture or binary is copied or redistributed.

- Blender Geometry Nodes manual: https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/

## Image Projector research notes

The Image Projector is an original Blender Spot-light shader assembled from
native Geometry, Vector Transform, Image Texture and math nodes. It performs a
perspective division in the light's local space and supports Blender image
sequences through `ImageUser`; no third-party projector add-on, shader, asset or
binary is copied or redistributed.
