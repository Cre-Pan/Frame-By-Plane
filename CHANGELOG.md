# Frame by Plane 4.1.7

## Import hierarchy

- Flattened leaf folders containing exactly one static image, in addition to single image sequences.
- Ignored folder/layer name differences when deciding whether the Collection is redundant.
- Placed the static plane directly in the parent project Collection.
- Preserved Collections for folders with multiple layers, child folders or one video.

## Colors and preview

- Preserved independent automatically varied layer colors for flattened static images.
- Kept parent Collections neutral when they receive flattened static or animated layers.
- Removed the redundant folder row from the Multiplane Setup preview.

## Validation

- Added focused scan and direct-build tests for static images, sequences, nested folders, multiple stills and videos.
- Python compilation, Ruff undefined-symbol checks, registration and static audits passed.

---

# Frame by Plane 4.1.6

## Import hierarchy

- Flattened leaf folders containing exactly one detected image sequence.
- Removed the redundant Collection even when the folder name differs from the sequence name.
- Placed flattened sequences directly in their parent project Collection.
- Preserved Collections for folders with multiple sequences, child folders or one static image.

## Colors and preview

- Preserved independent automatically varied layer colors when no child Collection is created.
- Applied distinct colors to root-level independent sequences as well.
- Kept parent Collections neutral when they contain flattened child sequences.
- Disabled collection-color editing in the preview when direct layers do not inherit the Collection color.

## Validation

- Added focused scan and build tests for root, nested, renamed-folder and sibling-sequence cases.
- Python compilation and Ruff undefined-symbol checks passed.

---

# Frame by Plane 4.1.5

## Fixed

- Prevented `Remove Corrupted Planes` from freeing image/movie cache datablocks synchronously inside the generation report popup.
- Moved corrupted-rig deletion to the centralized safe-task scheduler.
- Removed Undo registration from the deferred cleanup operator, avoiding an invalid undo boundary around delayed ID deletion.
- Deferred cleanup of unused static image datablocks and explicitly unlinked UI users.
- Excluded native `SEQUENCE` and `MOVIE` images from automatic removal to avoid Blender 5.1 cache teardown crashes.

## Multiplane Setup UI

- Replaced filesystem folder icons with Blender collection color icons for setup collection rows.
- Added editable collection color tags to leaf collection rows.
- Editing a preview collection color updates every direct pending layer in that collection.
- Parent collections remain uncolored and scene roots continue to use the scene icon.

## Validation

- Python compilation completed for every module.
- Import, register, unregister, reload and re-register tests passed.
- All 90 operators remain registered with unique `bl_idname` values.
- Added targeted tests for deferred image cleanup, deferred corrupted-rig deletion and preview collection color propagation.

---

# Changelog

## 4.1.4

- Fixed **Main Folders as Separate Scenes** by executing each build with a matching Scene/ViewLayer context override and restoring the original window scene afterwards.
- Preserved the complete filesystem folder hierarchy during project scan and Auto Build.
- Assigned Collection colors globally across leaf folders using Blender's eight valid collection tags.
- Kept parent collections untagged (`NONE`) whenever they contain child collections.
- Mapped the neutral Frame by Plane layer tag `COLOR_09` to Blender Collection tag `NONE`.
- Reduced Extend drag sensitivity with a `0–1` soft range, `0.01` button step and three decimal places; larger values can still be typed manually.
- Preserved all 90 operator IDs/order and all 124 registered RNA properties.

## 4.1.3

- Restored persistent load/undo handlers, message-bus subscriptions, synchronization timers, orphan cleanup, and migrations after loading another `.blend` file.
- Centralized and cancelled deferred UI/generation tasks safely across file loads and extension reloads.
- Prevented duplicate render handlers and Blender menu callbacks after module reloads.
- Guarded procedural Color/Gradient preview cache updates against recursive RNA callbacks.
- Fixed background-render startup error handling, modal-monitor failure, reload state, and temporary-directory cleanup.
- Rolled back partially-created generation event timers.
- Replaced broad import fallbacks with `ImportError` and routed legacy load work through the central migration runner.
- Removed verified orphan UI helpers, lifecycle hooks, state variables, and compatibility wrappers.
- Preserved all 90 operator IDs/order and all registered RNA properties.

## 4.1.2

