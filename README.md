# Frame by Plane — Version 4.1.7

Rigged image planes for multiplane animation in Blender 5.1+.

## Version 4.1.7

- Leaf folders containing exactly one image sequence or one static image no longer create a redundant Blender Collection.
- The resulting layer is placed directly in the parent project Collection, regardless of whether the folder name matches the layer name.
- Flattened layers keep independent automatically varied color tags instead of inheriting a collection color.
- Parent Collections that receive flattened child layers remain neutral in the Multiplane Setup preview and in the Outliner.
- Folders containing multiple layers, child folders, or a single video keep their Collection behavior.

## Main features

- Import single images, native image sequences and videos as controllable planes.
- Create procedural Color, Gradient and static Holdout planes.
- Build multiplane scenes from folders and grouped sequences.
- Edit timing, opacity, visibility, Crop, Extend and layer order from the UI.
- Fit image planes to the camera using the real image bounds.
- Use alpha-aware holdout tools for compositing masks.
- Render in a separate Blender process with status and Stop Render controls.

## Backend policy

```text
Images / Image Sequences / Videos → Blender native nodes
Color / Gradient → procedural materials
Holdout Plane → static procedural mask
```

No Material Sequence backend and no automatic image cache copies are used.
