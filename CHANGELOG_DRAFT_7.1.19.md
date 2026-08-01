# Frame By Plane 7.1.19 — draft changelog

> Draft only. The audited source still reports version 7.1.18 and has not been published.

## Stability

- Fixed the Effect Evolution lifecycle check so enable, Project Doctor and Repair consistently use Blender’s `frame_change_post` phase.
- Registration failures now roll back registered modules in reverse order and release the busy state when cleanup is safe.
- Generation waits for its own 0.20-second deadline even when another add-on has a faster timer running.
- Sequence and Multiplane generation now advance in main-thread chunks, report the current step and can be cancelled safely between Blender operations.
- Cancelled or failed generation restores add-on-created objects, meshes, materials, images and node groups from its transaction snapshot.
- Background render helpers no longer intercept `KeyboardInterrupt` or `SystemExit` as ordinary errors.

## Interface and diagnostics

- Grease Pencil effect compatibility now explains why an effect is Native, a Geometry Nodes candidate or Raster-only.
- Added Native, GN Candidate, Raster and All filters, category counts and Copy Compatibility Report.
- Replaced 40 generic operator tooltips with action-specific descriptions covering prerequisites, multi-layer behavior, Undo, skipped items and Preview scope.
- Preview badges and diagnostics are now consistent across Compositor Layers, Procreate Import and Generic Mesh Effects.
- Project Doctor labels Preview limitations separately from LTS errors.
- Added local Copy Diagnostics for active Preview features; no paths, media or telemetry are sent anywhere.

## Safer irreversible actions

- Renaming an effect preset creates an atomic rolling `effect_presets.backup.json` backup.
- Renaming source sequence files requires explicit confirmation, previews the first and last rename, and writes a rollback manifest by default.
- Filesystem actions now state clearly that Blender Undo cannot restore renamed files or external configuration.
- Corrupted-plane removal requires confirmation; targeted relation repair is shown only where a valid row target exists.
- Render-output sync now exposes a clear availability reason and remains a scene-only, idempotent operation.

## Performance

- Added an opt-in, local Developer/Profile mode. It is disabled by default.
- The Performance Dashboard can run a controlled 120-frame profile with warm-up, avg/p50/p95/max, CPU-side effective FPS, handler and scheduler metrics, Python memory delta and guaranteed frame restoration.
- Startup import/register timing, icon loading, scheduler queue/task timing, available cache statistics and UI-list activity can be exported as JSON or opened as a readable Blender Text report.
- Custom effect icons are loaded on demand. Startup preview entries measured in the audit dropped from 31 to 12.
- Duplicate icon aliases now share one Blender preview ID; 300,000 cached icon lookups measured 44.96 ms before and 30.24 ms after on the audit machine.
- Normal playback profiling remains outside the hot path when Developer/Profile mode is off. On the 100-layer animated fixture, average handler time measured 5.82 ms before and 5.71 ms after.

## Test coverage

- Expanded the Blender 5.2 LTS runner with registration failure injection, generation deadline/progress/rollback, Preview policy, irreversible-action contracts, performance profiling and icon deduplication checks.
- Added 20 Undo pushes with 10 Undo/10 Redo cycles in an interactive View3D context.
- Added tiny background renders for Workbench, Eevee and Cycles.

## Known limits

- “Profile 120 Frames” measures controlled CPU-side frame evaluation. It is not a GPU presentation benchmark or a substitute for final render timing.
- A single Blender operation cannot be interrupted halfway through; cancel is honored between reported chunks.
- Full runtime verification on Windows ARM64, macOS Intel/ARM and Linux x64 remains required before a multi-platform release.
- Large 4K/video, long-path/read-only filesystem and 250,000-point Grease Pencil fixtures remain follow-up test work.
