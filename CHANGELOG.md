# Changelog

All notable changes to Frame By Plane are documented here.

## 5.8.6 — 2026-06-23

### Added

- Custom `Z` Viewport Pie Menu for shading, pivot, visibility, selection, holdout, Crop, Extend, Masks and Quick Effects.
- Up to five configurable Quick Effects.
- Transparent render-background toggle for Eevee and Cycles.
- Universal Hide, Solo, Lock, Selectability and Holdout controls where compatible.
- Automatic viewport framing after successful plane imports.
- Full-black camera Passepartout for newly generated cameras.

### Improved

- Quick Effects dialog simplified to five dropdowns with Reset, Cancel and Apply.
- Pie Menu layout, spacing, button sizing and active-state feedback.
- Layer, rig and object lookup caching in viewport tools.
- Safer keymap registration and cleanup after hot reloads.
- Folder scanning and import-resource handling.
- Package size and repository cleanliness.

### Fixed

- Extrude front and back textures disappearing because `UVMap` was converted to an incompatible vector attribute.
- Extrude side, cap and direction handling.
- Multiple Pie Menu layout regressions and invalid emboss values.
- Duplicate keymaps after interrupted reloads.
- Selection and visibility restoration in Solo, Hide, Lock and Selectability operators.

## Changes introduced since 5.3.0

### Masks

- Square, Circle and Triangle shape masks.
- Color, Gradient and Noise generated masks.
- Alpha Matte and Luma Matte.
- Clipping Mask and per-effect masks.
- Helper visibility, inversion, feather, threshold, softness and debug controls.

### 2D effects

- Recolor with Color Ramp.
- Manual / Depth Blur.
- Rim, Gobo Shadows and Posterize.
- Expanded color, creative, film, paper and display effect categories.

### 2.5D and Geometry Nodes effects

- Extrude rebuilt with alpha-aware geometry, textured caps and directional controls.
- Cutout Outline.
- Camera Scale Lock and Mirror / Camera Billboard.
- Wind Bender, Mesh Ripple, Paper Curl and Infinite Rotation.
- Felt Fuzz and Text Matrix improvements.

### Effects Stack and UI

- Effect folders and clearer 2D, Mask and 3D sections.
- Per-effect masking controls.
- Improved icons, tooltips, disabled states and layout consistency.
- Reduced redundant labels and information rows.

### Performance and stability

- Reduced repeated scene and rig scans.
- Cached effect definitions and Quick Effect lists.
- Safer Undo/Redo, timers, lifecycle registration and hot reload behavior.
- Reduced unnecessary material, node, modifier and RNA updates.
- Removal of obsolete compatibility code and orphaned helpers.
