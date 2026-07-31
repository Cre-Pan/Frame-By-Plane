# Frame By Plane 7.1.10 LTS — Roadmap status

## Completed in 7.1.10

- Fail-closed deferred-callback inspection when any traversal budget is exceeded.
- Dispatch-time validation of the real `safe_tasks` and `managed_timers` payloads.
- Atomic multi-object Generic Mesh application and rollback.
- Fail-closed nested artist Group Node snapshots in Compositor Safe Repair.
- Explicit snapshot diagnostics for unreadable node properties, sockets and link endpoints.
- Regression coverage for each of the above contracts.

## Still requiring native Blender 5.2 desktop execution

- Long Grease Pencil drawing sessions with the Layer Tree visible.
- Repeated collection nesting, deletion and Undo/Redo under continuous redraw.
- Extension update from a detached Preferences window.
- Splash focus and placement after a real extension reload.
- GPU-backed rendering and live Compositor evaluation.
- Generic Mesh evaluation across every supported effect, topology class and modifier-stack position.
- Multilayer EXR output and interrupted synchronization recovery.

## Remaining feature roadmap

### Grease Pencil effect parity

Only verified Blender 5.2 native backends remain enabled. Geometry candidates still require deterministic Grease Pencil Geometry Nodes implementations and native visual regression tests.

### Generic Mesh

Generic Mesh remains Preview. Batch application is now transactional, but production qualification still requires native tests on large, material-heavy and mixed-modifier objects.

### Compositor Layers

Compositor Layers remains Preview. Safe Repair now fails closed through nested artist groups; remaining native cases include multilayer EXR evaluation, derived Layer Set chains and scene duplication during deferred synchronization.

### Procreate and Toon Boom

Support remains conservative. Undocumented project structures, vector conversion and round-trip exchange are not advertised without deterministic samples and tests.
