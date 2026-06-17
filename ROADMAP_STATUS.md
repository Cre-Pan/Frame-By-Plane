# Frame by Plane — Roadmap status after 4.8.7

## Completed

- Drag and drop effect ordering.
- Recommended-order warning and automatic fix.
- User preset rename.
- VHS, Soft CRT, Strong Flag and Cardboard Poster presets.
- Icon-only effect dropdown buttons.
- `DOWNARROW_HLT` icon for Effects Stack Actions.
- Warning placed before Presets and Stack Actions.
- Automatic Text Matrix playback limit.
- Expanded project effect statistics.
- Separate viewport/render Text Matrix character estimates.
- Dot Matrix brightness response curve.
- Wind Bender Local/World direction.
- Wind Bender static falloff preview.
- Automatic effects regression scene generated from Settings > Maintenance.
- Regression sources for Image, Sequence, Color and Gradient planes.
- Final Material input source for compatible color effects.
- On-demand effects profiler with real frame/depsgraph timing and Blender process working-set reporting.
- Textellation and Text Matrix light-to-dense glyph mapping corrected.
- Textellation atlas rebuilt with density-sorted built-in character rows.
- Partial alpha interpreted as lighter density; only total transparency is removed by default.
- Source-pixel glyph color enabled by default for Textellation and supported per cell by Text Matrix.
- Text Matrix source-color attribute switches correctly between instanced and realized geometry.
- Regression source images include partial-alpha bands.
- Effect property callbacks update only affected Shader/Geometry Nodes sockets.
- Keyframed and Evolve effects use property-scoped per-frame updates.
- Canonical effect groups, GN interface sockets, Matrix image nodes, font lookup and active effect IDs use transient runtime caches.
- Effect caches are invalidated safely across Undo, file load, datablock removal and unregister.
- Effects-stack synchronization reuses one stack discovery per rig and UI redraws use the synchronized stack mirror between periodic health checks.
- Procedural Color/Gradient Matrix effects reuse canonical groups instead of duplicating image-aware node trees unnecessarily.
- Alpha routing and Text Matrix quality/playback updates avoid redundant graph dirties.
- Text Matrix source sampling rebuilt from normalized point positions instead of unstable Grid index assumptions.
- Independent viewport, render and playback row controls added, with `0` preserving automatic aspect-correct rows.

## Partially completed

- Input Source:
  - Previous Effects, Original Material and Final Material are available for compatible shader effects.
  - Final Material is evaluated as a terminal color pass to avoid cyclic node graphs.
  - Textellation and Text Matrix still read the animated FBP source rather than arbitrary previous shader output.
- Performance profiler and runtime optimization:
  - active effects, heavy effects, generated groups/materials and Text Matrix characters are reported;
  - effect editing, frame evaluation and stack redraw paths now avoid several redundant full-stack and full-interface traversals;
  - the on-demand profiler measures average, median, minimum and maximum frame/depsgraph update times;
  - current Blender process working set and profile memory delta are reported where the operating system exposes them;
  - isolated per-effect timing, GPU memory and precise datablock attribution are not yet available.
- Stabilization:
  - static validation covers effect definitions, generated sockets, registration and migration IDs;
  - the generated regression scene must still be exercised interactively for Eevee/Cycles comparison, mouse drag behavior and long Undo/Redo sessions.

## Still missing

1. Previous Effects for Textellation and Text Matrix.
2. Explicit glyph cache per font and charset.
3. Duplicate the same effect multiple times on one plane.
4. Text Matrix diagnostic views.
5. Crop and Extend diagnostic views.
6. General UV and Alpha previews.
7. Chroma Key garbage mask and more advanced spill suppression.
8. Halftone RGB/CMYK separation.
9. Textellation custom charset and alternative atlases.
10. Per-effect isolated timing and GPU/datablock memory attribution.
11. Desktop regression pass: playback, Eevee/Cycles, save/reopen and extended Undo/Redo.
