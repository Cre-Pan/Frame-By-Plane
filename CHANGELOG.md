# Changelog

All notable public changes to Frame By Plane are documented here.

## [7.1.11] — 2026-07-31

### Scrub Bar

- Added gradual Mouse Magnet behavior to the persistent Scrub Bar.
- Added magnet range, strength and smoothing controls.
- Restored the correct custom Scrub Bar icon in Add-on Preferences.
- Fixed persistent hold cleanup after Blender window deactivation.

### Grease Pencil

- Preserved frame `0` and negative frames when creating and evaluating Grease Pencil Drawing Planes and masks.

### Distribution

- Added deterministic GitHub release automation and release-gate validation.
- Added reproducible five-platform packages, source archive and SHA-256 checksums.

## [6.1.0] — 2026-06-26

### Stable native workflow

- Promoted the 6.1 branch to **6.1 LTS**.
- Consolidated image and sequence playback around Blender’s native image-texture backend.
- Improved reliability for alpha, timing, loop modes, layer selection and project reopening.
- Refined single-plane, folder and multiplane imports.

### Effects and compositing

- Expanded and normalized the built-in registry to **62 effects**.
- Improved distortion, blur, color, stylization, masking and utility effect families.
- Refined alpha-aware masks, layer blend modes and effect ordering.
- Improved geometry-based cutout and thickness workflows.

### Interface and workflow

- Polished Layer List, Effects, Project, Camera, Render and Developer sections.
- Added clearer tooltips, diagnostics and copyable error reporting.
- Improved controls for selection, visibility, folders, blend modes and linked effect controllers.

### Reliability and performance

- Added autonomous developer tests and stricter release-gate checks.
- Improved save/reopen, undo/redo and Eevee/Cycles regression coverage.
- Removed obsolete code, redundant assets and orphaned release files.
- Reduced download size with platform-specific packages containing only compatible Python wheels.

### Distribution

- Added dedicated packages for Windows x64, Windows ARM64, macOS x64, macOS ARM64 and Linux x64.
- Kept an optional universal package containing dependencies for every supported platform.

## [6.0.0] — 2026-06-24

- Established the 6.0 generation with expanded effects, layered imports, masks, blend modes, cutout tools, camera workflows and developer diagnostics.
