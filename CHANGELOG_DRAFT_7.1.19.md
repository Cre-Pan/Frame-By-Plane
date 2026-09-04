# Frame By Plane 7.1.19 — implementation record

> The public summary is maintained in `release-notes/7.1.19.md`. This record preserves the detailed stability work inherited by the final 7.1.19 candidate.

## Stability and generation safety

- Hardened every import file-browser entry point against a partially registered Blender session. Missing `fbp_project_path`/`fbp_last_directory` RNA now cancels with restart/re-enable guidance instead of an `AttributeError`, while clean Blender 5.2 Animation and Storyboard template cycles retain both properties.
- Extended the import guard to stale `Scene` RNA wrappers after Main replacement, preventing `ReferenceError` from an already-open file browser or popup.
- Added one process-wide UUID owner for Multiplane and Sequence generation across operators, scenes and windows.
- Separated Fast Import batching from Global Undo; incremental jobs no longer leave the user's Undo preference disabled between modal ticks.
- Added a central generation lifecycle for begin, checkpoint, commit, cancel, verified rollback and retirement during reload, disable and Blender Main replacement.
- File Open, File Revert and New File now retire active generation in interactive and background Blender before RNA references become stale.
- Replaced project-wide rollback scans with an explicit ownership journal for objects, meshes, materials, images, node groups, cameras, rigs, collections and disk changes.
- Rollback now reports removed, restored, failed and remaining entries and verifies its postconditions before reporting success.
- Restored selection, active object, mode, camera, cursor, pivot, render resolution/aspect, import directory and relevant UI state after Cancel/failure.
- Added one idempotent progress owner with monotonic updates and exact-once begin/end.
- Generation chunks now require the owned timer identity and monotonic deadline; foreign timers and reentrant advances are ignored.

## Filesystem recovery

- Rename manifests now use a UUID operation ID, UTC metadata, exclusive reservation, atomic replacement and explicit terminal status.
- Corrupted-plane removal keeps its report until the deferred task verifies deletion and exposes Retry after failure.
- Save, Rename and Delete Effect Preset now use the same confirmation, rolling-backup and atomic-write contract.
- Preset mutations explicitly state that Blender Undo cannot restore filesystem changes.
- A corrupt preset library can be restored from a valid rolling backup while the corrupt input is preserved for inspection.
- Preset mutation fails closed when both primary and backup JSON are invalid or when the target is read-only.

## Performance diagnostics

- Frame timing now runs without `tracemalloc` and without detailed local profiling.
- Python allocation sampling runs separately and is never mixed into avg/p50/p95/max frame timing.
- Added same-fixture profiler-overhead calibration, warm-up/sample metadata, Blender/machine/scene metadata and explicit CPU-side approximation labels.
- The profiler refuses playback, render, generation, Undo/load, active-profiler, external-tracemalloc and unsupported background operator contexts.
- Replaced front-trimmed handler sample lists with bounded `deque` buffers.
- Generation transaction preparation no longer scales with global datablock count; the audit measured ~0.08 ms median at both 1k and 100k unrelated IDs.
- Upgraded Felt Fuzz once at canonical-group load instead of patching Alpha Mask sockets for every instance, reducing isolated add time by about 72%.
- Connected Grease Pencil raster-mask buffers to central runtime cleanup so reload and Main replacement release them predictably.
- Profiled cold and warm behavior for all effect families; the largest cold costs are cached Blender/NumPy initialization rather than repeated stack overhead.

## Orphan-code audit

- Removed 42 unused top-level definitions/constants or reload-result bindings, five unused imports and one write-only runtime marker.
- Confirmed that all 100 add-on Python modules are referenced and that no unused imports remain.
- Retained 27 public diagnostic/integration bridges even when the add-on has no internal caller.
- Kept 7.1.x `bl_idname`, RNA, effect-ID, bookmark and saved-schema compatibility boundaries intact.

## Interface and diagnostics

