# Frame By Plane feature guide

Frame By Plane is a Blender 5.2 LTS extension for image-sequence animation, Grease Pencil drawing, layered artwork and 2.5D multiplane compositing.

## Supported sources

- Still images and numbered image sequences
- Folders of animation frames
- Video files supported by Blender
- Layered PSD artwork
- Procreate projects
- Solid-color, gradient, holdout and cutout planes

## Animation workflow

- Loop, Ping-Pong and One Shot playback
- Frame offsets, holds, limited loops and sequence controls
- Viewport Scrub Bar with bookmarks and Preview Range
- Compact Timeline playback controls with configurable endpoint, keyframe and delta jumps
- Synchronized time controls across Timeline, Dope Sheet, Graph Editor, NLA and Sequencer
- Bidirectional Scene Strip frame synchronization while keeping the editor's current Scene
- Grease Pencil timing, onion skin and drawing exposure tools
- Independent Grease Pencil Stroke and Fill colors in Draw, Vertex Paint and Edit modes
- Stroke, Fill and Both drawing targets, mixed-selection swatches, X swap and Stroke-only Shift+X sampling
- Close Gap in the Tool Header with a Draw-only G shortcut and Undo-aware state
- Camera-facing layers, projectors and 2.5D depth controls

## Layer and effect workflow

- Layer List folders, visibility, solo, locking, selection and color tags
- Blend modes, clipping, opacity and alpha-aware geometry
- Reorderable, resettable non-destructive effect stacks
- Native Grease Pencil Shader Effects and modifiers in a selectable, reorderable list
- Grouped Grease Pencil effect picker with category icons and selected-effect settings
- Distortion, blur, color, lighting, stylization and utility effects

## Masks and compositing

- Shape, color, luminance, channel, gradient, noise and imported masks
- Grease Pencil masks with live preview and baked output
- Blender-native compositor groups with artist-node preservation and explicit render opt-in
- Safe Repair snapshots and rollback-aware project health checks

## Production and diagnostics

- Save/reopen and Undo/Redo-aware state management
- Background rendering and image-sequence output
- Diagnostic reports designed for GitHub bug reports
- No telemetry and no automatic project upload

For installation, see [INSTALLATION.md](INSTALLATION.md). For common failures, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
