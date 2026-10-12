# Changelog

All notable public changes to Frame By Plane are documented here.

## [7.5.2] - Unreleased

Version bumped to 7.5.x (7.5.0 was an internal test build).

### Fixes

- The Scrub Bar no longer slides left and right toward the mouse. **Mouse Magnet** in Preferences is now **Precise Range**: the distance from the bar within which scrubbing with `<` follows the pointer exactly.
- The Strokes and Fills dropdowns drew an empty list in Blender 5.2 (the list used a layout type Blender no longer accepts); the color list shows again.
- A pinned Scrub Bar no longer redraws the viewport on every timer tick while the mouse rests in the 3D View; hover updates only redraw when the hovered key or bookmark changes. Timer events are no longer swallowed during a hold, and edge scrolling uses the remembered pointer position.
- Pressing Shift or Ctrl while holding `<` before moving no longer jumps the playhead.
- If the Viewport or object goes away during the return glide, the playhead still lands on the start frame.
- Stroke and Fill swatches live in separate lists, so a change on one side can never make an open color picker edit the other side.
- Swap skips strokes whose material draws only a line or only a fill, instead of painting them with an empty color, and no longer adds an empty Undo step when nothing is selected.
- The Edit Mode header no longer rescans the selection on every redraw before the first sync.
- Choosing a Draw brush from Edit Mode first commits any pending color Undo step.
- Layers left locked by the removed Limited Loop guard in older files are unlocked on load.

### Release splash

- The release splash now opens after every installation of Frame By Plane: a fresh install, an update, or reinstalling the same version, from Blender Extensions or by drag and drop. Starting Blender again does not show it. **Show After Install / Update** in Preferences still turns it off.

### Grease Pencil

- Removed the Frame By Plane Grease Pencil effect list and its grouped effect picker (Reset, Move, Toggle, Repair Duplicates and the compatibility report). Grease Pencil drawings now use Blender's own Modifiers and Visual Effects panels; effects already added to a drawing stay on it as normal Blender effects.
- Removed **Draw on Canvas** (the Draw, Fill and Erase buttons next to a Drawing Plane), the **Ink Over Image** panel, **Create Missing / Current GP Drawings** and **Limited Loop Blocks**. Drawing Timing keeps **Plane → GP**, **GP → Plane**, Offset and Auto Sync.
- **Grease Pencil Drawing** in Shift+A is greyed out until a Frame By Plane plane is selected.
- In Edit Mode, selecting strokes with different colors shows every distinct Stroke and Fill color in the Tool Header (`Stroke colors ⇄ Fill colors`), up to 12 swatches; identical colors share one swatch. With more than 12, the larger side collapses into its own **Strokes** or **Fills** dropdown with a color list, **Replace All** and **Invert with Fill/Stroke**. Changing a swatch recolors only the selected strokes or fills that use that color.
- Only colors that are drawn count: if the selected strokes' material hides fills, the Fill side and the swap button disappear (and the other way round).
- **Swap Stroke / Fill** in Edit Mode now swaps each selected stroke's own colors, instead of painting every stroke with one color.
- Edit Mode's Tool Header has the **Material** selector (with Assign) and a **Draw brush** selector, so both can be changed without leaving Edit Mode.

### Scrub Bar

- Holding **<** now follows the pointer exactly on the Scrub Bar and speeds up as the pointer moves away from it, up to **Far Speed** (Preferences, **Speed Ramp Distance**). Moving only across the bar no longer changes the frame.
- Fixed: after releasing **<** the playhead stayed on the scrubbed frame until the next key press. Blender events carry no timer handle, so the glide never ticked; Scrub Bar edge scrolling and the hover magnet were affected the same way.
- Releasing **<** snaps the playhead back to the frame where you started like a magnet: it accelerates, passes the start frame by a frame or two and settles on it (**Return to Start Frame**, on by default, with **Return Time** and **Bounce**). Any key or click during the glide lands on the start frame at once.
- The Scrub Bar menu in the Viewport header is split into collapsible sections (Scrub Bar, Return to Start, Scrub Speed, Onion Skin, Bookmarks, Preview Range). **Length** is now in the Scrub Bar section, goes down to 10% of the Viewport and updates the bar while it is shown.
- A quick tap of **<** no longer pins the Scrub Bar. Pin it from the Scrub Bar button or its menu in the Viewport header, or turn **Tap < Pins the Bar** back on in Preferences.