- Moved selected-layer settings to Object Data Properties with an Image panel icon; kept the Layers and Grease Pencil stacks in Tool and restored all three optional N-Panel roots.
- Removed registered Panel-to-Panel inheritance after Blender 5.2 demonstrated that it can drop the base panel's `poll` callback during registration.
- Connected custom camera projection, lens/orthographic scale, clipping and aspect controls to the selected or Scene camera.
- Centered the Scrub Bar controls in Blender's native transform or Grease Pencil lane without replacing `VIEW3D_HT_header.draw`; an official append callback covers remaining modes where Blender omits both lanes.
- Differentiated the Interface preference icons and replaced the Updates and Support Video Plane icon with Monkey.
- Grease Pencil compatibility summaries distinguish Native supported from Native unavailable, GN candidates and Raster-only effects.
- Replaced the invalid `MOD_NODES` compatibility icon with Blender 5.2's native `GEOMETRY_NODES` icon.
- Added compatibility search, unavailable filtering and compact presentation for large effect lists.
- Replaced the old expanded Grease Pencil effect grid with a selectable UIList, plane-effects-style action toolbar and selected-effect settings.
- Divided the Grease Pencil add menu into seven icon groups: Stylize, Light & Edge, Warp, Stroke, Motion & Build, Utility and Surface.
- Removed the superseded inline effect-library renderer, expand/collapse operators and their transient RNA state.
- Preview feature detection now reads persisted compositor, Procreate and Generic Mesh metadata rather than relying on the latest import report.
- Project Doctor exposes `FAILED` and `FAILED_UNSAFE` registration lifecycle states with fail-closed recovery guidance and copyable diagnostics.
- Native GP Rim, Shadow, Blur, Glow and Outline now expose Blender 5.2's available artistic controls instead of a reduced generic subset.
- Glow reset now restores the intended 0.35 opacity and 6×6 size; Rim and Shadow use four quality samples by default.

## Timeline backport

- Backported the compact playback UI and jump-visibility preferences from official Blender PR 162412.
- Added synchronization popovers to Timeline, Dope Sheet, Graph Editor, NLA and Sequencer.
- Added guarded bidirectional Scene Strip frame mapping for Blender 5.2 without changing the editor's current Scene when Follow Scene is disabled.
- Automatically defers to Blender's compiled implementation when the upstream RNA is available in a later Blender build.

## Verified test coverage

- Blender 5.2 LTS background suite: 36 PASS, 0 FAIL and one documented SKIP, including panel/camera, Timeline and GP list/menu contracts.
- Blender 5.2 interactive suite: 8 PASS, including the native centered-header contract, two-window same/different operator contention, 20 Undo + 20 Redo and 300 Grease Pencil/Layer Tree redraw cycles.
- Installed Windows x64 ZIP: PASS for enable, FBP scene creation, save/reopen and active-owner File Open/Revert/New File.
- Blender 5.2 package validation: PASS for Linux x64, macOS ARM64/x64 and Windows ARM64/x64 archives.
- Isolated effect matrix: 6 Base, 79 Shader, 21 Geometry Nodes and 27 native Grease Pencil checks PASS (133 total).
- Direct Blender 5.2 visual QA: PASS for Data/Tool/N-Panel placement, live camera controls, Preferences icons, the GP effect list/group menu, Tag Color/menu ordering and two seven-step 2D Animation/Storyboarding header cycles.
- Static Blender 5.2 UI contract: 1,037 literal icons, 71 enum icons and 565 operator references validated with no remaining mismatch.

## Known limits

- Cancel is honored between Blender-operation checkpoints; a single Blender API call cannot be interrupted halfway through.
- “Profile 120 Frames” measures controlled CPU-side evaluation, not GPU presentation or a final render.
- Full runtime tests were executed on Windows x64 only. Other declared packages passed structural validation but still require native-platform runtime testing.
- The historical `CAMERA_SCALE_LOCK` artist-preservation fixture remains unavailable in the bundled test asset; the other Generic Mesh matrix/topology/group contracts pass.
