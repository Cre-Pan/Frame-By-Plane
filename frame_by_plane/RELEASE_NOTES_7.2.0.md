# Frame By Plane 7.2.0

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
- After an in-Preferences update, What’s New waits until Preferences is closed or left before appearing in the creative workspace.

## Release cleanup

- Final original 7.2 artwork with unchanged buttons and reload-safe popup scheduling.
- Fresh splash images are decoded once; existing images are refreshed after updates.
- Strict runtime-only ZIP inventory, source matching, platform wheel and license checks.
- Saved-project migrations remain supported. Generic Mesh remains opt-in Preview.

Requires Blender 5.2.x LTS. macOS Intel is package-validated, not natively runtime-tested.
