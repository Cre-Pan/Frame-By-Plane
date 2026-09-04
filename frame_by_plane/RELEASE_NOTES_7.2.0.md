# Frame By Plane 7.2.0 Pre-release

Frame By Plane 7.2 brings a complete dual-color Grease Pencil workflow to Blender 5.2 while retaining the camera, effect, timeline, import and stability work from 7.1.19.

## Grease Pencil colors

- Separate Stroke and Fill selectors in Draw, Vertex Paint and Edit modes.
- Stroke, Fill and Both modes keep independent RGBA colors.
- `X` swaps Stroke/Fill; `Shift+X` samples Stroke only.
- Mixed Edit selections show compact color swatches.
- Close Gap sits between Stroke/Fill/Both and Caps Type; `G` toggles it only in Draw Mode.
- Color, Close Gap, paint and edit operations follow Blender Undo ordering.

## Production workflow

- Camera aspect shapes, SD–8K/Custom resolution, linked pixels, orientation swap and saved format presets.
- Managed compositor nodes stay out of rendered output until Use Compositor in Render is enabled.
- Selected layer settings use Object Data Properties; Tool and N-Panel sections share the same controls.
- Image-plane, Generic Mesh and Grease Pencil effects retain artist data and use consistent list/grouped-menu UI.
- Scrub Bar, Timeline sync, import lifecycle and Animation/Storyboard template handling include the 7.1.19 stability fixes.

## Candidate status

This build is a GitHub pre-release for Blender 5.2.x LTS. The complete background, interactive, focused 7.2 and isolated install gates pass on Windows x64; the five platform packages are validated structurally and built deterministically.