- Split the monolithic operator implementation into focused modules while preserving all 90 operator IDs and registration order.
- Reduced `core.py` by moving layer, collection, preview and project helpers into `layers.py`.
- Added `runtime.py` for shared diagnostics and transient state.
- Added `migrations.py` for retired Wiggle cleanup and old pre-start node migration.
- Removed module-level circular dependencies and several old `core.py` bridges.
- Replaced 308 exact `except Exception: pass` blocks with narrower exception groups; added explicit warnings to critical registration and native-rig paths.
- Added registration rollback diagnostics and static import/register validation.

## 4.1.1

- Shortened the Blender Extensions `permissions.files` reason to comply with the 64-character manifest limit.


## 4.0.19

- Removed unused `backend_dispatcher.py` and `sequence_parser.py` bridge modules.
- Removed orphan helpers, old settings properties, disabled viewport timers and deprecated transparent-frame UI code.
- Replaced `operators.py` namespace copying with an explicit import list.
- Fixed an undefined video-extension constant in the fallback material builder.
- Removed risky forced `Image.alpha_mode` changes from the fallback loader.
- Fixed deferred orphan-cleanup scheduling so a failed timer request cannot leave cleanup permanently locked.
- Safe-task timers are now tracked and unregistered when the extension unloads.
- Added registration rollback after partial failures.
- Sequence rename preserves per-frame data and updates all FBP rigs sharing the renamed source files.
- Background render process/log state is cleaned on stop, registration and extension unload.
- Removed historical release-note files from the extension package; history remains in this changelog.

## 4.0.17

- Fixed multi-rig Start Frame synchronization.
- Added FPS/duration editing across all selected Frame by Plane rigs.
- Holds the first image before Start Frame instead of forcing pre-start transparency.
- Layer thumbnails replace Color Tag icons when thumbnail display is enabled.
- Removed the Basic/Advanced UI switch and grouped advanced features into collapsible sections.
- Fixed Repeat Texture so both UV extension geometry and Image Texture extension mode update together.

## 4.0.13

- Deferred Multiplane generation by one UI tick so the start popup can appear before heavy work begins.
- Deferred Image Sequence generation after file selection for the same reason.
- Removed progress updates that could leave Blender's cursor/progress indicator frozen at 5%.
- Kept the final Generation Report popup for success, warnings, rename and cleanup actions.


## 4.0.6

- Added generation status/report popup for Multiplane and Image Sequence creation.
- Added post-generation actions: Remove Corrupted Planes, Rename Sequence, Let's Go and clear report.
- Added detection/reporting for unsafe native sequence filenames and missing generated source files.
- Kept the no-cache workflow: no automatic duplicate image files are created.

## Version 4.0.6

- Removed automatic `_FBP_native_cache` creation. Frame by Plane no longer copies image sequences into cache folders.
- Added an explicit **Rename Sequence for Blender** tool for native Image Sequence filenames that may show pink in Blender.
- The rename tool shows a confirmation dialog and renames the original files on disk to a simple consecutive pattern such as `Layer_0001.png`, `Layer_0002.png`.
- Problematic native sequences now display a warning in the Frames panel with a direct rename button.
- Added a maintenance button for renaming selected problematic sequence files.
- Native image/video backend remains cache-free and material-sequence-free.

## Version 4.0.3

- Fixed single-image imports in mixed project folders.
- Static image layers now use Blender image source `FILE`, not one-frame `SEQUENCE`.
- Native Image Sequence remains enabled for real multi-frame image sequences.
- Avoided forcing image `alpha_mode` during native media loading to reduce crash risk during large imports in Blender 5.1/5.2.

## Version 4.0.1

- Translated remaining user-facing UI labels to English.
- Added or expanded English tooltips for sidebar panels, properties and icon-only controls.
- Fixed the Layers UIList so image thumbnails are actually displayed when **Show Thumbnails** is enabled.
- Kept layer color tags visible beside thumbnails/procedural icons.
- Added layer color tag and procedural color data to the Layer Tree refresh signature, so UIList rows update more reliably after color/tag changes.
- Added clearer tooltip descriptions for frame duration, frame selection, visibility, opacity, timing and camera-fit controls.

## Version 4.0.0

