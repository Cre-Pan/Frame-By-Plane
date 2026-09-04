# Frame By Plane 7.1.18 — follow-up audit

Audit completed on 1 August 2026 against Blender 5.2.0 LTS on Windows 11. The add-on version remains `7.1.18`. No GitHub release, tag, asset or Blender Extensions upload was created or changed.

## Outcome

All P0 blockers identified by the follow-up prompt are resolved and covered by Blender regression tests. The candidate is classified **GO with accepted risks** for manual release review. The accepted risks are limited to runtime platforms unavailable on this machine, one unavailable historical Generic Mesh test asset, and the fact that an individual Blender API operation cannot be interrupted halfway through.

## Findings and disposition

| Finding | Disposition | Verification |
| --- | --- | --- |
| P0.1 process-wide generation lock | Resolved | One UUID owner records operator, scene, window, start time, phase, cancellation state and ownership journal. Same/different operators, two windows and two scenes are refused without changing the active owner. |
| P0.2 Global Undo between ticks | Resolved | Fast Import batches rebuilds but never changes `use_global_undo`. Initial `True` and `False` are preserved. Interactive suite completes 20 Undo and 20 Redo operations. |
| P0.3 orphan state after reload/load/unregister | Resolved | Central begin/checkpoint/commit/rollback/retire lifecycle. `load_pre`, module reload and unregister retire the owner, progress, queue and journal. |
| P0.4 broad/incomplete rollback | Resolved | Rollback uses an explicit tagged ownership journal. Results expose `removed`, `restored`, `failed`, `remaining`, disk changes and a verified postcondition. Foreign objects, materials and images survive. |
| P0.5 incomplete user state | Resolved | Selection, active object, mode, camera, cursor, pivot, render resolution/aspect, last import directory, Create Tools visibility and original Global Undo value are captured/restored. |
| P0.6 multiple progress owners | Resolved | One idempotent progress owner per transaction; begin/end occur once, updates are monotonic and commit reaches 100%. |
| P1.1 foreign timers advance chunks | Resolved | Timer identity, monotonic deadline, one-step-per-deadline and reentrancy guard are enforced. A foreign 1 ms timer is ignored. |
| P1.2 misleading progress semantics | Resolved | Payloads distinguish current step, completed steps, total steps, phase and percent. Stale updates cannot move progress backwards. |
| P1.3 O(project) preparation | Resolved | Production generation uses incremental ownership registration. Final medians remain below 0.25 ms from 1k through 100k unrelated Mesh IDs and do not follow the legacy global scan. |
| P1.4 false cancel/rollback report | Resolved | Reports are derived from the structured rollback result and name/count failures and remaining items. |
| P1.5 corrupted-plane report cleared early | Resolved | Deferred removal has a UUID task ID and pending/success/failure state. The report is cleared only after verified deletion; Retry remains available on failure. |
| P1.6 rename-manifest collision | Resolved | Schema 2 uses UUID operation ID, UTC timestamp/timezone, exclusive reservation, atomic replace, retry and terminal status (`COMPLETED`, `ROLLED_BACK`, `ROLLBACK_FAILED`). |
| P1.7 incomplete preset filesystem contract | Resolved | Save, Rename and Delete use confirmation, rolling backup and atomic write, explicitly state that Blender Undo cannot restore files, recover a valid backup while preserving corrupt input, fail closed without a valid backup, and preserve read-only targets. |
| P2.1 tracemalloc distorts timing | Resolved | Authoritative timing runs without tracemalloc or detailed local profiling. Allocation sampling is a separate 24-frame run. |
| P2.2 unguarded profiler | Resolved | Playback, render, generation, Undo/load, active profiler, external tracemalloc and unsupported background operator contexts are refused. |
| P2.3 front deletion in sample buffer | Resolved | Handler samples use `collections.deque(maxlen=2048)`. |
| P2.4 always-on metrics | Measured; no change required | Independent empty-scene frame evaluation changed by −0.45%, within sub-millisecond run noise. Detailed timing remains profile-gated. |
| P2.5 coarse chunks | Accepted limitation | Work is split at safe Blender-operation boundaries. A single Blender data-build call remains non-interruptible; cancellation is honored at the next checkpoint. |
| P3.1 ambiguous GP Native counts | Resolved | Native supported and Native unavailable are distinct; GN candidate and Raster-only counts remain explicit. Search, unavailable filter and compact 50+ row mode are present. |
| P3.2 incomplete persisted Preview detection | Resolved | Detection checks persisted compositor structures, Procreate rig metadata and Generic Mesh modifier metadata, not only the last import report. |
| P3.3 hidden failed lifecycle | Resolved | Project Doctor exposes `FAILED`/`FAILED_UNSAFE`, explains fail-closed recovery and offers copyable diagnostics. |

