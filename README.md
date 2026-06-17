# Frame by Plane 4.8.7

## 4.8.7 Text Matrix sampling and grid controls

- Rebuilds Text Matrix with position-normalized image coordinates instead of assuming a Mesh Grid point-index order. This fixes transposed, rotated-looking and scrambled source sampling.
- Adds independent **Columns** and **Rows** controls for viewport, render and playback. A row value of `0` keeps aspect-correct automatic rows.
- Updates both grid dimensions in one evaluation when changing quality presets or playback limits.
- Forces stale Text Matrix Geometry Nodes groups to rebuild through the new `frame_by_plane.text_matrix.487` asset ID.
- Keeps render-time column and row overrides lossless and restores the original modifier values after rendering.
- Updates Text Matrix cell estimates and regression defaults for manual rows.

## 4.8.6 Effect nodes and performance

- Updates only the shader or Geometry Nodes sockets affected by the edited property instead of rewriting the complete effect interface on every slider movement.
- Pushes only keyframed or Evolve-driven properties during frame changes.
- Avoids repeated alpha/image synchronization during unrelated effect edits and batches plane update tags.
- Caches canonical effect groups, Geometry Nodes interface sockets, Matrix source-image nodes, the built-in font and synchronized effect IDs.
- Clears every RNA-bearing cache before Undo, file replacement and module teardown.
- Reuses canonical Dot Matrix and Textellation groups for procedural Color/Gradient materials that do not need a private image binding.
- Makes alpha relinking idempotent and invalidates group caches before node-group removal.
- Reduces repeated modifier/material/node-tree scans while synchronizing or drawing the Effects stack.
- Text Matrix quality and playback transitions now perform one scoped Geometry Nodes update.
- Preserves Mesh Wiggle Seed/Unique Seed dependency on the effective `W` socket.

## 4.8.5 Textellation and Text Matrix correctness

- Corrects the luminance direction shared by Textellation and Text Matrix: white now selects light or blank glyphs, while black selects dense glyphs.
- Rebuilds the 32-column Textellation atlas with every built-in character row sorted by measured raster density.
- Keeps both Matrix effects on the same character levels when Character Count changes.
- Composites partial source alpha over white for glyph selection. By default, only exactly transparent cells disappear; partial alpha changes density instead of glyph opacity.
- Enables source-pixel glyph color by default in both effects.
- Text Matrix stores one sampled color per cell and reads it from the instancer or realized geometry as appropriate.
- Prevents stale packed atlases from older `.blend` files from being reused after an extension update.
- Extends the generated regression pattern with opaque, partially transparent and fully transparent source regions.
- Cleans compact duplicate statements and version-specific temporary paths.

## 4.8.4 Final Material and performance profiling

- Adds **Final Material** as a third Input Source for compatible color effects.
- Final Material effects are evaluated after the regular color stack, preserving an acyclic shader graph while keeping their relative order.
- Copy, paste, reset and multi-layer effect workflows preserve the new source mode.
- Adds **Run Effects Profiler** under Settings > Maintenance.
- The profiler performs a warm-up pass, measures real frame/depsgraph update times, records average/median/min/max values and reports Blender's process working set where supported.
- The latest timing and memory results are shown in Project Statistics and written to `FBP_Effects_Profiler_Report` in the Text Editor.
- Textellation and Text Matrix continue to use their synchronized native image/sequence source; arbitrary previous-shader sampling remains a separate roadmap item.

## 4.8.3 Regression and effect-control update

- Uses `DOWNARROW_HLT` for the icon-only **Effects Stack Actions** menu.
- Adds **Dot Matrix Brightness Response**, an exponent curve that controls how source luminance maps to dot size and brightness.
- Adds **Wind Bender Direction Space** (`Local` / `World`), editable wind direction and a static pinned-falloff preview.
- Rebuilds Dot Matrix and Wind Bender with new 4.8.3 asset IDs so stale saved groups migrate automatically.
- Adds **Create Effects Regression Scene** under Settings > Maintenance.
- The generated scene includes Image, Sequence, Color and Gradient sources, representative procedural-source stacks, and one safe test layer for every registered effect.
- Writes a regression report to the Blender Text Editor and uses reduced settings for very heavy effects.

