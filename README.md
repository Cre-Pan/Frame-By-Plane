# 🎞️ Frame By Plane

**Frame By Plane works like Blender’s native “Image as Planes”, but is built for animation, layered artwork and 2.5D multiplane workflows.**

Import images, image sequences, folders, PSD files and Procreate projects as controllable planes. Organize layers, edit timing, apply masks and blend modes, add non-destructive effects, build camera depth and render directly inside Blender.

[Download from Blender Extensions](https://extensions.blender.org/add-ons/frame-by-plane/) · [Open the latest GitHub release](../../releases/latest)

## Highlights

- 🎬 Native image-sequence playback with Loop, Ping-Pong and One Shot modes.
- 🗂️ Single-plane and multiplane imports from images, folders and layered projects.
- 🧩 PSD and Procreate layer workflows with alpha preservation.
- 🎨 62 built-in effects covering distortion, blur, color, stylization, masks and utilities.
- 🌓 Layer blend modes inspired by common painting and compositing applications.
- ✂️ Cutout, alpha-aware geometry and 2.5D depth tools.
- 🎥 Camera, project, render and sequence controls designed for animation.
- 🧪 Integrated diagnostics, regression checks and release-gate tools.
- 📦 Separate lightweight packages for Windows, macOS and Linux.

## Requirements

- **Blender 5.1.2 or newer**
- Supported packages:
  - Windows x64
  - Windows ARM64
  - macOS Intel x64
  - macOS Apple Silicon ARM64
  - Linux x64

## Installation

1. Open the [latest GitHub release](../../releases/latest).
2. Download the ZIP matching your computer.
3. In Blender, open **Edit → Preferences → Get Extensions**.
4. Open the menu in the top-right corner and choose **Install from Disk**.
5. Select the downloaded ZIP without extracting it.

| Computer | Release asset |
|---|---|
| Most Windows PCs | `frame_by_plane-6.1.0-windows_x64.zip` |
| Windows on ARM | `frame_by_plane-6.1.0-windows_arm64.zip` |
| Apple Silicon Mac | `frame_by_plane-6.1.0-macos_arm64.zip` |
| Intel Mac | `frame_by_plane-6.1.0-macos_x64.zip` |
| 64-bit Linux | `frame_by_plane-6.1.0-linux_x64.zip` |

> [!IMPORTANT]
> Do not install GitHub’s automatically generated **Source code (zip)** archive. Use one of the installable release assets listed above.

## Main effect families

<details>
<summary>View the built-in effect groups</summary>

- **Distortion and geometry:** Pixelate, Hex Pixelate, Mosaic Jitter, Swirl, Bulge/Pinch, Lens Warp, Wave Warp, Ripple, Kaleidoscope, Wind Bender, Thickness and camera-facing utilities.
- **Color and light:** Recolor, White Balance, Curves, Color Isolate, Gradient Light, Rim, Shadow, False Color, Solarize, Tritone and Film Fade.
- **Blur and detail:** Depth Blur, Gaussian Blur, Directional Blur, Triangle Blur, Tilt Shift and Unsharp Mask.
- **Stylization:** Ink, Edge Work, Pencil Sketch, Poster Edges, Crosshatch, Emboss, Halftone, Dot Matrix, ASCII, ASCII Matrix and Text Matrix.
- **Masks and compositing:** Alpha Matte, Luma Matte, shape masks, clipping/imported masks, Color Mask, Luminance Mask, Channel Mask, Gradient Mask, Noise Mask, Chroma Key and Layer Blend.

</details>

## Repository structure

```text
frame_by_plane/       Blender extension source and bundled wheels
.github/              Issue templates and validation workflow
docs/                 Installation and release documentation
tools/                Local validation and build scripts
release-notes/        Copy-ready GitHub release notes
```

## Build locally

Blender can generate one optimized package for each declared platform:

```bash
blender --command extension build \
  --source-dir ./frame_by_plane \
  --output-dir ./dist \
  --split-platforms
```

Windows users can run `tools/build_release.ps1`; macOS and Linux users can run `tools/build_release.sh`.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Bug reports should include Blender version, operating system, reproduction steps and the Frame By Plane diagnostic report when available.

## License

Frame By Plane is released under the **GNU General Public License v3.0 or later**. Bundled third-party components retain their original licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
