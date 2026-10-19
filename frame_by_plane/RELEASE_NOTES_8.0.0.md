# 🎞️ Frame By Plane — 8.0.0

Frame By Plane 8 LTS: Grease Pencil masks you can edit, Split into Multiple Planes, a SOLO badge, a new Live Tutorial, the Magnetic Scrub Bar and six languages, for Blender 5.2 LTS.

## ✨ What's new

- 🎭 **Grease Pencil Mask you can edit:** an **Edit** button in the effect header brings the mask strokes back for drawing, **Done** returns to the layer, and an eye shows or hides the strokes. The mask now covers the whole shot from frame 1 wherever it is created, Ctrl+Z after drawing no longer removes the effect, and the mask is computed many times faster.
- ✂️ **Split into Multiple Planes:** from the frame list or right-click → Frame By Plane → Layer, turn every frame of a layer into its own plane, keeping position, size and effects.
- 💡 **SOLO badge:** a translucent badge at the top of the Viewport shows when Solo is on (layer Solo or the Z pie's Solo Selection). Hide Overlays hides it too.
- 🎓 **New Live Tutorial:** a redesigned guide panel and a new Frame by Frame tutorial.
- 🧪 **Apply Effects:** bake a layer's image effects into the layer itself.
- ⏱️ **Magnetic Scrub Bar:** hold `<` to scrub, release it and the playhead snaps back to where you started with a small bounce. Exact on the bar, faster as the pointer moves away. A tap no longer pins the bar; pin it from the Viewport header.
- 🗂️ **Scrub Bar menu:** collapsible sections, a live Length slider and an Audio Scrubbing toggle. Return to Start has its own button next to the pin, and in Draw Mode the bar shows only the active layer.
- ↔️ **Hold `<` in the Timeline, Dope Sheet, Graph Editor, NLA and Sequencer:** move left or right to scrub from where the playhead is.
- 🎬 **Set Scene In/Out from Media:** an option (off by default) in Add Plane and Multiplane that fits the Scene range to a new Image Sequence or Video.
- 🎨 **Every selected color:** Edit Mode shows each distinct Stroke and Fill color as its own swatch, with dropdowns, Replace All and per-stroke Invert.
- 🖌️ **Material in Edit Mode:** pick the material slot without leaving Edit Mode.
- 🌍 **Six languages:** Italian, Spanish, French, German, Simplified Chinese and Japanese. Frame By Plane follows Blender's language, or pick one in Preferences → Interface → Language.
- ➕ **Add Plane dialog:** one dialog for Image, Video, Color, Gradient and Holdout planes; Fit Camera to New Plane is optional.
- 🧹 **Leaner Grease Pencil tools:** see *Removed in 7.5* below.

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
- Adding an effect, a Grease Pencil Mask or a Clipping Mask from the pie menu can be undone with Ctrl+Z.
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

> Requires **Blender 5.2.x LTS**.