### Add Plane dialog

- **Single Plane**, **Video Plane**, **Color Plane**, **Gradient Plane** and **Holdout Plane** open one **Add Plane** dialog with the plane type in a dropdown at the top, so you can switch type without closing it. Settings are grouped into Animation, Plane and Material, Camera, and Placement sections.
- Adding a Single Plane no longer changes the scene resolution to the new image's aspect. Turn on **Fit Camera to New Plane** in the dialog to get the previous behavior.

### Effect stack performance

- Reordering an effect chain now writes the complete order once and rebuilds each material stage once, instead of rebuilding the stage for every one-step move. Adding effects to a populated stack is roughly twice as fast (16-effect stack: about 1.7 s → 0.8 s in total).
- Shader-stage order lookups scan each material once instead of recomputing node tokens two or three times per node.
- Mixed stacks (Image effects plus at least one Mesh effect) are about three times faster to edit: a 12-effect mixed stack drops from about 2.8 s to 0.95 s of total add time. The stack order is computed once per refresh, Mesh-effect modifiers are identified without re-reading node-group tags per registered effect, and composite stage materials only write socket values that actually changed (this also avoids needless material re-evaluation during playback).

### Compositor

- The Compositor panel now starts with one **Compositor | Refresh | Live Update** row. Compositor turns the tools off as well as on, and Refresh rebuilds the setup; it is highlighted when changes are waiting or nothing has been built yet.
- **Live Update** is off by default: adding layers or effects or changing an effect type no longer rebuilds the compositor after every click. Effect values (mix, thresholds, colors) still update immediately. Turning Live Update on applies any waiting change, and enabling **Use Compositor in Render** brings a waiting setup up to date before rendering.
- The compositor **Color Grade** effect now changes the image. It used a Color Balance mode that ignores Temperature and Tint, and wrote the same value to both white points, which cancel out.
- A copied scene (Full or Linked Copy) no longer renders the original scene's layers into every managed compositor layer.
- With Live Update off, dragging an effect value after changing its type (or reordering) no longer writes into the old effect's node; it waits for Refresh like other structural edits.
- Grouping, ungrouping, moving and removing compositor layers, reordering compositor effects and assigning groups now follow Live Update / Refresh, instead of always rebuilding immediately (and raising an error, for example when the last layer of a folder was removed).
- **Share Unassigned Groups**, **Render Managed Layers Only** and View Layer names now mark the compositor for Refresh when changed.
- With **Render Managed Layers Only** off, turning a native View Layer's render switch on or off is no longer undone by the next compositor sync.
- **Restore Native Compositor** asks for confirmation, because it also deletes the editable Effects & Masks group.
- The compositor no longer re-tags its tree on every scene update while the render opt-in is active, and two layer-remap dropdowns can no longer show garbled names.

### Cleanup

- Removed about 700 lines of code that nothing used: 31 helper functions (diagnostic snapshots, legacy timing probes, layer sorting and report helpers), two dead constants and three unused imports. The static orphan audit now lists only two Scrub Bar helpers, which are left as they are.

### Fixes

