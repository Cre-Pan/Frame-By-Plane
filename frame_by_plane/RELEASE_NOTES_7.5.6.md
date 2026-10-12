# 🎞️ Frame By Plane — 7.5.6

A Grease Pencil, Scrub Bar and Add Plane update for Blender 5.2 LTS.

## ✨ What's new

- ⏱️ **Magnetic Scrub Bar:** hold `<` to scrub, release it and the playhead snaps back to where you started with a small bounce. Exact on the bar, faster as the pointer moves away. A tap no longer pins the bar; pin it from the Viewport header.
- 🗂️ **Scrub Bar menu:** collapsible sections, a live Length slider and an Audio Scrubbing toggle.
- ↔️ **Hold `<` in the Timeline, Dope Sheet, Graph Editor, NLA and Sequencer:** move left or right to scrub from where the playhead is.
- 🎬 **Set Scene In/Out from Media:** an option (off by default) in Add Plane and Multiplane that fits the Scene range to a new Image Sequence or Video.
- 🎨 **Every selected color:** Edit Mode shows each distinct Stroke and Fill color as its own swatch, with dropdowns, Replace All and per-stroke Invert.
- 🖌️ **Material in Edit Mode:** pick the material slot without leaving Edit Mode.
- ➕ **Add Plane dialog:** one dialog for Image, Video, Color, Gradient and Holdout planes; Fit Camera to New Plane is optional.
- 🧹 **Leaner Grease Pencil tools:** the extra effect list, Ink Over Image, Create Missing Drawings and Limited Loop are gone.

## 🛠️ Fixes in 7.5.6

- A pinned Scrub Bar no longer redraws the viewport constantly while idle.
- Swap and swatch edits are safer: stroke-only strokes keep their colors, and editing a swatch never recolors the other side.
- Layers left locked by the old Limited Loop tool are unlocked on load.
- The Scrub Bar stays where it is placed: it no longer slides toward the mouse.
- The Strokes and Fills dropdowns show their color list again.
- Stroke/Fill colors: the first color picked for strokes that had none now shows, and the Draw colors are no longer replaced by the selection's colors after a visit to Edit Mode.
- Scrub Bar fixes: the playhead no longer jumps back after scrolling past the bar's end, a click right after the return glide lands where you click, and the return lands on the start frame even outside the scene range.

> Requires **Blender 5.2.x LTS**.