## 4.8.1 Effect stack workflow

- Drag effects vertically from the grip handle to reorder their real shader or Geometry Nodes chain.
- Cancel an active drag with Esc or right-click to restore the original order.
- Rename saved user presets directly from the preset menu.
- Compact warnings identify effects that differ from the recommended chain order.
- Added VHS, Soft CRT, Strong Flag and Cardboard Poster presets.

## 4.8.0 Creative effects refinement

- Rebuilds **Halftone** with Circle, Square, Diamond and Line shapes, independent ink/background colors, transparent background and luminance/mask diagnostic previews.
- Rebuilds **Dot Matrix** with image-driven minimum/maximum dot size, selectable shapes, dead pixels, flicker, independent random fields and debug views.
- Extends **Textellation** with edge emphasis, dithering and luminance/glyph-index previews while preserving animated FBP source synchronization.
- Expands **Wind Bender** with pinned-edge falloff, adjustable turbulence scale, procedural gusts and refined Sway/Flowing Waves behavior.
- Adds effect-cost statistics, heavy-effect counts and estimated Text Matrix viewport cells to Project Statistics.

## 4.7.1 Effect stack workflow

- Adds built-in and user effect presets, saved in the Blender configuration directory without duplicating materials or node groups.
- Adds Copy Active Effect, Copy Stack, Paste Stack, Reset, Clear and Recommended Order actions.
- Paste Stack restores shader-stage and Geometry Nodes modifier order while preserving unrelated Blender modifiers.
- Adds diagnostic previews for Chroma Key, Halftone, Dot Matrix and Textellation.
- Copies viewport/render visibility, input source and complete procedural animation state.

## 4.7.0 Advanced stack and Text Matrix performance

- Image effects can read either the **original material color** or the output of **previous effects** in the stack.
- Text Matrix adds Draft, Preview, Final and Custom quality profiles with independent viewport/render column counts.
- Render-time Text Matrix resolution is applied temporarily and restored after render completion or cancellation.
- Refines effect ordering and keeps the stored rig order synchronized with every material using the effect chain.

## 4.6.10 Stability baseline

- Audits generated shader and Geometry Nodes groups, required sockets, cleanup, visibility, duplication and stale-datablock migration.
- Keeps viewport-eye and render-camera states independent during rebuilds and renders.
- Removes private generated groups and materials only when they are no longer used.
- Preserves compatibility with projects created by the 4.6.x Matrix releases.

## 4.6.9 Animated source and procedural-noise fixes

- Renames **ASCII Matrix** to **Textellation** while preserving old `.blend` compatibility.
- Textellation now follows the evaluated ImageUser of the native FBP material, including animated image sequences, One Shot, Loop and Ping-Pong timing.
- Text Matrix refreshes both the source image datablock and explicit Geometry Nodes frame input, so glyph density follows the current animated plane frame.
- Text Matrix and Textellation map source luminance to the active character gradient; lighter and denser glyphs change with the image zones instead of remaining frozen.
- Replaces the old cyclic Evolve clock with deterministic non-repeating procedural noise. `Stepped` controls how many frames each random value is held; `Seed` selects the stream; `Unique per Layer` separates layers.
- Rebuilds Textellation and Text Matrix node groups with 4.6.9 asset IDs to remove stale cached groups from older files.

## Previous 4.6.x notes

## 4.6.8 Effects reliability pass

- Keeps viewport-eye and render-camera visibility independent after add, repair, duplication and material rebuilds.
- Clears both visibility states when an effect is removed, avoiding stale camera settings after re-adding it.
- Copies render visibility and complete procedural animation settings when duplicating an effect to selected layers.
- Rebuilds Dot Matrix with independent size/brightness random fields and a safe zero-glow hard-edge mode.
- Makes Textellation character variation scale with the active character range instead of using a fixed jump.
- Forces Text Matrix to sample discrete cell centers with Closest interpolation and avoids writing alpha-mask sockets that the group does not expose.
- Bumps Matrix asset IDs so stale 4.6.7 groups are migrated automatically.

