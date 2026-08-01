# Changelog

All notable public changes to Frame By Plane are documented here.

## [7.1.18] — 2026-08-01

### Stability

- Fixed persistent identity for Blender 5.2 native Grease Pencil Shader Effects and modifiers.
- Prevented repeated add actions from creating unmanaged duplicates.
- Restored native Grease Pencil effect removal, reordering, reset, duplicate repair and open-state persistence.
- Fixed Compositor Safe Repair snapshots for Blender 5.2 color, vector and rotation socket values.

### UX and UI

- Added Expand All and Collapse All actions to the Grease Pencil Effect Stack.
- Kept inline effect sections open or closed across redraws and file saves.
- Improved release documentation, search-oriented project wording and Blender 5.2 troubleshooting.

### Validation

- Passed the complete Blender 5.2.0 background regression suite.
- Passed the interactive 300-redraw sidebar stress suite and Preferences reload test.
- Validated the Windows x64 package with Blender's native extension validator.
- Normalized release ZIP metadata so repeated builds produce identical SHA-256 hashes.

## [7.1.17] — 2026-08-01

- Added alphabetic Scrub Bar bookmarks, native color tags and improved bookmark interactions.
- Added bookmark appearance controls and Preview Range activation protection.
- Exposed native Grease Pencil Onion Skin controls in the Viewport popover.

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