- Masks that sample the layer UV (Luma/Alpha Matte, Gradient, Noise, Wave, Voronoi, Channel, Color and Imported masks) no longer lose their UV input after a UV effect is moved or the stack is sorted. They previously appeared frozen until another rebuild.
- Removing a duplicated (multi-instance) effect now also removes its per-instance viewport and render visibility data instead of leaving it on the layer.
- **Clear Effect Stack** and **Remove Selected Effects** now update the saved effect-stack data, so removed effects (and their group membership) no longer remain as hidden records in the .blend file.
- **Copy / Paste Effect Stack** now pastes an exact copy: duplicated effects keep every instance with its own settings, and the visible stack order and effect groups are preserved. Previously only one instance per effect was pasted, with the active instance's values, and the order could change the look of the result.
- **Effect Stack Presets** now restore the saved stack order. Existing presets benefit too, because the order was already stored in them.
- Copying a stack or saving a preset no longer changes the source layer: duplicated effects were silently added to the group of their first instance.
- **Hide in Render** now works for every Image effect. The render only applied it to animated or Evolve effects, so other effects hidden for the render still appeared in F12 output. Mesh-effect render quality settings are now applied to every Mesh effect for the same reason.
- Toggling render visibility for a duplicated effect with several layers selected now reaches every instance.
- In stacks that mix Image and Mesh effects, hiding an effect, Solo, duplicating an instance and removing an instance are now reflected in the final result and in what Mesh effects read. Previously the change only appeared after another edit.
- Removing an effect instance that a local mask was attached to now returns the mask to the layer cleanly; Project Health no longer reports a missing receiver.
- Hiding a global (Layer) mask, in the viewport or for the render, no longer makes a semi-transparent layer more transparent. The hidden mask still multiplied the layer alpha once more (50 % alpha rendered at 25 %).
- Adding an effect while an effect group (or one of its members) is selected now places the new effect inside that group. It was added to the top of the stack while joining the group, so the group also swallowed every row in between.
- Switching an effect to another variant of its family (for example Pixelate → Hex Pixelate) keeps its place in the stack instead of moving it to the bottom. With two variants of one family on a layer (for example Swirl and Bulge Pinch), the switch now replaces the effect you clicked instead of the first one in the family. On a duplicated effect it replaces only the selected copy (the other copies and their settings stay), and a local mask attached to that copy moves to the new variant.
- **Paste Effect Stack** and **Effect Stack Presets** keep local masks on the right duplicated effect, rebuild mask combinations in stack order, and no longer add ungrouped duplicated effects to a group. In Merge mode, masks attached to a replaced effect return to the layer instead of pointing at nothing.
- Adding or removing an effect (including removing the last one) now updates the saved effect-stack data immediately.
- Removing an Image effect that had a local mask no longer disconnects the UV input of the effect above it (for example Swirl above a masked Wave Warp), which made the layer render wrong until the next edit.
- Re-adding an effect that is already on the layer no longer moves it, or its other copies, into the selected group. The same cause briefly grouped pasted copies.
- After a variant switch, a local mask on a duplicable effect follows the new variant's exact copy, so removing that copy returns the mask to the layer.
- **Duplicate** places the copy directly above the original effect, and a copy of a group member joins that group. The copy was listed at the bottom of the stack, although it was evaluated above the original, and the next reorder moved it to the bottom for real.

## [7.2.1] — Prepared 2026-09-07

- Added paired Gap Off/On icons with separate grouping and explicit, idempotent choices.
- Replaced both Gap assets with the final high-contrast artwork supplied on September 7.
- Separated the GP color pair from Pin Mode and restored the Swap Colors button background in Draw, Vertex Paint and Edit modes.
- Placed Scrub Bar controls first in the centered Viewport lane across all six GP modes without copying Blender's header source.
- Fixed explicit Gap Off for mixed open/closed Edit selections; preserved Draw-only G toggle and Undo handling.

## [7.2.0] — 2026-09-05

### Stable release polish

- Integrated the final original 7.2 artwork with unchanged splash buttons.
- Deferred automatic What's New until Preferences is closed or left, preserving pending notices across add-on reloads.
- Avoided a redundant splash image decode on first load while refreshing existing images after updates.
- Added strict runtime-only package inventory and source/wheel/license checks to both build scripts.
- Extended exclusions for bytecode, temporary work directories and Blender backups; retained saved-project compatibility.

### Grease Pencil color workflow

- Added independent Stroke and Fill RGBA selectors to Draw, Vertex Paint and Edit modes, with native Stroke, Fill and Both behavior.
- Added compact mixed-color selection swatches, separate point/fill edits, `X` swap and continuous Stroke-only `Shift+X` sampling.
- Added Close Gap in the native Tool Header and a Draw-only `G` shortcut that preserves Edit Mode Grab.
- Added dedicated Undo steps and post-Undo Draw tracking recovery for swaps, sampling, Close Gap, point colors, fill colors and new Both-mode strokes.

### UI and rendering

- Added an unparented Object Data Properties image panel plus shared Tool/N-Panel roots for Layers, Grease Pencil and Layer Settings.
- Made the managed compositor explicitly opt-in for renders while preserving previous native render and artist-graph state.
- Retained the 7.1.19 camera format, linked pixel, effect-list, Scrub Bar, timeline synchronization and template/import stability work.

