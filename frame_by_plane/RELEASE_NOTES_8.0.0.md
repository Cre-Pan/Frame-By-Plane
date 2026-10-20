# 🎞️ Frame By Plane — 8.0.0

Frame By Plane 8.0 is a large workflow and reliability update for Blender 5.2 LTS. It includes the Grease Pencil polish prepared as 7.2.1, which was not published on its own.

## 🌀 Deform Plane (Lattice)

- **Poses:** one-click deformations (Sway, Arch, Squash / Stretch, Taper, Shear, Bulge / Pinch, Wave, Flag and Curl), each added as a slider you can keyframe. Sliders mix freely and go from −1 to 1, so Squash becomes Stretch and Sway bends either way. **Custom** adds an empty pose and opens the cage to shape it by hand.
- Presets are exact at any cage density, and a preset that needs more control points refines the cage on its own.
- Changing the **Cage Grid** keeps the current shape, the poses and their animation instead of resetting the cage.
- Fixed: after a grid change the cage grew by the amount of the current deformation.

## 🎯 On-plane controls

- **Gradient Mask**, **Gradient Light** and **Tilt-Shift** handles now line up with the visible effect on non-square images. Existing projects render exactly as before.
- **Radial Gradient Mask** has its own handles (centre, inner and outer radius) and is now a true circle on non-square images instead of an oval.
- Touching a Gradient Light handle no longer resets Shadow Position.
- **Wave Mask** and **Voronoi Mask** get an on-plane arrow to rotate the pattern.

## 🧩 Compositor (Preview)

- **Opening a file no longer adds a compositor.** Earlier versions gave every scene an empty compositor on load, and F12 rendered through it. Files saved that way are cleaned up automatically.
- **Compositor Off really turns it off:** your own compositor, render settings and View Layers come back. The Frame By Plane nodes are kept, and turning it on again resumes the same setup.
- Building the compositor never changes F12 until **Use Compositor in Render** is on.
- New **Compositor | Refresh | Live Update** row: Live Update is off by default, so adding layers or effects no longer rebuilds everything after every click.
- **Color Grade** Temperature and Tint now work, and copied scenes no longer render the original scene's layers.

## ⚡ Performance

- Reordering and adding effects is about twice as fast on large stacks.
- Stacks that mix Image and Mesh effects are about three times faster to edit.

## 🛠️ Effect stack fixes

- **Hide in Render** now works for every Image effect.
- Duplicate places the copy directly above the original, inside the same group.
- Switching a variant (for example Pixelate → Hex Pixelate) keeps its place and replaces only the selected copy.
- Adding an effect with a group selected puts it inside that group.
- Copy / Paste Effect Stack and Effect Stack Presets reproduce the source exactly: order, groups, duplicated effects and local masks.
- Hiding a global mask no longer makes a semi-transparent layer more transparent.
- Masks no longer lose their UV input after effects are moved, removed or sorted.

## ✏️ Grease Pencil (from 7.2.1)

- New Gap Off / On icons with two connected buttons.
- Cleaner color controls, with a visible Swap Colors button in every mode.
- The Scrub Bar is always first in the centered Viewport controls.
- Gap Off correctly opens selected curves when the selection mixes open and closed strokes.

## 📥 Download the correct ZIP

| Computer | Release asset |
|---|---|
| Most Windows PCs | `frame_by_plane-8.0.0-windows_x64.zip` |
| Windows on ARM | `frame_by_plane-8.0.0-windows_arm64.zip` |
| Apple Silicon Mac | `frame_by_plane-8.0.0-macos_arm64.zip` |
| Intel Mac | `frame_by_plane-8.0.0-macos_x64.zip` |
| 64-bit Linux | `frame_by_plane-8.0.0-linux_x64.zip` |

Install the ZIP through **Edit > Preferences > Get Extensions > Install from Disk**. Do not install GitHub's automatically generated Source code ZIP.

> Requires **Blender 5.2.x LTS**. Projects from 7.x open without manual migration.
