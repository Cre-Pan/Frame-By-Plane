# Frame By Plane 7.1.10 LTS

Frame By Plane 7.1.10 closes additional deferred-callback, Generic Mesh and Compositor safety gaps found during the 7.1 LTS stabilization pass.

## Runtime and RNA safety

- Deferred callback scans now fail closed when their depth, item or node budget is exceeded.
- Oversized callback dictionaries, sequences, defaults, closures, slot payloads and callable namespaces are rejected rather than treated as safe after partial inspection.
- `safe_tasks` and `managed_timers` now revalidate the real callback immediately before execution, not only their scheduler wrapper.
- Mutable callbacks that acquire a Blender RNA value after registration are cancelled before they can run.
- New scheduler metrics distinguish confirmed RNA captures from inconclusive bounded scans.

## Generic Mesh

- Multi-object effect application is now transactional.
- If evaluation fails on any selected object, every earlier object is restored to its previous Frame By Plane modifier state.
- Newly-created modifiers on the failing object are removed.
- Existing artist-created Geometry Nodes modifiers remain untouched.
- Modifier ordering, custom properties, node groups and visibility flags are restored during batch rollback.

## Compositor Safe Repair

- Snapshot failures inside nested artist Group Nodes now propagate to the root completeness flag.
- Safe Repair fails before mutation when nested groups exceed the recursion, node or link safety limits.
- Failed reads of node properties, custom properties, socket values and link endpoints are no longer silently omitted.
- Incomplete artist graphs are rejected rather than compared as if they were complete.

## Test coverage

- Added tests for post-registration RNA mutation through both deferred-callback facades.
- Added fail-closed tests for deeply nested and oversized callback payloads.
- Added atomic multi-object Generic Mesh rollback coverage.
- Added nested Compositor Group depth-limit coverage.

Frame By Plane 7.1.10 requires Blender 5.2.x.
