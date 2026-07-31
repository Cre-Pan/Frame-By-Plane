# Frame By Plane 7.1.11 LTS

Frame By Plane 7.1.11 closes the 7.1 LTS line with a refined Scrub Bar, corrected frame-zero handling for Grease Pencil Drawing Planes, and a reproducible GitHub release pipeline.

## Scrub Bar

- Added **Mouse Magnet**: the persistent Scrub Bar now begins moving toward the cursor when it enters a configurable proximity range.
- Added a smooth attach/release transition instead of an abrupt jump.
- Added Preferences controls for magnet range, strength and smoothing.
- Scrub Bar Preferences now request coalesced Viewport redraws, so Live Preview updates immediately while editing values and colors.
- The bar follows the cursor exactly in the inner magnetic zone while retaining a gradual approach in the outer zone.
- Magnetic movement is frozen during an active scrub or keyframe transform, preventing the axis from drifting under the pointer.
- Momentary `<` scrubbing resets the magnetic displacement and keeps its relative-motion behavior predictable.
- Deactivating the Blender window during a persistent hold now restores the previous persistent view instead of leaving the temporary hold range active.
- The Frame Scrub Slider section in Add-on Preferences now uses its correct custom timeline icon.

## Grease Pencil frame zero

- Creating a Grease Pencil Drawing Plane at frame `0` now creates its first drawing at frame `0`, not frame `1`.
- Frame `0` and negative frames are now preserved throughout GP mask exposure lookup, geometry extraction, reveal evaluation, raster refresh and frame-state caching.
- Scene start frame `0` is no longer treated as a missing value when initializing Grease Pencil exposure timing.

## Startup and Preferences

- Fixed an add-on registration failure caused by the undefined `update_shift_a_menu_position_cb` callback.
- Restored the missing `update_shortcut_preferences_cb` callback before its RNA properties are constructed.
- Shift+A position changes now immediately re-register the menu entry.
- Shortcut preference changes now rebuild the interactive keymaps and redraw the interface.

## Release engineering

- Added deterministic, standard-library release packaging for all five supported platforms.
- Added strict platform wheel isolation and package CRC validation.
- Added tag-to-manifest version checks before publication.
- Added identical common-payload verification across platform packages.
- Added automatic SHA-256 generation for every release archive.
- Added clean source packaging with development reports excluded from installable ZIP files.

## GitHub automation

- Tag pushes matching `v*.*.*` can validate, build, attest and publish a GitHub Release automatically.
- Releases are created as drafts first, assets are uploaded, and publication happens only after every gate succeeds.
- Existing published releases are never overwritten by the workflow.
- Manual workflow runs can build artifacts without publishing them.

## Repository validation

- Updated GitHub Actions to current Node 24-compatible official actions.
- Added release-note, support-policy and manifest synchronization checks.
- Added reproducible package generation to pull-request validation.
- Added regression coverage for Scrub Bar magnet geometry, transition easing, the Preferences icon and Grease Pencil frame `0`.
- Added a class-construction audit that rejects undefined RNA `update=` callbacks before packaging.

## Support policy

- Blender support remains 5.2.x.
- The 7.1 line is frozen for broad feature development after this release.
- Any later 7.1 patch should contain only confirmed regressions or release-infrastructure fixes.
