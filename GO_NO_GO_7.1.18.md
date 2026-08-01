# Frame By Plane 7.1.18 — GO / NO-GO

## Decision

**GO con rischi accettati** for manual release review.

This is not an authorization to publish. The follow-up audit explicitly required no GitHub or Blender Extensions publication, and no publication was performed.

## Blocking criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| One process-wide generation owner | PASS | UUID owner; same/different operator, window and scene contention tests |
| Global Undo not disabled between ticks | PASS | True/False preservation plus interactive 20 Undo/20 Redo |
| Reload/load/unregister leave no owner | PASS | Reload, disable, installed-package Open/Revert/New tests |
| Explicit ownership and verified rollback | PASS | Structured removed/restored/failed/remaining result; foreign IDs preserved |
| Complete relevant user-state restore | PASS | Selection, active, camera, cursor, pivot, resolution/aspect, directory, UI/Undo |
| One progress owner | PASS | Exact-once begin/end, monotonic updates, 100% on commit |
| Foreign timers cannot advance chunks | PASS | Owned timer identity, deadline, 1 ms foreign timer and reentrancy tests |
| Cancel/rollback reports truthful | PASS | Reports derive from verified structured result |
| Preset/manifest/report filesystem recovery | PASS | Atomic writes, UUID manifest, backup/recovery, corrupt/read-only tests |
| Timing and memory separated | PASS | 120 timing samples without tracemalloc; separate 24-sample allocation run |
| Profiler refuses concurrent contexts | PASS | Playback/render/generation/Undo-load/profiler/tracemalloc/background guards |
| No persistent ID/version change | PASS | Manifest still `7.1.18`; repository verifier passes |
| Compile/register/background | PASS | Blender 5.2 suite, 0 failures |
| Install/activate/save/reopen | PASS | Final Windows x64 ZIP in isolated profile |
| Eevee/Cycles | PASS | Tiny background render outputs produced |
| Package validation | PASS | Four declared-platform ZIPs pass Blender 5.2 validation |

No P0 blocker remains in the tested environment.

## Accepted risks

1. **Native platform runtime coverage.** Runtime tests were executed locally on Windows x64. Linux x64, macOS ARM64 and Windows ARM64 packages passed structural validation locally; the new native GitHub Actions gate is configured but has not run remotely yet. This is the principal release risk.
2. **Single-call cancellation granularity.** A long individual Blender API call cannot be interrupted; cancellation occurs at the next safe checkpoint.
3. **Historical Generic Mesh fixture.** `CAMERA_SCALE_LOCK` artist-modifier preservation is skipped because its node asset is not present in the bundled regression fixture. Generic Mesh matrix, topology and group contracts pass.
4. **Synchronous profile UI.** The profiler refuses unsafe contexts and restores the frame, but does not provide mid-run Cancel. The measurement is limited to 120 CPU-side frame evaluations.

These risks do not invalidate the P0 transaction, Undo or recovery guarantees proven on Blender 5.2 Windows x64.

## Release conditions

Before an actual public upload:

- review and explicitly approve this GO decision;
- confirm that the final upload files match the SHA-256 values in `FOLLOWUP_AUDIT_7.1.18.md`;
- require all four jobs in the `Blender 5.2 native release gate` workflow to pass before upload;
- keep the version at 7.1.18 unless a separate versioning decision is made;
- run the existing PowerShell publisher only after its own confirmation prompt and only with `BLENDER_EXTENSIONS_TOKEN` supplied through the environment;
- publish GitHub/Blender Extensions as a separate, explicitly authorized action.

## Stop condition

Audit work stops here. No release, tag, GitHub asset, Wiki change or Blender Extensions upload is included in this decision.
