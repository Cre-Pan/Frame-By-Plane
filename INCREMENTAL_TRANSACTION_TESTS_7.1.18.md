# Frame By Plane 7.1.18 — incremental transaction tests

## Result

**PASS.** The final source passed the Blender 5.2 LTS background and interactive suites. The final installed Windows x64 package also passed active-owner File Open, File Revert and New File tests.

## Transaction model under test

Generation is coordinated by one process-wide owner in `generation_transaction.py`. Each owner has:

- a UUID token;
- operator ID and user-facing mode;
- scene and window pointers;
- UTC creation time and monotonic start time;
- phase, completed/total steps and cancellation state;
- one progress owner;
- an append-only journal of explicitly owned datablocks, collections, rigs, cameras and disk changes;
- a captured user-state record.

Only the owner token may checkpoint, commit or roll back the transaction. A refused job never starts Fast Import, never opens progress, never changes Global Undo and never owns output.

## Concurrency matrix

| Scenario | Expected | Result |
| --- | --- | --- |
| Two windows, same operator | B refused; A remains owner | PASS, installed interactive context |
| Two windows, different operators | B refused; A remains owner | PASS, installed interactive context |
| Two scenes | B refused process-wide | PASS |
| B attempts while A is later cancelled | B never becomes owner; A rollback only | PASS |
| Foreign object created after A begins | Preserved | PASS |
| Foreign material/image created after A begins | Preserved | PASS |
| Owner token after refusal | Unchanged | PASS |
| Progress/queue after refusal | Not opened/not finalized by B | PASS |
| Rollback after contention | Removes only A-owned entries; verified | PASS |

The interactive result contains `same_operator_refused=true`, `different_operator_refused=true`, `blocked_job_never_became_owner=true`, `owner_continued=true` and `rollback_verified=true`.

## Global Undo and history

| Scenario | Result |
| --- | --- |
| Initial `use_global_undo=True` | Preserved during and after Fast Import |
| Initial `use_global_undo=False` | Preserved during and after Fast Import |
| Wait between modal ticks | Add-on does not change the preference |
| Second window while owner active | Lock works without disabling Undo |
| Interactive history | 20 pushes, 20 Undo, 20 Redo — PASS |
| Background history availability | 20 pushes, all 19 exposed Undo entries and 19 Redo entries — PASS |
| Cancel/failure/reload/load/unregister | Original preference remains unchanged |

The production transaction is an explicit data transaction rather than a long-lived suppression of Blender Global Undo. Individual Blender operations remain history-visible according to Blender's native context; FBP rollback is responsible for cancelling partial generation between checkpoints.

## Lifecycle matrix

| Event | Test path | Result |
| --- | --- | --- |
| Reload Scripts/module reload | Active owner plus owned object, `importlib.reload` early retirement | PASS |
| Disable/unregister | Active owner plus owned object, coordinator unregister | PASS |
| File Open | Installed ZIP, real `bpy.ops.wm.open_mainfile` with active owner | PASS |
| File Revert | Installed ZIP, real `bpy.ops.wm.revert_mainfile` with active owner | PASS |
| New File | Installed ZIP, real `bpy.ops.wm.read_homefile(use_empty=True)` with active owner | PASS |
| Background Main replacement | `load_pre` registered in background and checked by lifecycle audit | PASS |

Every path leaves:

- no active generation owner;
- no owner progress handle;
- no transaction-owned partial object;
- no stale transaction journal in the replacement scene;
- no altered Global Undo preference.

The package smoke initially exposed that background mode registered `load_post` but not `load_pre`. This was treated as a real P0 defect, fixed in `handlers.py`/`lifecycle.py`, and the real Open/Revert/New sequence was rerun successfully.

## Rollback and failure injection

### Owned data

The journal was exercised with:

- Object and Mesh IDs;
- Material and Image IDs;
- Node groups;
- camera and rig records;
- a nested collection tree of depth 20;
- user-state mutations;
- disk-manifest state.

The depth-20 tree is removed by ownership order/dependency depth, not a fixed number of cleanup passes.

### Foreign data

Objects, meshes, materials and images not recorded with the transaction token remain after rollback, including foreign data created after the owner was acquired.

### Failure point

The deterministic `AFTER_YIELD` failpoint raises after the first yielded checkpoint. The resulting rollback reports:

- `verified=true`;
- no `failed` entries;
- no `remaining` entries;
- owned Mesh/Object removed;
- foreign data preserved.

### Truthful result contract

Rollback returns structured primitive data:

- `removed`;
- `restored`;
- `failed`;
- `remaining`;
- `disk_changes`;
- `verified`.

User reports are built from this result. The implementation does not say that rollback completed when the result is partial, failed or unverifiable.

## User-state restoration

The regression mutates state after acquiring the owner, then verifies restoration of:

- selected objects;
- active object;
- interaction mode when valid;
- scene camera;
- 3D cursor;
- transform pivot;
- resolution X/Y and percentage;
- pixel aspect X/Y;
- last import directory;
- Create Tools UI visibility;
- initial Global Undo value.

The serialized before/after relevant-state snapshot matches after verified rollback, except for explicitly journaled data that is expected to be removed.

## Progress contract

The progress probe produces:

- `progress_begin`: 1 call;
- monotonic updates: `0, 50, 50, 100`;
- `progress_end`: 1 call;
- updates after end: 0.

Repeated begin/end are idempotent. A stale 25% update after 50% does not move the UI backwards. Commit is the only path that publishes 100%; cancel reports the actual last completed checkpoint.

## Timer contract

The chunk scheduler verifies:

- event timer identity matches the owned timer;
- a foreign 1 ms timer is ignored;
- monotonic time must reach the stored deadline;
- only one chunk may claim a deadline;
- reentrant advance is rejected;
- cancellation prevents a late claim;
- non-timer events do not advance generation.

## Filesystem recovery

| Contract | Result |
| --- | --- |
| Rename manifest UUID/exclusive name | PASS |
| Atomic manifest finalization | PASS |
| Terminal status and finalization time | PASS |
| Preset atomic write | PASS |
| Rolling backup before Save/Rename/Delete | PASS |
| Valid backup recovery from corrupt primary | PASS; corrupt input preserved as `effect_presets.corrupt.json` |
| Corrupt primary and corrupt/missing backup | PASS; mutation fails closed |
| Read-only preset target | PASS; original bytes preserved |
| UI warning | PASS; Save/Rename/Delete state that Blender Undo cannot restore the file |
| Corrupted generated-plane cleanup | PASS; task UUID and report retained until verified completion |

## Final suite summary

- Background: PASS, 0 failures, 1 unrelated historical-asset skip.
- Interactive: PASS, 0 failures, 0 skips.
- Installed Windows x64 package lifecycle smoke: PASS.
- Five package manifests: PASS under Blender 5.2 `extension validate`.
