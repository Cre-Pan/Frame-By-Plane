# Changelog

All notable public changes to Frame By Plane are documented here.

## [Unreleased]

## [8.0.0] — Prepared 2026-10-20

Includes 7.2.1, which was not published on its own.

### Effect stack performance

- Reordering an effect chain now writes the complete order once and rebuilds each material stage once, instead of rebuilding the stage for every one-step move. Adding effects to a populated stack is roughly twice as fast (16-effect stack: about 1.7 s → 0.8 s in total).
- Shader-stage order lookups scan each material once instead of recomputing node tokens two or three times per node.
- Mixed stacks (Image effects plus at least one Mesh effect) are about three times faster to edit: a 12-effect mixed stack drops from about 2.8 s to 0.95 s of total add time. The stack order is computed once per refresh, Mesh-effect modifiers are identified without re-reading node-group tags per registered effect, and composite stage materials only write socket values that actually changed (this also avoids needless material re-evaluation during playback).

### Compositor

- **F12 asks before rendering an out-of-date compositor.** When Use Compositor in Render is on and compositor changes are waiting for Refresh, F12 / Ctrl+F12 open a short warning with **Update** (refresh, then render), **Ignore** (render the previous setup) and **Cancel**. In every other case F12 renders exactly as before.
- **Opening a file no longer adds a compositor.** Every load gave each scene an empty "FBP Composite" compositor, and F12 then rendered through it even if the Frame By Plane compositor was never used. Files saved that way are cleaned up on load: an empty generated compositor is removed and the native render path comes back.
- **Compositor Off really turns it off.** The Compositor button only hid the panel, while the managed graph, its View Layers and Film Transparent stayed active and F12 still rendered through it. Off now puts back your own compositor, Use Compositing, Film Transparent and View Layer switches, removes the generated View Layers and stops live updates. The FBP nodes (including nodes you added) and the layer list are kept, and turning the compositor on again resumes the same setup.
- **Building the compositor no longer changes F12** until **Use Compositor in Render** is on. Generated View Layers used to render, and Render Managed Layers Only switched off your own View Layers, as soon as the setup was built. They now follow the render opt-in, which also switches them back immediately when it is turned off.
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

### New effects

- **Frame Stack** (Mesh, for image sequences and videos): turns time into a solid. Earlier frames are stacked in depth behind the plane, one slice per frame, with per-slice offset, depth, rotation, twist and scale. **Follow Playback** keeps the newest frame on the plane and the past trailing behind; **Fixed Range** stacks a chosen range and its Start Frame can be animated to scroll the solid through time. Opacity offers the front/back threshold (faint front slices), **Depth Fade**, a **Luminance Key** that hides dark or bright areas without a separate mask video, and **Glow**, an additive mode that needs no sorting. An optional **Outline** draws the volume edges. The plane keeps full resolution; earlier slices use a grid whose detail is set separately for viewport, playback and render. Cycles automatically gets enough transparent bounces for the slices. Concept inspired by "Video Frame Stack" by hipofizus.

- **Knit & Crochet** (Mesh, for images, sequences and videos): rebuilds the image as yarn. **Knit** makes stockinette V stitches in columns, each row tucked under the next; **Crochet** makes single-crochet stitches (a head over two posts) in brick-offset rows. Every stitch takes its colour from the image, transparent areas stay empty, and sequences and videos stay animated. Thickness, plies and twist shape the yarn; Fuzz adds a woolly sheen; Color Variation and Hand-made add irregularity; Self Light keeps the yarn readable in unlit scenes. Stitch count is set separately for viewport, playback and render.

### Import

- **Drag and drop shows the import options.** Dropping images, a sequence or a video now always opens the Import with Frame By Plane dialog: Auto / Single Plane / Multiplane, Dropped Media or Parent Folder, the plane settings (Frame Hold, loop, orientation, Shadeless, alpha crop) and a **Camera** choice: **Keep Camera**, **Match Aspect** (change the existing camera's output aspect to the media) or **New Camera**, plus Fit to Camera and, for Multiplane, Layer Spacing. Single Plane and Multiplane now follow the same camera choice; before, Single Plane could only adapt an existing camera and Multiplane always created a new one.

### Tutorial

- The tutorial card is about half the size, follows Blender's Resolution Scale and display density (it ignored scales below 1.0 and was too small on high-density displays), can be **dragged by its title bar** anywhere in the viewport and **collapsed** to the title bar alone, which still shows the current step.

### On-plane controls

- **Gradient Mask**, **Gradient Light** and **Tilt-Shift** handles now line up with the effect on non-square images. The blue and orange bars sat along the UV direction, so on a 16:9 image the visible transition ran at a different angle than the bars. Existing projects render exactly as before; only the handle positions are corrected.
- **Radial Gradient Mask** has its own handles: the yellow handle is the circle centre (drag to move, rotate to turn the handles), blue marks the inner radius where the mask is fully opaque and orange the outer radius where it reaches zero. The radial gradient is now a true circle on non-square images instead of an ellipse stretched to the image proportions (the shorter side keeps its size).
- Touching a **Gradient Light** handle no longer resets **Shadow Position** to zero.
- **Wave Mask** and **Voronoi Mask** get an on-plane arrow to rotate the pattern.

### Lattice (Deform Plane)

- **Poses**: one-click deformations — Sway, Arch, Squash / Stretch, Taper, Shear, Bulge / Pinch, Wave, Flag and Curl — each added as a slider that can be keyframed. Sliders mix freely and go from -1 to 1, so Squash becomes Stretch and Sway bends either way. **Custom** adds an empty pose and opens the cage to shape it; the pose is shown alone until **Back to Plane**.
- Presets land exactly on the cage surface (the B-spline cage no longer softens them depending on the grid density), and a preset that needs more control points refines the cage automatically.
- Changing the **Cage Grid** keeps the current shape, the poses and their animation instead of resetting the cage. Reset and Camera Flatten rewrite only the rest cage; poses keep their deformation on top of it.
- Fixed: refitting the cage after a grid change used the deformed plane's bounds, so the cage grew by the amount of the current deformation.

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

## [7.2.1] — Prepared 2026-09-07 (released as part of 8.0.0)

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