## Blender 5.2 results

### Background suite

- Result: **PASS**
- Failures: 0
- Skips: 1
- Registration: three clean reloads plus one in-place reload
- Synchronous media generation: PASS
- Owner, timer, progress, lifecycle, rollback and user-state contracts: PASS
- Preset read-only/corrupt/recovery and manifest finalization: PASS
- Save/reopen: PASS
- Workbench, Eevee and Cycles 32×32 renders: PASS
- Profiler separation and all concurrency guards: PASS

The single skip is `generic_mesh_artist_modifier_preservation`: the historical `CAMERA_SCALE_LOCK` node asset is not available in the bundled regression fixture. The Generic Mesh matrix, topology and supported-group contracts all pass.

### Interactive suite

- Result: **PASS**
- Failures/skips: 0/0
- Add-on registration: 0.2415 s
- Undo: 20 pushes, 20 Undo, 20 Redo
- Two windows, same operator: refused safely
- Two windows, different operators: refused safely
- Original owner continues; blocked job never becomes owner
- Rollback after contention: verified
- Grease Pencil/Layer Tree redraw stress: 300 cycles in 2.7187 s
- Preferences reload and What's New scheduling: PASS

### Installed ZIP smoke

The final `windows-x64` ZIP was installed and enabled through Blender's extension CLI in an isolated user profile. The installed module created an FBP Grease Pencil canvas, saved a `.blend`, reopened it, preserved the FBP marker and retained registered operators. With a transaction active, real File Open, File Revert and New File operations each retired the owner and its partial data. No source-checkout import was used for this smoke test.

## Bookmark Color Tag visual validation

The real Blender 5.2 menu reproduced a name/swatch mismatch: the nine Bookmark labels were paired with sequential `STRIP_COLOR` icons whose native order did not match the custom Bookmark palette. The menu now uses explicit `COLORSET` icons for White, Grey, Yellow, Red, Orange, Green, Blue, Magenta and Purple. A second interactive capture confirmed that every displayed name matches its swatch. Stored identifiers and Scrub Bar RGBA values are unchanged, so existing bookmarks require no migration.

## Package validation

All five declared-platform archives were rebuilt deterministically and passed Blender 5.2 `extension validate`:

| Package | Bytes | SHA-256 |
| --- | ---: | --- |
| `frame_by_plane-7.1.18-linux_x64.zip` | 11,277,458 | `0C56441543E42F16DF2F3A241C32FE3202BB0D330724242B1809637AD732DD72` |
| `frame_by_plane-7.1.18-macos_arm64.zip` | 8,547,090 | `9A40880DF98E4102CB2446B2F48EB3FC32AD7C874333774F65853D823AFF70D7` |
| `frame_by_plane-7.1.18-macos_x64.zip` | 9,160,658 | `CE665C82B3C72894EE604BA1C230EB4B446F641CD5EB1E4960F4C20508D97A14` |
| `frame_by_plane-7.1.18-windows_arm64.zip` | 6,669,721 | `E4D06D6E60EEA5159D0543C72D6A7A32EDF92B795F41C498687C266BB3A4EA51` |
| `frame_by_plane-7.1.18-windows_x64.zip` | 11,122,858 | `A9432B592486BB9A0E892C3D4C60A5294B8687882E7360760719413076900D40` |

The macOS x64 package is retained as requested and passes structural validation. It remains package-only in the automated gate because Blender's official 5.2.0 checksum listing currently contains no Intel runtime image.

`extension validate` checks package structure and platform metadata; it is not equivalent to running Blender on Linux, macOS or Windows ARM64.

## Persistent-data and publication checks

- `blender_manifest.toml` still declares `version = "7.1.18"`.
- No persistent schema or add-on identifier was changed.
- No user Blender profile was used for package installation; the smoke profile was isolated and removed after the test.
- No release was published and no network operation was required.

## Evidence

- `INCREMENTAL_TRANSACTION_TESTS_7.1.18.md`
- `PERFORMANCE_PROFILER_VALIDATION_7.1.18.md`
- `PERFORMANCE_BEFORE_AFTER_7.1.18.json`
- `CHANGELOG_DRAFT_7.1.19.md`
- `GO_NO_GO_7.1.18.md`
- Reproducible probes: `tools/followup_performance_probe.py`, `tools/installed_package_smoke.py`