- Renumbered the extension as `4.0.0` for the next Blender Extensions upload.
- Kept the stable Native Image Sequence backend introduced in the 2.0.x cleanup line.
- Image and video layers use Blender native `Image Sequence` / `Movie` nodes.
- Procedural Color and Gradient planes remain separate from image sequence logic.
- Holdout Plane remains a static mask plane, not an animated color sequence.
- Kept the cleanup and stabilization fixes from Beta 2.0.8.
- Kept Blender Extensions tags: `3D View` and `Animation`.



## Beta 2.0.8

- Added the `Animation` tag to the Blender extension manifest.
- Removed the duplicate `bl_info` metadata block from `core.py`; `__init__.py` is now the single add-on metadata source.
- Replaced wildcard UI imports from `core.py` with explicit imports in `ui.py` and `ui_layout.py`.
- Simplified the backend dispatcher now that only Native Image Sequence and Procedural Color backends exist.
- Kept runtime behavior unchanged for import, Native Image Sequence, Color, Gradient, Holdout, Crop / Extend and Background Render.

## Beta 2.0.7

- Removed the unused `fbp_fit_mode` RNA property now that Fit has one behavior only.
- Alpha-aware image holdout now creates a fresh holdout material every time, avoiding stale native ImageUser timing after rebuilds.
- Background render modal state is cleaned more safely after stop, finish or failure.
- Fixed a mutable default in the background render modal operator.
- Clarified procedural comments: Color/Gradient may have frames; Holdout planes are static masks.

## Beta 2.0.6

- Fixed native layer creation where Crop / Extend geometry refresh could restore a stale `matrix_world`.
- Vertical orientation and generated depth offsets are enforced after native geometry/timing rebuilds.
- Crop / Extend still preserves object transforms, but now through explicit local components instead of `matrix_world`.

## Beta 2.0.5

- Native image/video materials are now always unique per rig/rebuild.
- Alpha holdout restore now rebuilds image layers only through the native backend.
- Folder-only image imports now place generated rigs inside the correct collection.
- Selected FBP child planes resolve back to their rig for edit operators.
- Background render now starts with `Popen`, shows progress, and can be stopped.
- Procedural color-plane viewport hiding is applied inside the background render process.
- UIList color chips use non-joined rows to avoid cramped swatches.

## Beta 2.0.4

- Fixed creation orientation fallback: Vertical is now the default unless Horizontal is explicitly selected.
- Multiplane and single-plane generation use the same robust orientation/depth logic.
- Procedural Color/Gradient frame swatches in the Frames UIList are now editable.
- UIList color edits write directly back to the frame material and refresh active frame controls.

## Beta 2.0.3

- Cleaned package text files and removed duplicate release-note files from the extension zip.
- Removed stale version comments from the codebase.
- Removed placeholder extraction comments left during earlier refactor passes.
- Normalized excessive blank lines and trailing whitespace.
- Kept the runtime logic unchanged from Beta 2.0.2.

## Beta 2.0.2

- Fixed multi-rig editing for Crop / Extend and Color / Gradient controls.
- Simplified Fit to Camera to one reliable image-rectangle fit mode.
- Fixed orthographic Fit to Camera handling.
- Prevented Crop / Extend from resetting plane or rig transforms.
- Renamed `Edges` to `Crop / Extend` and reordered sliders.
- Restored animated REC/DOT state in the Frames UIList.
- Improved animated Color / Gradient frame updates and live UI swatches; Holdout planes remain static masks.
- Disabled and closed Gradient controls for solid Color frames.
- Added render viewport guard for procedural color planes.
- Fixed animated alpha holdout timing copy for native image sequences.

## Beta 2.0.1

- Removed the legacy generated-material image backend entirely.
- Image layers now always use Blender native Image Sequence / Movie nodes.
- Procedural Color and Gradient animation remains separate; Holdout planes remain static masks.
- Removed the backend preference from Add-on Preferences.

## Beta 2.0.0

- Added Safe Task Scheduler for deferred cleanup and native duplicate repair.
- Added Backend Dispatcher for Native Image Sequence and Procedural Color / Gradient / Holdout.
- Added Sequence Parser bridge for importer cleanup.
- Cached Color / Gradient UIList preview colors on frame rows.
- Stabilized Color / Gradient appearance panel height.
- Preserved procedural preview metadata during layer duplication.
- Cleaned Blender Extensions package for Beta 2.
