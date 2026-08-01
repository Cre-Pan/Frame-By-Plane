# Frame By Plane 7.1.18 LTS

Frame By Plane 7.1.18 is a Blender 5.2 LTS stability update focused on native Grease Pencil effects, compositor safety and a more efficient effects workflow.

## Grease Pencil effect stability

- Fixed native Grease Pencil effects losing their Frame By Plane identity immediately after creation on Blender 5.2.
- Prevented repeated clicks from creating unmanaged duplicate Shader Effects or modifiers.
- Restored reliable add, remove, reorder, reset and duplicate-repair actions for all 27 native Grease Pencil backends.
- Persisted inline open/closed state on the owning Grease Pencil object when Blender rejects custom properties on native stack items.
- Added **Expand All** and **Collapse All** controls to the Grease Pencil Effect Stack header.
- Kept artist-authored, untagged effects outside Frame By Plane cleanup and duplicate repair.

## Compositor safety

- Updated artist-graph regression coverage for Blender 5.2's `compositing_node_group` API and modern Mix node.
- Fixed Safe Repair snapshots for color, vector and rotation socket values exposed as `bpy_prop_array` or `mathutils` data.
- Preserved the fail-closed safety contract: unknown RNA values still cancel repair before artist nodes are modified.
- Verified nested group snapshots, custom properties, links, rollback and orphan cleanup on Blender 5.2.0 LTS.

## Test and release reliability

- Made the native regression runner independent of the extracted source directory name.
- Corrected What's New scheduling coverage so an already queued, deduplicated prompt is recognized as success.
- Isolated the tiny render from an intentionally incomplete compositor test graph.
- Passed the complete Blender 5.2 background suite and interactive 300-redraw UI stress suite.
- Validated the Windows x64 installable ZIP with Blender's extension validator.
- Normalized Blender-generated ZIP timestamps for reproducible release hashes.

## Support policy

- Blender support remains 5.2.x LTS.
- This patch changes no project schema and requires no manual migration.
