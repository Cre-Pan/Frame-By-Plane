# Frame By Plane — Blender 5.2 Image Sequence & Grease Pencil Add-on

**Frame By Plane is a Blender 5.2 LTS add-on for image-sequence animation, Grease Pencil, layered PSD and Procreate artwork, 2.5D multiplane scenes, compositing and non-destructive effects.**

It works like Blender's native **Images as Planes**, but adds production controls for timing, layers, masks, camera depth, rendering and frame-by-frame animation workflows.

[Download from Blender Extensions](https://extensions.blender.org/add-ons/frame-by-plane/) · [Download the latest GitHub release](../../releases/latest) · [Read the GitHub Wiki](../../wiki)

## What's new in 7.1.18 LTS

- Fixed persistent ownership for all 27 native Grease Pencil effect backends on Blender 5.2.
- Prevented unmanaged duplicate Shader Effects and Grease Pencil modifiers.
- Restored reliable add, remove, reorder, reset and duplicate-repair actions.
- Added **Expand All** and **Collapse All** controls for the Grease Pencil Effect Stack.
- Fixed Compositor Safe Repair snapshots for Blender 5.2 color, vector and rotation socket values.
- Passed native Blender 5.2.0 background tests and a 300-redraw interactive UI stress test.

See the complete [7.1.18 release notes](release-notes/7.1.18.md).

## Core features

### Image sequences and frame-by-frame animation

- Import still images, numbered image sequences, folders and video as controllable planes.
- Use Loop, Ping-Pong and One Shot playback with timeline and frame-offset controls.
- Scrub and edit Grease Pencil timing from the Viewport with bookmarks, preview range and onion-skin controls.

### Layered artwork and 2.5D multiplane scenes

- Import layered PSD and Procreate projects while preserving transparency and layer structure.
- Arrange artwork in camera depth for parallax, multiplane animation and motion-comic workflows.
- Manage layer visibility, folders, blend modes, clipping, holdouts and alpha-aware cutouts.

### Grease Pencil, masks and effects

- Create Drawing Planes linked to image layers or use independent Grease Pencil canvases.
- Apply native Blender Grease Pencil modifiers and Shader Effects from one compact stack.
- Build shape, color, luminance, channel, gradient, noise, imported and Grease Pencil masks.
- Use non-destructive distortion, blur, color, light, stylization and compositing effects.

### Compositing, camera and rendering

- Build Blender-native compositor layer packages while preserving artist-created nodes and links.
- Use Safe Repair, diagnostics and rollback-aware project health tools.
- Control camera-facing planes, projectors, render output and image-sequence delivery inside Blender.

## Requirements

- **Blender 5.2.x LTS**
- Windows x64 or ARM64, macOS Intel or Apple Silicon, or Linux x64

## Install Frame By Plane

1. Open the [latest GitHub release](../../releases/latest).
2. Download the ZIP matching your computer.
3. In Blender, open **Edit → Preferences → Get Extensions**.
4. Open the menu in the top-right corner and choose **Install from Disk**.
5. Select the downloaded ZIP without extracting it.

| Computer | Release asset |
|---|---|
| Most Windows PCs | `frame_by_plane-7.1.18-windows_x64.zip` |
| Windows on ARM | `frame_by_plane-7.1.18-windows_arm64.zip` |
| Apple Silicon Mac | `frame_by_plane-7.1.18-macos_arm64.zip` |
| Intel Mac | `frame_by_plane-7.1.18-macos_x64.zip` |
| 64-bit Linux | `frame_by_plane-7.1.18-linux_x64.zip` |

> [!IMPORTANT]
> Do not install GitHub's automatically generated **Source code (zip)** archive. Install one of the Frame By Plane release assets listed above.

For a clean update or architecture details, read the [installation guide](docs/INSTALLATION.md).

## Quick start

1. Open the **Frame By Plane** tab in Blender's 3D View sidebar.
2. Choose a single image, sequence, folder, PSD, Procreate file or video.
3. Set timing and playback, then create the layer or multiplane project.
4. Use **Layers**, **Effects**, **Grease Pencil**, **Camera** and **Render** to refine the scene.
5. If a project needs inspection, open **Project Health** and copy the diagnostic report before filing an issue.

## Documentation and support

- [Feature guide](docs/FEATURES.md)
- [Installation and updates](docs/INSTALLATION.md)
- [Blender 5.2 troubleshooting](docs/TROUBLESHOOTING.md)
- [Release process](docs/RELEASING.md)
- [GitHub Wiki](../../wiki)
- [Bug reports and feature requests](../../issues)

Bug reports should include Blender version, operating system, reproduction steps and the Frame By Plane diagnostic report when available. Frame By Plane does not send telemetry or project data.

## Repository structure

```text
frame_by_plane/       Blender extension source, tests, assets and bundled wheels
.github/              Issue templates and validation workflow
docs/                 Installation, features, troubleshooting and release docs
tools/                Repository validation and platform build scripts
release-notes/        Copy-ready GitHub release notes
```

## Build and test locally

Build optimized packages for every declared platform:

```bash
blender --command extension build \
  --source-dir ./frame_by_plane \
  --output-dir ./dist \
  --split-platforms
```

Run the native Blender 5.2 regression suites:

```bash
python frame_by_plane/tests/run_blender_lts.py \
  --blender /path/to/blender \
  --all
```

Windows users can run `tools/build_release.ps1`; macOS and Linux users can run `tools/build_release.sh`.

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Frame By Plane is released under the **GNU General Public License v3.0 or later**. Bundled third-party components retain their original licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
