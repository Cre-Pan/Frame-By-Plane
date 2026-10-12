# 🎞️ Frame By Plane — 7.5.3

A Grease Pencil, Scrub Bar and Add Plane update for Blender 5.2 LTS.

## ✨ What's new

- ⏱️ **Magnetic Scrub Bar:** hold `<` to scrub, release it and the playhead snaps back to where you started with a small bounce. Exact on the bar, faster as the pointer moves away. A tap no longer pins the bar; pin it from the Viewport header.
- 🗂️ **Scrub Bar menu:** collapsible sections and a live Length slider.
- 🎨 **Every selected color:** Edit Mode shows each distinct Stroke and Fill color as its own swatch, with dropdowns, Replace All and per-stroke Invert.
- 🖌️ **Brush and material in Edit Mode:** pick the Draw brush and the material slot without leaving Edit Mode. The brush button shows the brush of the selected strokes (or Mixed), and picking another brush restyles them.
- ➕ **Add Plane dialog:** one dialog for Image, Video, Color, Gradient and Holdout planes; Fit Camera to New Plane is optional.
- 🧹 **Leaner Grease Pencil tools:** the extra effect list, Ink Over Image, Create Missing Drawings and Limited Loop are gone.

## 🛠️ Fixes in 7.5.3

- A pinned Scrub Bar no longer redraws the viewport constantly while idle.
- Swap and swatch edits are safer: stroke-only strokes keep their colors, and editing a swatch never recolors the other side.
- Layers left locked by the old Limited Loop tool are unlocked on load.
- The Scrub Bar stays where it is placed: it no longer slides toward the mouse.
- The Strokes and Fills dropdowns show their color list again.
- The Edit Mode brush list only offers brushes that draw strokes (no erasers, Fill or Tint).

> Requires **Blender 5.2.x LTS**.
