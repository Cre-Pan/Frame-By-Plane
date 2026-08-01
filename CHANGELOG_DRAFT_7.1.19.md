# Frame By Plane 7.1.19 — draft changelog

> Draft only. The audited source and packages still report version 7.1.18. Nothing described here has been published as 7.1.19.

## Stability and generation safety

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

## Interface and diagnostics

- Grease Pencil compatibility summaries distinguish Native supported from Native unavailable, GN candidates and Raster-only effects.
- Added compatibility search, unavailable filtering and compact presentation for large effect lists.
- Preview feature detection now reads persisted compositor, Procreate and Generic Mesh metadata rather than relying on the latest import report.
- Project Doctor exposes `FAILED` and `FAILED_UNSAFE` registration lifecycle states with fail-closed recovery guidance and copyable diagnostics.

## Verified test coverage

- Blender 5.2 LTS background suite: PASS, including registration failure injection, media generation, deep rollback, filesystem recovery, save/reopen and Workbench/Eevee/Cycles renders.
- Blender 5.2 interactive suite: PASS, including two-window same/different operator contention, 20 Undo + 20 Redo and 300 Grease Pencil/Layer Tree redraw cycles.
- Installed Windows x64 ZIP: PASS for enable, FBP scene creation, save/reopen and active-owner File Open/Revert/New File.
- Blender 5.2 package validation: PASS for Linux x64, macOS ARM64/x64 and Windows ARM64/x64 archives.

## Known limits

- Cancel is honored between Blender-operation checkpoints; a single Blender API call cannot be interrupted halfway through.
- “Profile 120 Frames” measures controlled CPU-side evaluation, not GPU presentation or a final render.
- Full runtime tests were executed on Windows x64 only. Other declared packages passed structural validation but still require native-platform runtime testing.
- The historical `CAMERA_SCALE_LOCK` artist-preservation fixture remains unavailable in the bundled test asset; the other Generic Mesh matrix/topology/group contracts pass.
