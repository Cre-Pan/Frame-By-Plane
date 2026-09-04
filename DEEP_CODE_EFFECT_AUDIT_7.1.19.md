# Frame By Plane 7.1.19 — deep code and effect audit

Audit completed on 10 August 2026 with Blender 5.2.0 LTS (`fbe6228777e7`). The review combined conservative AST reference analysis, Blender registration/reload tests, isolated add/evaluate/remove checks for every effect, cold/warm timing probes and direct visual UI checks.

## Outcome

- No orphan Python modules remain.
- No unused imports remain in the add-on or its Blender test launchers.
- 40 unused top-level functions, constants or reload-result bindings were removed.
- Five unused imports and one write-only Fast Import runtime marker were removed.
- 27 zero-internal-reference public helpers remain intentionally: they are read-only diagnostics, release-gate probes or documented integration bridges. They are not registration or runtime overhead.
- All 133 effect checks pass individually on Blender 5.2.
- The complete background suite passes with 35 PASS, 0 FAIL and one documented asset-dependent SKIP.
- The interactive Blender suite passes 7/7.

## Effect-by-effect matrix

| Family | Checked | Result |
|---|---:|---|
| Base | 6 | PASS |
| Shader | 79 | PASS |
| Geometry Nodes | 21 | PASS |
| Native Grease Pencil | 27 | PASS |
| **Total** | **133** | **PASS** |

Every supported effect was loaded or built, checked against its socket contract, added to a real fixture, evaluated through Blender's dependency graph, removed, and checked for residual objects. Native Grease Pencil entries were additionally resolved to the Blender 5.2 backend and checked for clean deactivation.

## Fixes and optimizations

### Native Grease Pencil visual controls

The Blender 5.2 RNA schema was compared with the controls exposed by Frame By Plane for all 27 native effects. The first visual-quality pass restores hidden options for Rim, Shadow, Blur, Glow and Outline. Glow's old generic `intensity`/`blur` defaults did not resolve on Blender 5.2; they now target the real `opacity`/`size` properties. Rim and Shadow default sampling increased from two to four, while existing saved effect values remain untouched.

The second UX pass replaces the old button grid and independently expanded sections with a native-style selectable list. Add operations are divided into seven icon groups, reordering uses Blender 5.2's native Shader FX/modifier move operators, and only the selected effect's settings are drawn. The superseded library renderer, two expand/collapse operators, two transient RNA flags and per-item open-state bridge were removed.

### Felt Fuzz

The prebundled Felt Fuzz group still exposed the transitional `Base Seed` socket and received Alpha Mask sockets separately for every effect instance. The canonical group is now upgraded once before caching:

- the current contract exposes `Seed`, `Use Alpha Mask`, `Alpha Threshold` and `Alpha Resolution`;
- saved 7.1 files using `Base Seed` remain readable through the reverse socket alias;
- instance creation no longer repeats the Alpha Mask patch;
- isolated add time fell from about 25 ms to about 6.5–7 ms, roughly 72% faster.

### Runtime caches

Grease Pencil raster-mask caches are now cleared by the central Grease Pencil runtime cleanup. Reload, file replacement and add-on teardown therefore release the bounded grid/raster buffers instead of retaining up to roughly 48 MiB until process exit.

### Cold/warm profiling

- Square Mask: about 317 ms on the first process use, then 12.9–13.9 ms. The cold cost is lazy NumPy/helper/SDF initialization and is intentionally not moved to every Blender startup.
- Circle Mask: about 37–54 ms after initialization, dominated by its denser editable SDF contour.
- Text Matrix: about 229 ms for the first dependency-graph evaluation, then about 10–11 ms; group loading and Blender compilation are cached correctly.
- Other shader additions stayed below roughly 30 ms in the isolated matrix; Geometry Nodes outliers match their declared `HEAVY`/`VERY_HEAVY` classifications.

## Removed code

The safe removal set included:

- obsolete Blender 5.2 assertion and import-context wrappers;
- unused unavailable-effect UI cache code;
- reload-retirement result variables whose cleanup calls still execute directly;
- superseded UI width, icon, folder-order and effect-order helpers;
- an obsolete Grease Pencil keyframe tuple wrapper and continuous scrub mapping;
- duplicate release metadata constants and retired motion/compositor/UI constants;
- unused test/runtime imports and the Fast Import undo marker that had no reader.

The audit deliberately did not remove Blender classes, `bl_idname` aliases, RNA properties, effect IDs or string-addressed callbacks solely because a lexical search could not see a call.

## Compatibility retained

- Public `bl_idname` aliases stay frozen for the full 7.1.x line.
- Saved RNA names and Frame By Plane IDProperty keys remain unchanged.
- Legacy bookmark prefixes remain readable so existing Timeline markers reconcile correctly.
- Project, effect-stack and preset schema fields remain active validation boundaries, not disposable migration code.
- Legacy compositor roles remain because they repair/open existing 7.1 files without guessing.
- Reload registration cleanup remains necessary for Blender's Reload Scripts and Main replacement lifecycle.
- The Blender PR 162412 backport is isolated behind compiled-RNA detection so it becomes inert when Blender provides the upstream implementation.

## Reusable audit tools

- `tools/audit_orphan_code.py` reports module, symbol and import candidates without deleting dynamically registered Blender code.
- `tools/audit_effects_blender.py` supports `BASE`, `SHADER`, `GEOMETRY` and `GP_NATIVE`, optional effect-ID filtering and repeated cold/warm profiling.

Machine-readable reports are stored in the local `effect-audit-7.1.19` evidence directory.
