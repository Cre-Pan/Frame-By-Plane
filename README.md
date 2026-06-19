# 🎞️ Frame By Plane

**A better Image as Planes workflow built for Blender animation.**

Frame By Plane is a free Blender extension for importing single images, transparent PNG sequences, videos and layered folders as controllable animated image planes. It expands Blender's standard **Images as Planes** workflow with animation timing, looping, layer management, effects, Cutout replacement animation and multiplane project tools.

[Download Frame By Plane from Blender Extensions](https://extensions.blender.org/add-ons/frame-by-plane/)

## What is Frame By Plane?

Frame By Plane is designed for artists who need more than a static image plane. It turns image-based animation into an editable Blender workflow without requiring users to rebuild materials, manually configure image sequences or manage every plane separately.

Use it to:

- import one image as a plane;
- import a PNG or image sequence as an animated plane;
- import videos as native Blender movie textures;
- convert layered folders into multiplane animation setups;
- create Cutout Plane drawing libraries for replacement animation;
- control timing, loop modes, frame holds and playback directly from the 3D View;
- add Shader and Geometry Node effects to animated planes;
- manage large 2D and 2.5D animation projects inside Blender.

## Why use it instead of the standard Images as Planes workflow?

Blender's native **Images as Planes** tool is ideal for creating a single textured plane. Frame By Plane keeps that familiar idea but adds an animation-focused rig, native sequence controls, project organization and batch import tools.

| Workflow | Images as Planes | Frame By Plane |
| --- | --- | --- |
| Import a single image | Yes | Yes |
| Import a native image sequence | Basic setup | Animation-ready controls |
| Import layered folders | No | Yes |
| Multiplane animation setup | Manual | Automatic |
| Loop, Ping-Pong and One Shot | Manual configuration | Built in |
| First and last frame holds | Manual | Built in |
| Replacement drawing library | No | Cutout Plane |
| Layer list and project tools | No | Yes |
| Custom Shader and Geometry effects | Manual | Integrated effect stack |

## Main features

### Animated Image Planes

Import images, transparent PNG sequences and videos using Blender-native Image datablocks and materials. Control start frame, FPS, looping, playback mode, opacity and framing from the Frame By Plane interface.

### Multiplane Animation

Import complete folder structures as organized collections and animation layers. Frame By Plane detects numbered sequences, preserves natural ordering and creates editable multiplane setups for 2D and 2.5D scenes.

### Cutout Plane

Create a lightweight replacement-animation plane with a drawing library, thumbnails and an animatable integer **Drawing** slider. Use `0` as an empty drawing and switch poses without creating a material for every frame.

### Effects Stack

Apply built-in or custom Shader and Geometry Node effects to image planes. Create your own node effects, name them, assign icons and reuse them through the Frame By Plane Effects menu.

### Animation and project controls

Manage layers, timing, frame order, thumbnails, rendering, diagnostics and project cleanup from a unified Blender interface.

## Common Blender workflows

### How to import an image as a plane in Blender

Use **Shift+A → Frame By Plane → Single Plane**, choose an image and generate the plane. Frame By Plane creates the mesh, native image material and animation controls automatically.

### How to import an image sequence as a plane

Choose **Single Plane Animation** and select a numbered PNG, JPEG, TIFF or supported image sequence. Frame By Plane detects the sequence and provides Loop, Ping-Pong and One Shot playback controls.

### How to animate a transparent PNG sequence

Import the sequence through **Single Plane Animation**. Alpha is preserved when supported by the source images, and the resulting plane can be timed, looped and combined with effects.

### How to create multiplane animation in Blender

Choose **Multiplane** or **Multiplane Animation**, select the project folder and review the detected collections and sequences before generating the complete layered setup.

### How to import a video on a plane

Import the movie as an animated Single Plane. Frame By Plane uses Blender's native movie image source and exposes the relevant animation controls in the layer interface.

## Compatibility

- Blender 5.1 or newer
- Windows x64 and ARM64
- macOS Intel and Apple Silicon
- Linux x64
- Eevee and Cycles-compatible image materials

Frame By Plane never deletes original image or video files from disk.

## Installation

1. Download Frame By Plane from Blender Extensions.
2. In Blender, open **Edit → Preferences → Get Extensions**.
3. Search for **Frame By Plane** and install it.
4. Open the 3D View sidebar or use **Shift+A → Frame By Plane**.

## Frequently asked questions

### Is Frame By Plane an alternative to Images as Planes?

It extends the same image-on-mesh concept for animation-heavy projects. The standard Blender tool remains useful for simple static planes, while Frame By Plane adds sequence timing, layered imports, Cutout animation, effects and multiplane controls.

### Can I import a PNG sequence into Blender?

Yes. Frame By Plane detects numbered image sequences and imports them as native animated image planes with Loop, Ping-Pong and One Shot controls.

### Can I use transparent images and videos?

Transparent image formats are supported when the source contains alpha. Videos use Blender's native movie-image support, so available formats depend on the Blender build and its media support.

### Does Frame By Plane work for 2D animation in Blender?

Yes. It is designed for image-based 2D and 2.5D workflows, including multiplane scenes, replacement animation, motion graphics and composited animation layers.

## Release history

## 5.2.1 — Discoverability & Documentation

- Repositioned Frame By Plane as an animation-focused extension of the Images as Planes workflow.
- Updated the Blender Extensions tagline with the exact `Image as Planes` terminology.
- Rebuilt the README around real user workflows and search questions.
- Added concise explanations for image, sequence, video, Cutout and multiplane importing.
- Added a comparison table between Blender's standard Images as Planes tool and Frame By Plane.
- Added installation, compatibility and common-workflow sections for GitHub and search engines.
- No animation, rendering or project behavior was changed in this documentation-focused patch.

## 5.2.0 — Cross-Platform Release

- Declared support in the Blender Extensions manifest for Windows x64, Windows ARM64, macOS Intel, macOS Apple Silicon and Linux x64.
- Kept the official functional tags `3D View` and `Animation`; operating-system support is declared through the dedicated `platforms` field rather than feature tags.
- Consolidated the cleanup, Camera Rig removal, native sequence recovery and performance work completed since 5.1.5.
- Added a complete changelog covering versions 5.1.5 through 5.2.0.
- Preserved the fixed four-row Settings layout and its visual separators.

## 5.1.22 — Cleanup & Stability Pass

- Restored the four-row Settings layout in the Camera section after Camera Rig removal.
- Kept only standard camera generation controls: projection, lens/scale, aspect, clipping, cursor pivot and fit.
- Prevented hidden dot-files, macOS resource forks and hidden folders from entering project imports.
- Stopped automatic deletion of Cutout Image datablocks; unused managed buffers are released and Blender remains responsible for orphan purging.
- Removed the obsolete deferred Image-cleanup queue while preserving generated proxy-cache cleanup.
- Hardened hot reload by discarding legacy cleanup callbacks and malformed runtime cache containers.
- Removed an unused private Matrix helper and an unused render-unregister variable.
- Completed static registration, reference, property and call-signature checks.

## 5.1.21 — Camera Rig Removal

- Removed the complete Camera Rig subsystem.
- Removed Camera Rig operators, controls, custom widgets, properties, migration and repair code.
- Removed Camera Rig entries from Shift+A and Settings.
- Removed Camera Rig checks from Project Health, Deep Audit and Scene synchronization timers.
- Removed the Add Camera Rigs third-party integration and its package attribution.
- Standard camera settings and camera-dependent plane effects remain available.


## 5.1.17 — Native Sequence Timing Hotfix

- Fixed the root cause of persistent pink animated planes in Blender 5.1.2: the extended first-frame hold no longer moves `ImageUser.frame_start` before the real animation start.
- Prevented Blender from resolving the first sequence image as a missing frame such as `frame_0000.png`.
- Kept the 500-frame first/last holds through the compact `frame_offset` F-Curve, without changing the real native sequence start.
- Added automatic migration for native animated planes created with versions 5.1.5–5.1.16. Existing healthy images, materials, effects and layer order are preserved.
- Timing repair runs after extension registration, file/Scene synchronization and Undo/Redo, and touches only layers using the obsolete timing contract.
- Verified with the real Blender 5.1.2 Python runtime: static Single Plane, animated Single Plane, Multiplane, migration, save/reopen and register/unregister.

## 5.1.16 — Image Plane Import Recovery

- Restored reliable **Single Plane**, animated Single Plane and **Multiplane** generation after the 5.1.15 native-media regression.
- Removed unconditional proxy conversion; canonical proxies are again created only for mixed folders or filenames Blender cannot safely interpret as a sequence.
- Removed the forced `Image.reload()` immediately after changing an Image datablock to SEQUENCE or MOVIE, which could leave Blender 5.1 with an invalid or pink native buffer.
- Static images remain native FILE images and no longer pass through sequence-specific initialization.
- Removed automatic media rebuilds from the general Scene synchronization timer, preventing healthy newly-created layers from being rebuilt while import state is still settling.
- Kept strict path/source validation and bumped the media-cache revision so broken 5.1.15 Image bindings are not reused.

## 5.1.10 — Import Pipeline & Layer List Workflow

- Reworked Project Folder scanning into a single-pass directory snapshot instead of repeatedly traversing the same subfolders.
- Large animation exports and nested Toon Boom-style folder structures now build the Multiplane Setup with substantially fewer filesystem calls.
- Directory symlinks are not recursively followed, preventing accidental import loops and unbounded scans.
- Duplicate media entries are filtered before sequence detection while preserving deterministic natural ordering.
- Technical texture-map files and hidden import folders remain excluded during the optimized scan.
- Added **Expand All** and **Collapse All** controls to the Multiplane Setup import tree.
- Multiplane Setup collections remain collapsed by default and can be opened only when needed.
- The active Multiplane Setup row is now preserved by logical identity after collection collapse, rename or reordering instead of jumping to an unrelated visual row.
- Clicking a layer name explicitly selects its Frame by Plane rig and synchronizes both Layer List indices.
- Double-clicking an unselected layer name now selects that layer first and immediately opens the rename field.
- The linked-plane selectability icon now unlocks and selects the plane automatically, deselecting the rig and making the plane active.
- Clicking the plane icon again relocks the plane and returns selection to the rig only when the rig itself is not locked.
- Rig locks are no longer silently removed when returning from direct plane editing.
- Added targeted regression tests for project scanning, sequence grouping, duplicate filtering, symlink-loop protection and rig/plane selection transitions.

## 5.1.9 — Instant Custom Effect Authoring

- Added **New Custom Effect** to the Custom Nodes column of the Effects menu.
- The command creates a complete local node group instead of requiring a manually prepared group.
- In the 2D Effects view it creates a Shader template with `Color In`, `Alpha In`, `UV Vector`, `Color Out` and `Alpha Out`.
- In the 3D Effects view it creates a Geometry Nodes template with a Geometry input and output.
- New templates start as safe pass-through effects, so applying them does not change the current image, alpha or geometry.
- The generated group is registered automatically in the Frame by Plane Custom Effects library.
- The effect is applied immediately to every compatible selected Frame by Plane layer.
- The first linked plane becomes the active object and the add-on opens a Node Editor when the current workspace allows it.
- Shader effects enter the generated group from the active material; Geometry effects activate their linked Nodes modifier.
- Added **Edit Nodes** to existing Custom Effect controls for reopening the source group directly.
- **Register Existing...** remains available for node groups created manually or imported from other `.blend` files.
- Added conservative error recovery: group creation remains valid even when Blender cannot switch the current area to a Node Editor.
- Added contract tests for generated Shader and Geometry interfaces, pass-through links and unique custom-effect IDs.

## 5.1.8 — Effects Stack Identity & Custom Nodes Performance

- Duplicated Frame by Plane rigs now receive a fresh persistent Effects Stack owner identity instead of inheriting the source rig contract.
- Geometry modifiers and shader nodes copied by Blender automatically repair duplicated effect-instance IDs.
- Multiple material copies of the same shader effect on one layer share one logical instance ID, keeping layer-level controls synchronized.
- Existing projects self-heal legacy or conflicting instance metadata during normal stack synchronization; Deep Audit can also repair it explicitly.
- Deep Audit now validates persistent instance IDs for shader effects as well as Geometry Nodes effects.
- Custom Node Effects keep validated direct references to their source node groups and avoid complete `bpy.data.node_groups` scans while the library is unchanged.
- Custom-effect definitions are rebuilt only when metadata, interface sockets or node-group structure actually changes.
- Missing custom-effect lookups use a bounded negative cache, preventing repeated full searches for unavailable groups.
- Custom Geometry and Shader socket descriptors use short-lived bounded caches during rapid sidebar redraws and slider interaction.
- Multi-material custom Shader synchronization captures the master state once and skips secondary-material scans while topology and values remain unchanged.
- Material rebuild and effect restoration paths no longer force a complete Custom Effects registry refresh on every operation.
- The Effects sidebar rebuild path no longer performs node-group repair or full asset-health scans merely to mirror the current stack.
- All new runtime caches clear on Undo, file replacement and extension disable without retaining Blender RNA references.
- Static compilation, AST validation, instance-identity tests and Custom Effects cache regressions completed for every Python module.

## 5.1.7 — Undo, Render & Runtime Guard Hardening

- Undo pre-handlers no longer mutate Scene collection properties while Blender is entering Global Undo.
- Layer and pending-import UI rows rebuild only from a deferred post-Undo task after Blender releases the Main database safely.
- Undo guard release now fails closed when timer registration or render-state queries are unavailable; a persistent watchdog performs recovery instead.
- The Undo watchdog stays registered across normal operation and recovers stale guarded states even when an expected post-handler is missed.
- Render state reported as unknown never authorizes Blender ID writes or restoration, preventing unsafe mutations during uncertain background/render transitions.
- Render completion and cancellation immediately wake the restoration watchdog, greatly reducing the gap before a second render can start.
- Render visibility, effect state and interface-lock restoration are transactional: transient RNA failures remain queued and retry only after confirmed idle state.
- Stale or deleted render backup entries are discarded safely, while valid retryable entries no longer block unrelated restoration work.
- Deferred safe tasks tolerate short-lived unknown render states without being lost, then cancel conservatively if Blender never reaches a verifiable state.
- Load-post service restoration is isolated from partial module-import failures, keeping safety watchdogs available after file replacement.
- Added targeted regression tests for timer rejection, missed Undo post-handlers, unknown render state and transactional restoration retries.
- Static compilation, AST validation, handler duplication checks and package consistency checks completed for every Python module.

## 5.1.6 — Cache Safety & Multi-Scene Performance

- Cutout image lookup now uses a validated name-only path index instead of rebuilding a complete `bpy.data.images` map for isolated lookups.
- Cutout path caches self-heal after image path edits, rebuild after Image ID count changes and clear safely on Undo or file replacement.
- Cutout Scene rig caches now validate both layer and object counts, preventing short stale windows after duplication or deletion.
- Cutout Scene cache growth is bounded across temporary Scenes and long Blender sessions.
- Progressive Cutout thumbnail generation redraws only the 3D View sidebar and is rate-limited while the queue is active.
- Duplicate/orphan fallback scan clocks are now stored per Scene, so activity in one Scene can no longer postpone safety checks in another.
- Effect render-visibility rows reuse the existing runtime effect profile instead of rescanning Geometry Nodes modifiers.
- Render preflight performs one fresh effect discovery, then reuses resolved modifier and shader-node targets across the complete stack.
- Layer UI polls and hot rig iteration no longer allocate temporary copies of the synchronized layer collection.
- Extension unregister now clears cosmetic collection cache flags correctly after restoring an idle managed-render guard.
- Static compilation, AST validation and package consistency checks completed for every Python module.

## 5.1.5 — Performance & Stability Pass

- Cutout buffer cleanup is deferred during playback and rendering, preventing native image/GPU cache eviction from interrupting frame evaluation.
- Cutout cleanup is queued only when the displayed drawing actually changes instead of once per evaluated frame.
- Cutout scene lookup now scales with synchronized Frame by Plane layers rather than every object in the Scene.
- Native media datablocks are indexed once and resolved by validated keys, removing the previous repeated all-image scan during large imports.
- Native media lookup hints are cleared safely on Undo and file replacement, without retaining Blender RNA references.
- Raw source thumbnails now use a bounded 512-entry LRU cache; composite preview caches remain independently bounded.
- Layer collection caches no longer rewrite two custom properties across every collection on every synchronization.
- Collection containment checks use a lightweight active-scene index after the first rebuild, reducing Outliner/layer UI redraw work.
- Effect presence, source and visibility queries reuse bounded runtime profiles instead of repeatedly scanning modifiers and material nodes during UI redraws.
- Effect discovery/profile/health cache windows were tuned to reduce repeated topology inspection while preserving periodic self-healing.
- Static compilation and AST validation completed for every Python module.

## 5.1.4 — Cutout UI Cleanup & Stability

- Removed Pixel/Smooth controls from the Cutout N-panel; filtering remains available only during Cutout Plane setup.
- Removed the large-preview search/browser button and the popup thumbnail grid.
- Removed dedicated Empty buttons; `0 = Empty` remains available directly through the Drawing slider.
- Replaced the preview action button with a centered, non-interactive current-drawing label.
- Reduced Cutout preview cache and queue limits now that the permanent library list is the only thumbnail browser.
- Removed unreachable browser operator/UIList code and its Blender registrations.
- Preserved the progressive thumbnail queue for visible library rows, with lower bounded memory use.

## 5.1.3 — Cutout Memory & Animation Safety

- Added automatic CPU/GPU buffer eviction for inactive Cutout drawings while preserving their Blender Image datablocks, file links and `.blend` compatibility.
- New external images are tagged conservatively as Cutout-managed; packed, generated, dirty or externally shared images are never evicted.
- Import and Add Drawings release newly decoded buffers immediately after caching source dimensions, preventing large temporary memory peaks.
- The active drawings and a 24-image LRU working set stay resident for responsive slider scrubbing.
- Zero-user managed images left by Replace, Remove or driven-slot clearing are released and removed safely.
- Cutout library thumbnails load progressively in bounded batches with request and ready-state limits.
- The currently selected drawing still loads immediately; pending thumbnails use a lightweight loading icon.
- Global thumbnail cache resets now clear Cutout preview queues as well, preventing stale preview state after background changes, load or Undo.
- Removed the old warning at 256 images. Warnings now depend on genuinely resident non-evictable buffers or exceptionally large 2,048-entry libraries.
- Render preflight validates only drawing indices used by a Constant active Action; Driver, NLA, modifiers or non-Constant animation fall back to the conservative full-library check.
- Reorder and removal transactionally remap both the active Action and compatible Blender 5.1 NLA action slots, with full rollback on failure.
- Driven libraries can now delete content safely by converting the selected numeric slot to Empty, preserving the Driver contract and slider range.
- Reordering remains intentionally blocked while an active Driver controls Drawing because changing numeric Driver semantics automatically would be unsafe.

## 5.1.0 — Cutout Plane

- Added a lightweight Cutout Plane for replacement animation and 2D rigging.
- Select independent images, create one empty plane, then animate an integer Drawing slider from `0` (Empty) to `X`.
- Slider edits update Constant keyframes automatically, with deduplicated deferred synchronization during dragging.
- Added a large preview, a classic management list and configurable preview backgrounds.
- Reordering and removal remap existing Drawing keyframes; these operations are blocked when drivers or NLA strips make automatic remapping ambiguous.
- Every library entry stores a real Blender Image reference, while Cutout Plane renders use one managed per-frame image swap guarded by the existing render/undo safety system.
- Added bounded thumbnail-compositing caches and a lightweight scene rig index.

## 4.10.2 — Rename Sync, Settings UI & Cleanup

### Immediate layer rename synchronization

- The Sequence panel now renames layers through a dedicated rename-safe property instead of writing directly to `Object.name`.
- Layer rows, virtual tree rows, known rig/plane ownership snapshots and effect owner tags are retargeted in the same operation.
- The temporary missing-layer error shown before the delayed synchronization is removed.
- Duplicate Blender names use the final Blender-assigned name consistently.
- Linked multi-scene layer caches are invalidated safely after a rename.

### Settings panel redesign

- Settings are divided into Project, Display, Camera, Render and Tools.
- Image thumbnail, procedural color preview and alphabetical sorting controls are available under Settings > Display.
- Image thumbnails also have a quick toggle beside the Layers list.
- Project keeps current file, project folder and advanced import interface controls.
- Tools contains automatic orphan cleanup, practical repairs, advanced diagnostics and project statistics.
- Add-on Preferences remain the source of defaults for newly created scenes; N-panel controls affect the current scene.

### Bug fixes and cleanup

- Split layers now always store the owning rig name on their generated plane.
- Thumbnail cache cleanup respects other open scenes that still use image previews.
- Collection color variants update the intended scene even when Blender supplies a different callback context.
- Removed stale RNA cleanup entries and verified exact registration/unregistration symmetry.
- Camera-rig registration rollback now reports cleanup failures instead of silently hiding them.
- Cleaned formatting and unused loop variables detected by static analysis.
- Updated the add-on and manifest version to `4.10.2`.

## 4.10.1 — Bug Audit & Cleanup

### Custom Effects lifecycle

- Custom effect definitions are purged from the live registry during disable and rebuilt from the current `.blend` on enable.
- Removed or hidden custom node groups can no longer remain as stale menu entries after disabling and re-enabling the add-on.
- Missing custom effect lookups use a bounded negative cache instead of forcing a complete node-group scan on every UI query.
- File-load refresh failures now produce one diagnostic warning instead of failing silently.

### Runtime cache recovery

- Active effect IDs are periodically revalidated without returning to per-frame full scans.
- Manual modifier or shader-node changes are detected automatically after a short cache interval.
- Temporary invalid RNA references use a timed backoff instead of retrying the same failed discovery on every frame.
- Undo, file load and unregister continue to clear all runtime effect caches immediately.

### Code cleanup

- Removed twenty unused imports left after the 4.10 registry extraction.
- Restored the intended registration order: Object/Scene properties are registered before Custom Effects and the Effects runtime.
- Static checks cover undefined names, unused imports, duplicate classes and duplicate operator identifiers.
- Updated the add-on and manifest version to `4.10.1`.

## 4.10.0 — Effects Architecture

### Dedicated effect registry

- Effect identifiers, metadata, compatibility rules, performance labels and menu layouts now live in `effects_registry.py`.
- UI and diagnostics can inspect the effect library without importing the complete Geometry Nodes and shader runtime.
- The 36 built-in effect definitions remain semantically equivalent to 4.9.18.
- Existing layers, effect instance IDs, node groups and custom properties require no migration.

### Dependency cleanup

- `custom_effects.py` no longer imports the full effect runtime to refresh the library.
- A lightweight callback contract updates registered custom node effects without creating a circular module import.
- The main circular dependency group is reduced from ten modules to nine.
- `properties.py`, `ui.py`, `handlers.py` and project diagnostics use the dedicated registry where runtime operations are not required.

### Maintenance and lifecycle

- Registry refresh hooks are installed and removed explicitly during add-on registration and unregister.
- Import, register and unregister smoke tests cover the new module boundary.
- Updated the add-on and manifest version to `4.10.0`.

## 4.9.18 — Runtime Performance

### Procedural sequence timing

- Color, Gradient and Holdout frame durations now use a cached cumulative timeline.
- Frame lookup uses binary search instead of rebuilding and walking every duration on every evaluated frame.
- Transform animation does not disable the cache; only animated duration properties use the conservative live path.
- Reorder, duration edits, Undo, file load and sequence rebuilds invalidate timing automatically.

### Per-frame effect synchronization

- The frame handler resolves only rigs with active effects instead of scanning every Frame By Plane layer.
- Geometry modifiers and shader effect nodes are cached per rig and reused across frames.
- Animated effect-property mappings are discovered once per playback session instead of rescanning every F-Curve each frame.
- Image-aware effect source synchronization reuses resolved modifier and node targets.
- Socket and visibility values are written only when their evaluated value changed.

### Cache safety

- Runtime caches contain names, identifiers and temporary RNA references only; no project data is persisted.
- Caches clear on Undo, file load, unregister and structural effect changes.
- Renamed or externally rebuilt objects self-heal immediately or through a short periodic validation.
- Updated the add-on and manifest version to `4.9.18`.

## 4.9.17 — Centralized Render Safety

### Render-state contract

- Render detection now has one canonical implementation shared by handlers, timers, Scene sync and unregister cleanup.
- The runtime distinguishes `IDLE`, `BUSY` and `UNKNOWN` instead of treating failed API queries inconsistently.
- Mutation-sensitive paths proceed only when Blender explicitly reports an idle render state.
- Managed Frame By Plane renders can still perform the procedural and effect updates selected during render preflight.

### Handler and timer hardening

- Fixed the Effects Evolve frame handler continuing after a failed render-state query.
- Procedural frame updates stop during external renders and when render state cannot be confirmed.
- Deferred Blender-ID tasks retry while rendering is active and are discarded when the state is unknown.
- Render watchdog recovery and extension unregister use the same tri-state query.

### Blender Extensions

- Added the required `clipboard` permission for **Single Plane from Clipboard**.
- Updated the add-on and manifest version to `4.9.17`.

## 4.9.16 — Ownership & Render Process Hardening

### Background Render

- `Popen.poll()` failures are no longer interpreted as a finished render.
- Process, log and temporary snapshot remain available until child-process exit is positively confirmed.
- Failed `terminate()` / `kill()` attempts no longer discard the process reference or delete files still in use.
- The Background Render Status popup is read-only during `draw()`; log parsing and Scene-property refresh happen before the dialog opens or from the modal timer.
- Pressing `Esc` keeps the modal monitor alive when process termination cannot be confirmed.

### Native render safety

- Render-state query failures are treated conservatively in timers, frame handlers, Scene sync and unregister cleanup.
- Deferred Blender-ID writes are abandoned when Blender cannot confirm that no render job is active.
- Cosmetic collection-cache properties are not removed while render state is active or unknown.

### Rig / plane ownership

- Delete snapshots now store runtime object identity in addition to names.
- Blender `session_uid` is used when available, with pointer fallback.
- Reusing a deleted rig or plane name cannot transfer ownership to the replacement object.
- Each render plane has one authoritative snapshot owner.
- Broken `Shift+D` duplicates no longer claim the original rig's plane or overwrite its `fbp_parent_rig_name` marker.
- Deleting a broken duplicate cannot delete a plane still parented to or targeted by another live FBP rig.
- Direct Outliner renames are repaired by identity instead of name guessing.

### Custom Node Effects performance

- Custom effect definitions use a bounded metadata/interface signature cache.
- Repeated panel redraws avoid rebuilding unchanged effect definitions.
- Cache entries invalidate on registration, metadata edits, forced library refresh and unregister.
- Removed a duplicated `name=` argument in the Custom Node Group property declaration.

### Context Effects menu

With one or more Frame By Plane layers selected, use:

**Right Click in the 3D Viewport → Effects**

The menu shares the normal Effects registry and supports Image Effects, Mesh Effects and Custom Node Effects in horizontal category columns.

### Custom Node Effects

Open **Effects → Add Effect → Custom Nodes → Register Node Group…** to register a local Shader or Geometry node group with a custom name, icon and description.

Shader groups use `Color In → Color Out`, with optional `Alpha In → Alpha Out` and `UV Vector`. Geometry groups use `Geometry → Geometry`. Other visible value inputs become editable controls automatically.

## Compatibility policy

Layers created with an earlier native render or media-cache contract are rejected rather than migrated. Delete and reimport those layers with the current 5.1 version. Original media files are never deleted.

## Blender target

- Blender **5.1.x**, developed for **5.1.2**.