## 4.6.7 Matrix and effect-node validation update

- Rebuilds **Dot Matrix** around cell-centered image sampling: source luminance now drives both dot area and brightness; random controls only add optional variation.
- Keeps **Textellation** as the fast shader/atlas effect and forces stable cell-center sampling from the current FBP image.
- Keeps **Text Matrix** exclusively in **Mesh Effects** as Geometry Nodes-generated vector text.
- Rebuilds Text Matrix with explicit per-glyph selection branches for reliable Blender 5.1 field evaluation.
- Corrects Text Matrix character scale to use physical cell width, preventing overlapping glyphs on wide planes.
- Preserves independent text/background materials, transparent background, Blender font selection, custom character sets and optional realization.
- Adds strict migration IDs for Dot Matrix, Textellation and Text Matrix so stale 4.6.6 groups are rebuilt automatically.
- Validates every effect group, every required socket, shader stacking, Geometry Nodes evaluation, alpha-aware private groups, add/remove cleanup and package registration.

## 4.6.6 Matrix and procedural animation update

- Restores the visible Procedural Seed / Evolve controls for Digital Noise.
- Adds deterministic Seed/Evolve controls, transparent backgrounds and independent foreground/background colors to the Matrix effects.
- Expands Textellation to sixteen character-gradient presets plus a larger 32×16 bundled atlas.
- Adds Text Matrix: real vector glyph geometry generated from image luminance, with Blender font selection, custom characters, text/background materials and alpha-aware cell removal.


## UX / UI

- Newly added effects are selected automatically and moved to the beginning of their compatible stack.
- Separate viewport eye and render camera controls for effects.
- Context-aware disabled move, duplicate, remove and generation controls.
- Compact icon-based effect toolbar and cleaner panels.
- Added duplicate-to-selected action for partial multi-layer effect stacks.
- Removed non-essential informational rows and corrected collapsible-section styling.

# Frame by Plane 4.6.1

Frame by Plane imports images, videos and native image sequences as rigged planes for multiplane animation in Blender.

## 4.6.1 stability pass

- Rebuilds all generated 4.6 shader and Wind Bender groups with new 4.6.1 asset identifiers.
- Prevents Blender files from silently reusing stale or incomplete generated node groups.
- Validates required group inputs and outputs before an effect is inserted.
- Removes only newly-created orphan node groups when a procedural builder fails.
- Keeps existing user node groups and active materials untouched during recovery.

## Effects workspace

Effects are now organized into three parallel stacks:

- **Base** — Crop, Extend, Chroma Key and color controls.
- **2D** — image-processing and graphic effects.
- **3D** — Geometry Nodes deformation and surface effects.

Every effect includes a detailed tooltip with compatibility and viewport-cost information. Effects marked Heavy or Very Heavy also show a performance warning.

## New effects

- **Digital Noise** — separate luminance and chromatic high-ISO noise with shadow bias.
- **Chroma Key** — tolerance, softness, despill and invert controls with generated alpha.
- **Halftone** — luminance-driven printed-dot conversion.
- **Dot Matrix** — adjustable spacing, dot size, random size, glow and background.
- **Textellation** — character mosaic using Classic, Numbers, Symbols or Binary sets.

## Updated effects

- Most 2D effects can now process Image, Image Sequence, Color and Gradient planes.
- **Pixelate** produces aspect-correct square blocks by default and exposes Pixel Density.
- **Wind Bender** supports Left, Right, Top or Bottom pinning and two motion modes:
  - Sway
  - Flowing Waves
- Wind Bender adds wave count, amplitude, speed, phase, turbulence and reverse direction.
- Crop and Extend moved into the Base effects stack; the previous standalone tools box was removed.

## Stability inherited from 4.5.x

- Fixed generation getting stuck on “Generating Frame By Plane Sequence”.
- Restored reliable deferred generation behavior from 4.5.7.
- Fixed Shift+D duplication for Color, Gradient, Image, Sequence, Holdout and multi-layer selections.
- Fixed procedural material opacity updates during duplication.

## Requirements

- Blender **5.1.0 or newer in the 5.1 series**
- Primary target: Blender **5.1.2**
