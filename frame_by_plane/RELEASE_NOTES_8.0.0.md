# 🎞️ Frame By Plane — 8.0.0

Frame By Plane 8 LTS: Grease Pencil masks you can edit, Split into Multiple Planes, a SOLO badge, a new Live Tutorial, the Magnetic Scrub Bar and six languages, for Blender 5.2 LTS. It also includes the Grease Pencil polish prepared as 7.2.1, which was not published on its own.

## ✨ What's new

- 🎭 **Grease Pencil Mask you can edit:** **Edit Grease Pencil** brings the mask strokes back for drawing, **Done** returns to the layer, and an eye shows or hides the strokes. Blur and Expand each have their own checkbox. The mask now covers the whole shot from frame 1 wherever it is created, Ctrl+Z after drawing no longer removes the effect, and the mask is computed many times faster.
- ✂️ **Split into Multiple Planes:** from the frame list or right-click → Frame By Plane → Layer, turn every frame of a layer into its own plane, keeping position, size and effects.
- 💡 **SOLO badge:** a translucent badge at the top of the Viewport shows when Solo is on (layer Solo or the Z pie's Solo Selection). Hide Overlays hides it too.
- 🎓 **New Live Tutorial:** a redesigned guide with a color per guide, key caps and a clear HOW path for every action, plus a new Frame by Frame tutorial.
- 🧪 **Apply Effects:** bake a layer's image effects into the layer itself.
- ⏱️ **Magnetic Scrub Bar:** hold `<` to scrub, release it and the playhead snaps back to where you started with a small bounce. Exact on the bar, faster as the pointer moves away. A tap no longer pins the bar; pin it from the Viewport header.
- 🗂️ **Scrub Bar menu:** collapsible sections, a live Length slider and an Audio Scrubbing toggle. Return to Start has its own button next to the pin, and in Draw Mode the bar shows only the active layer.
- ↔️ **Hold `<` in the Timeline, Dope Sheet, Graph Editor, NLA and Sequencer:** move left or right to scrub from where the playhead is.
- 🎬 **Set Scene Length from Media:** an option (off by default) in Single Plane and Multiplane that fits the Scene range to a new Image Sequence or Video.
- 🎨 **Every selected color:** Edit Mode shows each distinct Stroke and Fill color as its own swatch, with dropdowns, Replace All and per-stroke Invert.
- 🖌️ **Material in Edit Mode:** pick the material slot without leaving Edit Mode.
- 🌍 **Six languages:** Italian, Spanish, French, German, Simplified Chinese and Japanese. Frame By Plane follows Blender's language, or pick one in Preferences → Interface → Language.
- ➕ **Fewer popups:** Single Plane (images, sequences and videos) and Multiplane show their settings in the file browser sidebar; Color, Gradient, Holdout, Hex and Grease Pencil planes are created at once and adjusted in Blender's Adjust Last Operation panel. Only drag and drop still opens a popup. Every layout follows Blender's own style, with a collapsible Camera section.
- 🧹 **Leaner Grease Pencil tools:** see *Removed in 7.5* below.

## 🌀 Deform Plane (Lattice)

- **Poses:** one-click deformations (Sway, Arch, Squash / Stretch, Taper, Shear, Bulge / Pinch, Wave, Flag and Curl), each added as a slider you can keyframe. Sliders mix freely and go from −1 to 1, so Squash becomes Stretch and Sway bends either way. **Custom** adds an empty pose and opens the cage to shape it by hand.
- Presets are exact at any cage density, and a preset that needs more control points refines the cage on its own.
- Changing the **Cage Grid** keeps the current shape, the poses and their animation instead of resetting the cage.
- Fixed: after a grid change the cage grew by the amount of the current deformation.

## 🎯 On-plane controls

- **Gradient Mask**, **Gradient Light** and **Tilt-Shift** handles now line up with the visible effect on non-square images. Existing projects render exactly as before.
- **Radial Gradient Mask** has its own handles (centre, inner and outer radius) and is now a true circle on non-square images instead of an oval.
- Touching a Gradient Light handle no longer resets Shadow Position.
- **Wave Mask** and **Voronoi Mask** get an on-plane arrow to rotate the pattern.

## 🧩 Compositor (Preview)

- **Opening a file no longer adds a compositor.** Earlier versions gave every scene an empty compositor on load, and F12 rendered through it. Files saved that way are cleaned up automatically.
- **Compositor Off really turns it off:** your own compositor, render settings and View Layers come back. The Frame By Plane nodes are kept, and turning it on again resumes the same setup.
- Building the compositor never changes F12 until **Use Compositor in Render** is on.
- New **Compositor | Refresh | Live Update** row: Live Update is off by default, so adding layers or effects no longer rebuilds everything after every click.
- **Color Grade** Temperature and Tint now work, and copied scenes no longer render the original scene's layers.

## ⚡ Performance

- Reordering and adding effects is about twice as fast on large stacks.
- Stacks that mix Image and Mesh effects are about three times faster to edit.

## 🛠️ Effect stack fixes

- **Hide in Render** now works for every Image effect.
- Duplicate places the copy directly above the original, inside the same group.
- Switching a variant (for example Pixelate → Hex Pixelate) keeps its place and replaces only the selected copy.
- Adding an effect with a group selected puts it inside that group.
- Copy / Paste Effect Stack and Effect Stack Presets reproduce the source exactly: order, groups, duplicated effects and local masks.
- Hiding a global mask no longer makes a semi-transparent layer more transparent.
- Masks no longer lose their UV input after effects are moved, removed or sorted.

## ✏️ Grease Pencil (from 7.2.1)

- New Gap Off / On icons with two connected buttons.
- Cleaner color controls, with a visible Swap Colors button in every mode.
- The Scrub Bar is always first in the centered Viewport controls.
- Gap Off correctly opens selected curves when the selection mixes open and closed strokes.

## 🗑️ Removed in 7.5

These tools are gone. Files that used them still open; effects already on a drawing stay as normal Blender effects.

- **Grease Pencil effect list** and its grouped picker (Reset, Move, Toggle, Repair Duplicates, compatibility report). Use Blender's own Modifiers and Visual Effects panels.
- **Draw on Canvas** (the Draw, Fill and Erase buttons next to a Drawing Plane).
- **Ink Over Image** panel.
- **Create Missing / Current GP Drawings**.
- **Limited Loop Blocks**. Layers they left locked are unlocked on load.

Drawing Timing keeps **Plane → GP**, **GP → Plane**, Offset and Auto Sync.

## 📁 Where files are saved

- Effect presets now live in the extension's own user folder. Presets from earlier versions are copied there automatically.
- Media that Frame By Plane generates (PSD and Procreate layers, converted animated images, image-sequence proxies, pasted clipboard images) now goes into an `assets` folder next to your saved `.blend`, so the project folder can be moved or shared as a whole. Unsaved files still write next to the source media.

## 🛠️ Fixes in 8.0.0

- Grease Pencil Mask works on planes with Crop applied: the mask stays aligned with what was drawn.
- No thin unmasked line along the image edge when a mask stroke runs past it.
- Adding an effect, a Grease Pencil Mask or a Clipping Mask from the pie menu can be undone with Ctrl+Z.
- Ctrl+Z while drawing in a Grease Pencil Mask no longer risks crashing Blender.
- Draw Mode Stroke/Fill colors stay stable, and the first stroke drawn with Auto Keying gets its fill color instead of black.
- The interface language follows Blender again after loading a file.
- Holding `<` in the time editors stops at frame 0 when Allow Negative Frames is off.
- A pinned Scrub Bar no longer redraws the viewport constantly while idle.
- Swap and swatch edits are safer: stroke-only strokes keep their colors, and editing a swatch never recolors the other side.
- Layers left locked by the old Limited Loop tool are unlocked on load.
- The Scrub Bar stays where it is placed: it no longer slides toward the mouse.
- The Strokes and Fills dropdowns show their color list again.
- Stroke/Fill colors: the first color picked for strokes that had none now shows, and the Draw colors are no longer replaced by the selection's colors after a visit to Edit Mode.
- Scrub Bar fixes: the playhead no longer jumps back after scrolling past the bar's end, a click right after the return glide lands where you click, and the return lands on the start frame even outside the scene range.

## 📥 Download the correct ZIP

| Computer | Release asset |
|---|---|
| Most Windows PCs | `frame_by_plane-8.0.0-windows_x64.zip` |
| Windows on ARM | `frame_by_plane-8.0.0-windows_arm64.zip` |
| Apple Silicon Mac | `frame_by_plane-8.0.0-macos_arm64.zip` |
| Intel Mac | `frame_by_plane-8.0.0-macos_x64.zip` |
| 64-bit Linux | `frame_by_plane-8.0.0-linux_x64.zip` |

Install the ZIP through **Edit > Preferences > Get Extensions > Install from Disk**. Do not install GitHub's automatically generated Source code ZIP.

> Requires **Blender 5.2.x LTS**. Projects from 7.x open without manual migration.