### Validation

- Added a focused Blender 5.2 feature gate for dual colors, Close Gap, Edit/paint Undo, compositor opt-in, Object Data placement and three-cycle lifecycle cleanup.
- Updated the five-platform GitHub Actions gate and installed-package checks for 7.2.0.

## [7.1.19] — 2026-08-10

### Stability and compatibility

- Migrated legacy White Scrub Bar bookmark metadata to adaptive None and legacy Blue metadata to Cyan.
- Kept hexadecimal Color Plane creation under More... while removing the two obsolete folder-import entries from the Shift+A menu.
- Added repository checks that reject drift between the manifest, package builder, Blender Extensions publisher, release notes and native release gate.
- Removed proven orphan code and unused imports while retaining the frozen 7.1.x identifiers and saved-data contracts.
- Fixed the canonical Felt Fuzz socket contract and moved its Alpha Mask upgrade out of per-instance creation.
- Cleared Grease Pencil raster-mask buffers during the normal runtime-cache lifecycle.
- Made import entry points tolerate stale `Scene` RNA wrappers left by New/Open/Reload instead of leaking a `ReferenceError`.

### UX and UI

- Replaced fixed White with adaptive None (`SNAP_FACE`), removed Blue, and matched Grey to Blender's `STRIP_COLOR_09` swatch.
- Simplified the Scrub Bar popover by removing Interaction Info, Add Bookmark and the transparent-viewport explanatory label.
- Reordered the Scrub Bar context menu to Add Bookmark, Select/Deselect All, active Keyframe Type, Mirror, Duplicate (Shift+D) and Delete.
- Kept Blender's native Viewport header draw untouched and verified seven repeated 2D Animation/Storyboarding template changes without a collapsed header.
- Rebuilt the Grease Pencil Effect Stack as a selectable list with add, remove, reorder and reset actions, matching the image-plane Effects workflow.
- Replaced the long native Grease Pencil effect grid with a grouped add menu: Stylize, Light & Edge, Warp, Stroke, Motion & Build, Utility and Surface.
- Expanded native Grease Pencil controls for Rim, Shadow, Blur, Glow and Outline, including quality, Wave/Object shadow modes, Depth of Field, Glow blend controls and Outline material/target settings.
- Fixed the Geometry Nodes icon in the expanded Grease Pencil Compatibility Matrix for Blender 5.2.
- Fixed Glow defaults to use Blender 5.2's actual `opacity` and `size` properties instead of ignored compatibility names.
- Backported the compact playback controls from Blender PR 162412 to Blender 5.2, with configurable endpoint, keyframe and delta jumps.
- Added time synchronization popovers to Timeline, Dope Sheet, Graph Editor, NLA and Sequencer plus bidirectional Scene Strip frame synchronization without forcing an editor to change Scene.

### Release engineering

- Declared and built five platform-specific packages for Windows x64/ARM64, macOS Intel/Apple Silicon and Linux x64.
- Kept package metadata deterministic and expanded release validation for the macOS Intel archive.
- Added a reusable static orphan-code audit and an isolated 133-effect Blender audit matrix.
- Hardened long-path rename recovery so manifests do not exceed Windows `MAX_PATH` during rollback-safe imports.

## [7.1.18] — 2026-08-01

### Stability

- Fixed persistent identity for Blender 5.2 native Grease Pencil Shader Effects and modifiers.
- Prevented repeated add actions from creating unmanaged duplicates.
- Restored native Grease Pencil effect removal, reordering, reset, duplicate repair and open-state persistence.
- Fixed Compositor Safe Repair snapshots for Blender 5.2 color, vector and rotation socket values.

### UX and UI

- Added Expand All and Collapse All actions to the Grease Pencil Effect Stack.
- Fixed Bookmark Color Tag swatches so White, Grey, Yellow, Red, Orange, Green, Blue, Magenta and Purple match their displayed names.
- Kept inline effect sections open or closed across redraws and file saves.
- Improved release documentation, search-oriented project wording and Blender 5.2 troubleshooting.

### Validation

- Passed the complete Blender 5.2.0 background regression suite.
- Passed the interactive 300-redraw sidebar stress suite and Preferences reload test.
- Validated all five declared-platform packages with Blender's native extension validator.
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
