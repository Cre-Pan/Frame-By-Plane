# Changelog

All notable public changes to Frame By Plane are documented here.

## [8.1.0] - Unreleased

### Effects

- **Riso Print**: the old Seed only turned the misregistration, so it is now **Drift Angle**. New **Print Rotation** turns the halftone screen and the grain, and a real **Seed** reshuffles the grain and the dots (each ink's screen phase and the dot size jitter). Riso Print now has the Animation section of the other effects: **Animate** with **Speed** and **Stepped** boils the grain and dots over time.
- **Color Key** (Mask) now includes everything Chroma Key did. Invert keys the color out like a green screen, the new **Despill** greys the leftover key color along soft edges, the debug view gains **Distance**, and the Green Screen and Blue Screen presets moved here. Chroma Key is no longer a separate effect: files that use it are converted to Color Key automatically when opened. Despill applies when the key targets the whole layer.
- Every effect has its own icon in the add menus, the effect stack and the pie menu. Section titles no longer carry icons, internal variants share their family icon, and Solarize sits under Film.
- **Frame Stack** follows the playback of image sequences instead of their file numbers. Slices step through the drawings in the layer's timing order, so reordered or repeated rows, blank frames and sequences numbered from any value (0100, 1001…) stack correctly. Looping layers wrap the stack around the cycle when it restarts and Ping-Pong looks back the way the plane came; One Shot keeps the slices before the first frame empty. **Start Frame** of Fixed Range is now a timeline frame. Each layer keeps its own Frame Stack, so two sequences with the effect no longer show the same images (the same fix applies to Knit & Crochet). Saved files update on open.

### Lattice puppet pins

- **Puppet Pins** for the Lattice effect, in the spirit of Puppet Warp. **Add Pins** lets you click on the layer to place pins (Ctrl+Click removes one, Enter finishes). Move a pin with G or rotate it with R and the drawing bends around it while the other pins hold their areas still; keyframe pins like any bone (**Key Pins**). **Rest Pose** returns them to the undeformed layer and **Set as Rest** moves a pin to a better spot without bending the drawing.
- Pins use native Hook modifiers on the cage with automatic smooth weights, so they work with Poses and the cage, animate, save and render without anything running at playback time. **Follow Drawing** spreads each pin's influence through the opaque parts of the image, so a pin on a hand does not drag a separate nearby part across a transparent gap.
- The first pin refines the cage to about 24 points on the long side so the bend stays smooth.

### Lattice types

- The Lattice panel now opens on a **Type** menu: **Grid**, **Corner Pin**, **Bones**, **Pins** and **Camera**. The types stack on the same cage, and the panel lists the other types that are active on the layer. Cage and mesh settings and Poses fold into collapsible sections.
- All the handles and bones of a layer live in one **Controls** armature, so the viewport shows no relationship line per handle. Handles have their own shapes and colours (pins, bend pins, corners, point handles, IK targets), bones are drawn as sticks, and everything is posed and keyed in Pose Mode. The Lattice settings also appear in the armature's Object Data and Bone tabs.
- **Bones**, in the spirit of Moho: **Add Bones** lets you click joints on the layer (shoulder, elbow, hand). Right Click ends a chain, and a chain that starts on an existing joint branches from it. Ctrl+Click removes the last bone, and Enter finishes in Pose Mode. A chain of two or more bones gets an IK handle at its end. The bones are a native Armature that deforms the cage with smooth weights that follow the drawing, so it can be keyframed, saved and rendered like any rig. **Edit Bones**, **Key Pose**, **Rest Pose**, **Rebind** and **Remove** are in the panel.
- **Corner Pin**, like After Effects: four corner handles map the layer onto any quad with a true perspective, so the drawing foreshortens instead of only shearing. The handles keyframe, and the cage follows them live and on every frame. **Edit Cage** freezes the perspective into a Freeform cage.
- **Grid** gains **Point Handles**: one handle per cage point that you can move and keyframe without entering the cage's Edit Mode (cages of up to 100 points).
- **Pins** gain **Bend** pins, which stay in place and only rotate or scale their area, and a per-pin **Stiff Area** that keeps the area around a pin rigid.

### Viewport controls

- The handles of Crop, Extend and every effect with viewport controls (Swirl, Gradient Mask, Tilt Shift, Directional Blur, Pixelate, Shadow, Wind and the others), and the bounds handles of Shape Masks, are redrawn in one minimal style: thin flat bars, L corners, rings, crosses and arrows in white, like Blender's gizmos, turning to the theme's gizmo yellow while selected.
- New viewport controls: Alpha Matte and Luma Matte get a cross on the matte's centre that moves and turns it, and Riso Print gets an arrow for the Drift Angle.
- Handles are always drawn in front, in every shading mode. In Material Preview and Rendered the solid Crop and Extend bars used to sink behind the image.
- No more dashed relationship lines: handles follow their plane through a collapsed Child Of constraint instead of a parent. Files saved with the old handles are converted when the handles are next shown.
- Handles lie on the plane's real edges: they turn with a tilted layer and bend with it when the Lattice effect deforms it (Grid, Corner Pin, Bones, Pins, Camera), so Crop corners stay on the deformed corners.
- Gradient handles work like Figma's: Gradient Mask and Gradient Light stops are colour swatches (white and black for the mask, the ramp colours for the light) joined by a thin line. Stops added in the Gradient Light Color Ramp appear on that line in their own colour and slide along it with the mouse (with Undo).
- Arrows (Directional Blur, Wave Warp, Emboss, Wind and the other angle handles) are lines with an open V head, and the Directional Blur arrow head keeps its shape at any distance.
- Swirl, Bulge / Pinch, Ripple and Vignette show their reach as a dashed circle with a knob that changes the radius; Vignette also shows where it reaches full strength. Radial Gradient Mask shows its inner and outer circles dashed.
- Shape Masks show a dashed line where the Feather reaches full opacity.

### Z Pie and tooltips

- Z Pie: Hide, Solo and Holdout sit on the first south row; a second row adds Show Overlays (always) and Show Onion Skin (inside a Grease Pencil object). Lock and Selectability appear only while a Frame By Plane layer is selected, or one is still locked from the Pie. Cursor on Camera is an icon-only camera button.
- Operator and effect tooltips are one short sentence; the automatic "Use when", "Example" and "Note" paragraphs are gone. Italian translations follow.

### Fixes

- Halftone: Color Mode and Use Source Color had no effect, so BW Light, BW Dark and a custom Ink Color all rendered the source colors. They now work, and files saved with the old Halftone are updated when opened.
- Slice Shift: every band moved by the same Shift, which only slid the whole image sideways and left Bands with no visible effect. Neighbouring bands now move in opposite directions; files saved with the old Slice Shift are updated when opened.
- Grain no longer writes negative colors in dark areas.
- Oil Paint and Edge Distance Mask build about five times faster the first time they are added to a file (2 s and 1.5 s before), with an identical result.
- Felt Fuzz: the Render Density slider ends at 400,000 strands instead of 3,000,000. Rendering needs about 1 GB per 100,000 strands, so the old slider end could exhaust memory; higher values can still be typed.
- Extrude: in Array mode, transparent areas rendered black in Cycles once the copies used up the transparent-bounce limit. The automatic limit raised at render time now counts every Array copy.
- Paper Shards: chips darker than about 40% luminance sank below the plane and disappeared. Luminance Lift now raises chips from the plane (light ones for positive values, dark ones for negative values) and never pushes them under it. Files saved with the old Paper Shards are updated when opened.
- Paper Shards and Fiber Tufts: near the edge of a cutout, chips and fibers landed on transparent pixels (and rendered black) while opaque pixels next to them stayed empty. Each chip and fiber is now tested against the exact image alpha, and files saved with the old versions are updated when opened.
- Crosshatch: line edges are smoothed over one source pixel, which removes the jagged edges and moiré, and diagonal hatches now use the same spacing and width as the straight ones. Files saved with the old Crosshatch are updated when opened.

## [8.0.1] - Unreleased

### New effects

- **Frame Stack** (Mesh, for image sequences and videos): turns time into a solid. Earlier frames are stacked in depth behind the plane, one slice per frame, with per-slice offset, depth, rotation, twist and scale. **Follow Playback** keeps the newest frame on the plane and the past trailing behind; **Fixed Range** stacks a chosen range and its Start Frame can be animated to scroll the solid through time. Opacity offers the front/back threshold (faint front slices), **Depth Fade**, a **Luminance Key** that hides dark or bright areas without a separate mask video, and **Glow**, an additive mode that needs no sorting. An optional **Outline** draws the volume edges. The plane keeps full resolution; earlier slices use a grid whose detail is set separately for viewport, playback and render. Cycles automatically gets enough transparent bounces for the slices. Concept inspired by "Video Frame Stack" by hipofizus.

- **Knit & Crochet** (Mesh, for images, sequences and videos): rebuilds the image as yarn. **Knit** makes stockinette V stitches in columns, each row tucked under the next; **Crochet** makes single-crochet stitches (a head over two posts) in brick-offset rows. Every stitch takes its colour from the image, transparent areas stay empty, and sequences and videos stay animated. Thickness, plies and twist shape the yarn; Fuzz adds a woolly sheen; Color Variation and Hand-made add irregularity; Self Light keeps the yarn readable in unlit scenes. Stitch count is set separately for viewport, playback and render.

- **Riso Print** (Image, Pixel / Print menu): reprints the image with two or three spot inks on colored paper, like a risograph. Each ink takes its share of the color, drifts slightly out of register, and can turn into rotated halftone dots with mottled ink grain. Inks, paper, misregistration, dot size, grain and seed are editable, with presets for Pink & Blue, Three Drum and Green & Orange.

- **Oil Paint** (Image, Edges menu): an anisotropic Kuwahara filter. Color flattens into brush-stroke patches that follow the image's edges while contours stay sharp. Radius sets the stroke size, Anisotropy stretches strokes along edges (0 is the classic round filter) and Sharpness decides how crisp the stroke borders are. Transparent pixels never darken the paint.

- **Edge Distance Mask** (Mask, Nodes menu): a mask that ramps from the artwork's transparent edge inward over a set distance, for glowing borders, inner strokes and grow-in reveals (animate Threshold). Invert keeps the band along the edge. With Image Border on, the picture's own border counts as an edge, so fully opaque images get a frame-shaped falloff.

### Plane creation

- **Fewer popups.** Single Plane (images, sequences and videos) and Multiplane show their settings in the file browser sidebar instead of a dialog after the file browser. Color, Gradient, Holdout, Color Plane from Hex and Grease Pencil planes are created at once and adjusted in Blender's Adjust Last Operation panel. Only drag and drop still opens a popup.
- The settings follow Blender's own layout: collapsible Plane and Camera Settings, a compact Playback row and Playback and color preset dropdowns, two-row presets with Dimensions, and an icon-only Orientation. The orientation Swap button is gone.
- In the plane settings, **Set Scene In/Out from Media** is labeled **Set Scene Length from Media**.

### Fixes

- Image Projector: the projection was blurred by default because the light Radius also set the image size. The image size now follows the Cone Angle and Image Zoom only, Radius starts at 0 (labeled Softness) and the whole image fits inside the cone instead of losing its corners.
- Image Projector: image sequences numbered from anything other than 1 (for example 0101) projected nothing, and sequences got the wrong aspect ratio.
- Project Selected FBP Layer now follows the layer's timing (holds, loops) instead of freezing it on the current frame.
- Picking a movie as Projector Media now plays all of its frames; an image used by another plane is no longer renamed or turned into a sequence.
- Projector panel in Blender's layout: labels on the left, Focus in a collapsible section, and the Cycles note appears only when another render engine is active.

## [8.0.0] - Unreleased

Frame By Plane 8 LTS. Includes every 7.5.x change below.

### New

- Grease Pencil Mask: **Edit** / **Done** in the effect header to draw the mask again, and an eye to show or hide its strokes (hidden by default, stays visible once turned on). A new mask covers the shot from frame 1, wherever it is created.
- **Split into Multiple Planes** in the frame list and in right-click → Frame By Plane → Layer: one plane per frame, keeping position and effects.
- A translucent **SOLO** badge at the top center of the Viewport while layer Solo or the Z pie's Solo Selection is on; Hide Overlays hides it.
- Redesigned Live Tutorial with a Frame by Frame guide: each guide has its own color, readable icons and key caps, a HOW path for every action and a card that fits its text.
- Grease Pencil Mask panel: eye, Opacity and Invert on one row; Blur and Expand each have a checkbox that turns its slider on; Edit and Visibility move into a closed Grease Pencil Settings section.

### Fixes

- Grease Pencil Mask stayed misaligned or empty on planes with Crop applied; the mask is now rasterized over the uncropped image rectangle that the plane UVs use.
- A thin unmasked line no longer shows along the image edge when a Grease Pencil Mask stroke runs past it.
- Ctrl+Z after drawing in a new Grease Pencil Mask removed the effect; pie menu effect and mask buttons now push their own undo step.
- Ctrl+Z while drawing in a Grease Pencil Mask could crash Blender: cached drawing references are now dropped on Undo and Redo.
- Editing a mask on a later frame no longer adds an empty key that hid the mask.
- Grease Pencil Mask rasterization is many times faster with identical output.
- Dropping media in the Viewport opens the Import with Frame By Plane window again; it failed with an error after the 8.0 merge.
- In Draw Mode with Close Gap (or Fill in Both mode), existing strokes were closed and refilled when they came into view: scrubbing onto the first keyframe, switching from an empty layer, or moving or pasting a keyframe onto the playhead. Only new strokes change now.
- The Draw Mode color sync does about an eighth of the work per update on long animations.
- An open tutorial card no longer redraws the Viewport twice a second while nothing changes.

## [7.5.4] - Unreleased

Version bumped to 7.5.x (7.5.0 was an internal test build).

### New

- In Draw Mode the Scrub Bar shows, snaps to and edits only the active layer's keyframes; other modes still show every visible layer.
- The Viewport header has a **Return to Start** toggle next to the Scrub Bar pin. The Onion Skin button left the header; the Onion Skin settings stay in the Scrub Bar menu.
- **Set Scene In/Out from Media** (off by default) in the Add Plane dialog, the Multiplane dialog and the sidebar: after creating planes from an Image Sequence or a Video, the Scene Start and End cover their animation (one cycle, including Frame Hold). Still images never change the range.
- The Scrub Bar plays the audio under the playhead when **Audio Scrubbing** is on (Blender's own Timeline setting, now also a toggle in the Scrub Bar menu).
- Holding `<` (or Shift+,) in the Timeline, Dope Sheet, Graph Editor, NLA and Sequencer scrubs the playhead left and right from where it is, follows Shift Slowdown, and glides back to the start on release when Return to Start is on. Esc or right-click cancels.

### Fixes

- Holding `<` in the Timeline and other time editors no longer moves the playhead below frame 0 when **Allow Negative Frames** is off in Blender's Preferences.
- Strokes that never had a vertex color read as transparent black. Picking a Stroke or Fill color over one of those kept alpha 0, so nothing changed on screen; the first color picked over an unset one now gets full alpha.
- Leaving Edit Mode no longer turns the Draw and Vertex Paint colors into the selection's colors (often transparent black on uncolored strokes, which also made new fills invisible). Paint modes get back the colors they had before Edit Mode.
- Holding `<` past the end of the Scrub Bar and then moving away from it no longer snaps the playhead back toward the start.
- A click right after the return glide is hit-tested where the pointer really is, so drawing straight away is no longer taken as a Scrub Bar click.
- The return glide lands on the start frame even when it lies outside the scene or preview range.
- Older saved Mouse Magnet on/off and Strength values no longer shrink the Precise Range; Precise Range is also in the Scrub Bar menu under Scrub Speed.
- Editing a swatch can no longer move the open color picker onto another color group when two colors become equal.
- Swap in Edit Mode says why when nothing can be swapped.
- The Scrub Bar menu aligns its labels and is a little wider.
- The Scrub Bar no longer slides left and right toward the mouse. **Mouse Magnet** in Preferences is now **Precise Range**: the distance from the bar within which scrubbing with `<` follows the pointer exactly.
- The Strokes and Fills dropdowns drew an empty list in Blender 5.2 (the list used a layout type Blender no longer accepts); the color list shows again.
- A pinned Scrub Bar no longer redraws the viewport on every timer tick while the mouse rests in the 3D View; hover updates only redraw when the hovered key or bookmark changes. Timer events are no longer swallowed during a hold, and edge scrolling uses the remembered pointer position.
- Pressing Shift or Ctrl while holding `<` before moving no longer jumps the playhead.
- If the Viewport or object goes away during the return glide, the playhead still lands on the start frame.
- Stroke and Fill swatches live in separate lists, so a change on one side can never make an open color picker edit the other side.
- Swap skips strokes whose material draws only a line or only a fill, instead of painting them with an empty color, and no longer adds an empty Undo step when nothing is selected.
- The Edit Mode header no longer rescans the selection on every redraw before the first sync.
- Layers left locked by the removed Limited Loop guard in older files are unlocked on load.

### Apply Effects

- **Apply Effects** (Effects stack menu) bakes a layer's image effects with Cycles into PNG frames in `assets/baked/`, and the layer then plays them, so the result shows in Solid view too. The image effects are switched off, not removed, so the eye icons bring them back; mesh effects stay live. **Keep Original** puts the baked frames on a copy and hides the original instead.

### Languages

- The interface is translated into Italian, Spanish, French, German, Simplified Chinese and Japanese. **Preferences → Interface → Language** is Automatic by default (follows Blender's language); it can also be set to English or to one fixed language.

### Files and storage

- Effect presets are saved in the extension's user folder (`bpy.utils.extension_path_user`) instead of Blender's config folder or `~/.frame_by_plane`. Existing presets are copied over once; the old file is left in place.
- Generated media (PSD/Procreate layers, converted animated images, native sequence proxies, clipboard images) goes into an `assets` folder next to the saved `.blend`. Unsaved files still write next to the source media; the extension user folder is the last resort.
- Icons and the Geometry Nodes library are CC0-1.0; splash artwork is CC-BY-4.0 (see THIRD_PARTY_NOTICES.md).

### Release splash

- The release splash now opens after every installation of Frame By Plane: a fresh install, an update, or reinstalling the same version, from Blender Extensions or by drag and drop. Starting Blender again does not show it. **Show After Install / Update** in Preferences still turns it off.

### Grease Pencil

- Removed the Frame By Plane Grease Pencil effect list and its grouped effect picker (Reset, Move, Toggle, Repair Duplicates and the compatibility report). Grease Pencil drawings now use Blender's own Modifiers and Visual Effects panels; effects already added to a drawing stay on it as normal Blender effects.
- Removed **Draw on Canvas** (the Draw, Fill and Erase buttons next to a Drawing Plane), the **Ink Over Image** panel, **Create Missing / Current GP Drawings** and **Limited Loop Blocks**. Drawing Timing keeps **Plane → GP**, **GP → Plane**, Offset and Auto Sync.
- **Grease Pencil Drawing** in Shift+A is greyed out until a Frame By Plane plane is selected.
- In Edit Mode, selecting strokes with different colors shows every distinct Stroke and Fill color in the Tool Header (`Stroke colors ⇄ Fill colors`), up to 12 swatches; identical colors share one swatch. With more than 12, the larger side collapses into its own **Strokes** or **Fills** dropdown with a color list, **Replace All** and **Invert with Fill/Stroke**. Changing a swatch recolors only the selected strokes or fills that use that color.
- Only colors that are drawn count: if the selected strokes' material hides fills, the Fill side and the swap button disappear (and the other way round).
- **Swap Stroke / Fill** in Edit Mode now swaps each selected stroke's own colors, instead of painting every stroke with one color.
- Edit Mode's Tool Header has the **Material** selector (with Assign), so the material can be changed without leaving Edit Mode.

### Scrub Bar

- Holding **<** now follows the pointer exactly on the Scrub Bar and speeds up as the pointer moves away from it, up to **Far Speed** (Preferences, **Speed Ramp Distance**). Moving only across the bar no longer changes the frame.
- Fixed: after releasing **<** the playhead stayed on the scrubbed frame until the next key press. Blender events carry no timer handle, so the glide never ticked; Scrub Bar edge scrolling and the hover magnet were affected the same way.
- Releasing **<** snaps the playhead back to the frame where you started like a magnet: it accelerates, passes the start frame by a frame or two and settles on it (**Return to Start Frame**, on by default, with **Return Time** and **Bounce**). Any key or click during the glide lands on the start frame at once.
- The Scrub Bar menu in the Viewport header is split into collapsible sections (Scrub Bar, Return to Start, Scrub Speed, Onion Skin, Bookmarks, Preview Range). **Length** is now in the Scrub Bar section, goes down to 10% of the Viewport and updates the bar while it is shown.
- A quick tap of **<** no longer pins the Scrub Bar. Pin it from the Scrub Bar button or its menu in the Viewport header, or turn **Tap < Pins the Bar** back on in Preferences.

### Add Plane dialog

- **Single Plane**, **Video Plane**, **Color Plane**, **Gradient Plane** and **Holdout Plane** open one **Add Plane** dialog with the plane type in a dropdown at the top, so you can switch type without closing it. Settings are grouped into Animation, Plane and Material, Camera, and Placement sections.
- Adding a Single Plane no longer changes the scene resolution to the new image's aspect. Turn on **Fit Camera to New Plane** in the dialog to get the previous behavior.

## [8.0.0] — Prepared 2026-10-20

Includes 7.2.1, which was not published on its own.

### Effect stack performance

- Reordering an effect chain now writes the complete order once and rebuilds each material stage once, instead of rebuilding the stage for every one-step move. Adding effects to a populated stack is roughly twice as fast (16-effect stack: about 1.7 s → 0.8 s in total).
- Shader-stage order lookups scan each material once instead of recomputing node tokens two or three times per node.
- Mixed stacks (Image effects plus at least one Mesh effect) are about three times faster to edit: a 12-effect mixed stack drops from about 2.8 s to 0.95 s of total add time. The stack order is computed once per refresh, Mesh-effect modifiers are identified without re-reading node-group tags per registered effect, and composite stage materials only write socket values that actually changed (this also avoids needless material re-evaluation during playback).

### Compositor

- **F12 asks before rendering an out-of-date compositor.** When Use Compositor in Render is on and compositor changes are waiting for Refresh, F12 / Ctrl+F12 open a short warning with **Update** (refresh, then render), **Ignore** (render the previous setup) and **Cancel**. In every other case F12 renders exactly as before.
- **Opening a file no longer adds a compositor.** Every load gave each scene an empty "FBP Composite" compositor, and F12 then rendered through it even if the Frame By Plane compositor was never used. Files saved that way are cleaned up on load: an empty generated compositor is removed and the native render path comes back.
- **Compositor Off really turns it off.** The Compositor button only hid the panel, while the managed graph, its View Layers and Film Transparent stayed active and F12 still rendered through it. Off now puts back your own compositor, Use Compositing, Film Transparent and View Layer switches, removes the generated View Layers and stops live updates. The FBP nodes (including nodes you added) and the layer list are kept, and turning the compositor on again resumes the same setup.
- **Building the compositor no longer changes F12** until **Use Compositor in Render** is on. Generated View Layers used to render, and Render Managed Layers Only switched off your own View Layers, as soon as the setup was built. They now follow the render opt-in, which also switches them back immediately when it is turned off.
- The Compositor panel now starts with one **Compositor | Refresh | Live Update** row. Compositor turns the tools off as well as on, and Refresh rebuilds the setup; it is highlighted when changes are waiting or nothing has been built yet.
- **Live Update** is off by default: adding layers or effects or changing an effect type no longer rebuilds the compositor after every click. Effect values (mix, thresholds, colors) still update immediately. Turning Live Update on applies any waiting change, and enabling **Use Compositor in Render** brings a waiting setup up to date before rendering.
- The compositor **Color Grade** effect now changes the image. It used a Color Balance mode that ignores Temperature and Tint, and wrote the same value to both white points, which cancel out.
- A copied scene (Full or Linked Copy) no longer renders the original scene's layers into every managed compositor layer.
- With Live Update off, dragging an effect value after changing its type (or reordering) no longer writes into the old effect's node; it waits for Refresh like other structural edits.
- Grouping, ungrouping, moving and removing compositor layers, reordering compositor effects and assigning groups now follow Live Update / Refresh, instead of always rebuilding immediately (and raising an error, for example when the last layer of a folder was removed).
- **Share Unassigned Groups**, **Render Managed Layers Only** and View Layer names now mark the compositor for Refresh when changed.
- With **Render Managed Layers Only** off, turning a native View Layer's render switch on or off is no longer undone by the next compositor sync.
- **Restore Native Compositor** asks for confirmation, because it also deletes the editable Effects & Masks group.
- The compositor no longer re-tags its tree on every scene update while the render opt-in is active, and two layer-remap dropdowns can no longer show garbled names.

### Import

- **Drag and drop shows the import options.** Dropping images, a sequence or a video now always opens the Import with Frame By Plane dialog: Auto / Single Plane / Multiplane, Dropped Media or Parent Folder, the plane settings (Frame Hold, loop, orientation, Shadeless, alpha crop) and a **Camera** choice: **Keep Camera**, **Match Aspect** (change the existing camera's output aspect to the media) or **New Camera**, plus Fit to Camera and, for Multiplane, Layer Spacing. Single Plane and Multiplane now follow the same camera choice; before, Single Plane could only adapt an existing camera and Multiplane always created a new one.

### Tutorial

- The tutorial card is about half the size, follows Blender's Resolution Scale and display density (it ignored scales below 1.0 and was too small on high-density displays), can be **dragged by its title bar** anywhere in the viewport and **collapsed** to the title bar alone, which still shows the current step.

### On-plane controls

- **Gradient Mask**, **Gradient Light** and **Tilt-Shift** handles now line up with the effect on non-square images. The blue and orange bars sat along the UV direction, so on a 16:9 image the visible transition ran at a different angle than the bars. Existing projects render exactly as before; only the handle positions are corrected.
- **Radial Gradient Mask** has its own handles: the yellow handle is the circle centre (drag to move, rotate to turn the handles), blue marks the inner radius where the mask is fully opaque and orange the outer radius where it reaches zero. The radial gradient is now a true circle on non-square images instead of an ellipse stretched to the image proportions (the shorter side keeps its size).
- Touching a **Gradient Light** handle no longer resets **Shadow Position** to zero.
- **Wave Mask** and **Voronoi Mask** get an on-plane arrow to rotate the pattern.

### Lattice (Deform Plane)

- **Poses**: one-click deformations — Sway, Arch, Squash / Stretch, Taper, Shear, Bulge / Pinch, Wave, Flag and Curl — each added as a slider that can be keyframed. Sliders mix freely and go from -1 to 1, so Squash becomes Stretch and Sway bends either way. **Custom** adds an empty pose and opens the cage to shape it; the pose is shown alone until **Back to Plane**.
- Presets land exactly on the cage surface (the B-spline cage no longer softens them depending on the grid density), and a preset that needs more control points refines the cage automatically.
- Changing the **Cage Grid** keeps the current shape, the poses and their animation instead of resetting the cage. Reset and Camera Flatten rewrite only the rest cage; poses keep their deformation on top of it.
- Fixed: refitting the cage after a grid change used the deformed plane's bounds, so the cage grew by the amount of the current deformation.

### Cleanup

- Removed about 700 lines of code that nothing used: 31 helper functions (diagnostic snapshots, legacy timing probes, layer sorting and report helpers), two dead constants and three unused imports. The static orphan audit now lists only two Scrub Bar helpers, which are left as they are.

### Fixes

- Holding `<` past the end of the Scrub Bar and then moving away from it no longer snaps the playhead back toward the start.
- A click right after the return glide is hit-tested where the pointer really is, so drawing straight away is no longer taken as a Scrub Bar click.
- The return glide lands on the start frame even when it lies outside the scene or preview range.
- Older saved Mouse Magnet on/off and Strength values no longer shrink the Precise Range; Precise Range is also in the Scrub Bar menu under Scrub Speed.
- Editing a swatch can no longer move the open color picker onto another color group when two colors become equal.
- Swap in Edit Mode says why when nothing can be swapped.
- The Scrub Bar menu aligns its labels and is a little wider.
- Masks that sample the layer UV (Luma/Alpha Matte, Gradient, Noise, Wave, Voronoi, Channel, Color and Imported masks) no longer lose their UV input after a UV effect is moved or the stack is sorted. They previously appeared frozen until another rebuild.
- Removing a duplicated (multi-instance) effect now also removes its per-instance viewport and render visibility data instead of leaving it on the layer.
- **Clear Effect Stack** and **Remove Selected Effects** now update the saved effect-stack data, so removed effects (and their group membership) no longer remain as hidden records in the .blend file.
- **Copy / Paste Effect Stack** now pastes an exact copy: duplicated effects keep every instance with its own settings, and the visible stack order and effect groups are preserved. Previously only one instance per effect was pasted, with the active instance's values, and the order could change the look of the result.
- **Effect Stack Presets** now restore the saved stack order. Existing presets benefit too, because the order was already stored in them.
- Copying a stack or saving a preset no longer changes the source layer: duplicated effects were silently added to the group of their first instance.
- **Hide in Render** now works for every Image effect. The render only applied it to animated or Evolve effects, so other effects hidden for the render still appeared in F12 output. Mesh-effect render quality settings are now applied to every Mesh effect for the same reason.
- Toggling render visibility for a duplicated effect with several layers selected now reaches every instance.
- In stacks that mix Image and Mesh effects, hiding an effect, Solo, duplicating an instance and removing an instance are now reflected in the final result and in what Mesh effects read. Previously the change only appeared after another edit.
- Removing an effect instance that a local mask was attached to now returns the mask to the layer cleanly; Project Health no longer reports a missing receiver.
- Hiding a global (Layer) mask, in the viewport or for the render, no longer makes a semi-transparent layer more transparent. The hidden mask still multiplied the layer alpha once more (50 % alpha rendered at 25 %).
- Adding an effect while an effect group (or one of its members) is selected now places the new effect inside that group. It was added to the top of the stack while joining the group, so the group also swallowed every row in between.
- Switching an effect to another variant of its family (for example Pixelate → Hex Pixelate) keeps its place in the stack instead of moving it to the bottom. With two variants of one family on a layer (for example Swirl and Bulge Pinch), the switch now replaces the effect you clicked instead of the first one in the family. On a duplicated effect it replaces only the selected copy (the other copies and their settings stay), and a local mask attached to that copy moves to the new variant.
- **Paste Effect Stack** and **Effect Stack Presets** keep local masks on the right duplicated effect, rebuild mask combinations in stack order, and no longer add ungrouped duplicated effects to a group. In Merge mode, masks attached to a replaced effect return to the layer instead of pointing at nothing.
- Adding or removing an effect (including removing the last one) now updates the saved effect-stack data immediately.
- Removing an Image effect that had a local mask no longer disconnects the UV input of the effect above it (for example Swirl above a masked Wave Warp), which made the layer render wrong until the next edit.
- Re-adding an effect that is already on the layer no longer moves it, or its other copies, into the selected group. The same cause briefly grouped pasted copies.
- After a variant switch, a local mask on a duplicable effect follows the new variant's exact copy, so removing that copy returns the mask to the layer.
- **Duplicate** places the copy directly above the original effect, and a copy of a group member joins that group. The copy was listed at the bottom of the stack, although it was evaluated above the original, and the next reorder moved it to the bottom for real.

## [7.2.1] — Prepared 2026-09-07 (released as part of 8.0.0)

- Added paired Gap Off/On icons with separate grouping and explicit, idempotent choices.
- Replaced both Gap assets with the final high-contrast artwork supplied on September 7.
- Separated the GP color pair from Pin Mode and restored the Swap Colors button background in Draw, Vertex Paint and Edit modes.
- Placed Scrub Bar controls first in the centered Viewport lane across all six GP modes without copying Blender's header source.
- Fixed explicit Gap Off for mixed open/closed Edit selections; preserved Draw-only G toggle and Undo handling.

## [7.2.0] — 2026-09-05

### Stable release polish

- Integrated the final original 7.2 artwork with unchanged splash buttons.
- Deferred automatic What's New until Preferences is closed or left, preserving pending notices across add-on reloads.
- Avoided a redundant splash image decode on first load while refreshing existing images after updates.
- Added strict runtime-only package inventory and source/wheel/license checks to both build scripts.
- Extended exclusions for bytecode, temporary work directories and Blender backups; retained saved-project compatibility.

### Grease Pencil color workflow

- Added independent Stroke and Fill RGBA selectors to Draw, Vertex Paint and Edit modes, with native Stroke, Fill and Both behavior.
- Added compact mixed-color selection swatches, separate point/fill edits, `X` swap and continuous Stroke-only `Shift+X` sampling.
- Added Close Gap in the native Tool Header and a Draw-only `G` shortcut that preserves Edit Mode Grab.
- Added dedicated Undo steps and post-Undo Draw tracking recovery for swaps, sampling, Close Gap, point colors, fill colors and new Both-mode strokes.

### UI and rendering

- Added an unparented Object Data Properties image panel plus shared Tool/N-Panel roots for Layers, Grease Pencil and Layer Settings.
- Made the managed compositor explicitly opt-in for renders while preserving previous native render and artist-graph state.
- Retained the 7.1.19 camera format, linked pixel, effect-list, Scrub Bar, timeline synchronization and template/import stability work.

### Validation

- Added a focused Blender 5.2 feature gate for dual colors, Close Gap, Edit/paint Undo, compositor opt-in, Object Data placement and three-cycle lifecycle cleanup.
- Updated the five-platform GitHub Actions gate and installed-package checks for 7.2.0.

## [7.1.19] — 2026-08-10

### Stability and compatibility

- Migrated legacy White Scrub Bar bookmark metadata to adaptive None and legacy Blue metadata to Cyan.
- Kept hexadecimal Color Plane creation under More... while removing the two obsolete folder-import entries from the Shift+A menu.
- Added repository checks that reject drift between the manifest, package builder, Blender Extensions publisher, release notes and native release gate.
- Removed proven orphan code and unused imports while retaining the frozen 7.1.x identifiers and saved-data contracts.
- Fixed the canonical Felt Fuzz socket contract and moved its Alpha Mask upgrade out of per-instance creation.
- Cleared Grease Pencil raster-mask buffers during the normal runtime-cache lifecycle.
- Made import entry points tolerate stale `Scene` RNA wrappers left by New/Open/Reload instead of leaking a `ReferenceError`.

### UX and UI

- Replaced fixed White with adaptive None (`SNAP_FACE`), removed Blue, and matched Grey to Blender's `STRIP_COLOR_09` swatch.
- Simplified the Scrub Bar popover by removing Interaction Info, Add Bookmark and the transparent-viewport explanatory label.
- Reordered the Scrub Bar context menu to Add Bookmark, Select/Deselect All, active Keyframe Type, Mirror, Duplicate (Shift+D) and Delete.
- Kept Blender's native Viewport header draw untouched and verified seven repeated 2D Animation/Storyboarding template changes without a collapsed header.
- Rebuilt the Grease Pencil Effect Stack as a selectable list with add, remove, reorder and reset actions, matching the image-plane Effects workflow.
- Replaced the long native Grease Pencil effect grid with a grouped add menu: Stylize, Light & Edge, Warp, Stroke, Motion & Build, Utility and Surface.
- Expanded native Grease Pencil controls for Rim, Shadow, Blur, Glow and Outline, including quality, Wave/Object shadow modes, Depth of Field, Glow blend controls and Outline material/target settings.
- Fixed the Geometry Nodes icon in the expanded Grease Pencil Compatibility Matrix for Blender 5.2.
- Fixed Glow defaults to use Blender 5.2's actual `opacity` and `size` properties instead of ignored compatibility names.
- Backported the compact playback controls from Blender PR 162412 to Blender 5.2, with configurable endpoint, keyframe and delta jumps.
- Added time synchronization popovers to Timeline, Dope Sheet, Graph Editor, NLA and Sequencer plus bidirectional Scene Strip frame synchronization without forcing an editor to change Scene.

### Release engineering

- Declared and built five platform-specific packages for Windows x64/ARM64, macOS Intel/Apple Silicon and Linux x64.
- Kept package metadata deterministic and expanded release validation for the macOS Intel archive.
- Added a reusable static orphan-code audit and an isolated 133-effect Blender audit matrix.
- Hardened long-path rename recovery so manifests do not exceed Windows `MAX_PATH` during rollback-safe imports.

## [7.1.18] — 2026-08-01

### Stability

- Fixed persistent identity for Blender 5.2 native Grease Pencil Shader Effects and modifiers.
- Prevented repeated add actions from creating unmanaged duplicates.
- Restored native Grease Pencil effect removal, reordering, reset, duplicate repair and open-state persistence.
- Fixed Compositor Safe Repair snapshots for Blender 5.2 color, vector and rotation socket values.

### UX and UI

- Added Expand All and Collapse All actions to the Grease Pencil Effect Stack.
- Fixed Bookmark Color Tag swatches so White, Grey, Yellow, Red, Orange, Green, Blue, Magenta and Purple match their displayed names.
- Kept inline effect sections open or closed across redraws and file saves.
- Improved release documentation, search-oriented project wording and Blender 5.2 troubleshooting.

### Validation

- Passed the complete Blender 5.2.0 background regression suite.
- Passed the interactive 300-redraw sidebar stress suite and Preferences reload test.
- Validated all five declared-platform packages with Blender's native extension validator.
- Normalized release ZIP metadata so repeated builds produce identical SHA-256 hashes.

## [7.1.17] — 2026-08-01

- Added alphabetic Scrub Bar bookmarks, native color tags and improved bookmark interactions.
- Added bookmark appearance controls and Preview Range activation protection.
- Exposed native Grease Pencil Onion Skin controls in the Viewport popover.

## [6.1.0] — 2026-06-26

### Stable native workflow

- Promoted the 6.1 branch to **6.1 LTS**.
- Consolidated image and sequence playback around Blender’s native image-texture backend.
- Improved reliability for alpha, timing, loop modes, layer selection and project reopening.
- Refined single-plane, folder and multiplane imports.

### Effects and compositing

- Expanded and normalized the built-in registry to **62 effects**.
- Improved distortion, blur, color, stylization, masking and utility effect families.
- Refined alpha-aware masks, layer blend modes and effect ordering.
- Improved geometry-based cutout and thickness workflows.

### Interface and workflow

- Polished Layer List, Effects, Project, Camera, Render and Developer sections.
- Added clearer tooltips, diagnostics and copyable error reporting.
- Improved controls for selection, visibility, folders, blend modes and linked effect controllers.

### Reliability and performance

- Added autonomous developer tests and stricter release-gate checks.
- Improved save/reopen, undo/redo and Eevee/Cycles regression coverage.
- Removed obsolete code, redundant assets and orphaned release files.
- Reduced download size with platform-specific packages containing only compatible Python wheels.

### Distribution

- Added dedicated packages for Windows x64, Windows ARM64, macOS x64, macOS ARM64 and Linux x64.
- Kept an optional universal package containing dependencies for every supported platform.

## [6.0.0] — 2026-06-24

- Established the 6.0 generation with expanded effects, layered imports, masks, blend modes, cutout tools, camera workflows and developer diagnostics.
