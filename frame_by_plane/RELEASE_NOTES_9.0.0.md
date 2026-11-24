# 🎞️ Frame By Plane — 9.0.0

Frame By Plane 9.0.0 brings **plane groups** you can animate as one piece, an exact **Layer Transform** panel, **Set Layer Origin**, smooth **Infinite Rotation** and keyframed **Opacity** on image layers that finally plays back. Top and Side views stay fast with many layers, and errors that used to stay in the console now show in Project Doctor. It installs on **Blender 5.2 LTS** and **Blender 5.3**. Everything from 8.5.1 is listed in the [8.5.1 release notes](8.5.1.md).

## 🆕 New in 9.0.0

- 📦 **Plane groups.** Ctrl+G on some layers makes a group with a **box rig**: the outline of its nearest and farthest plane joined at the corners. A click on a plane selects the whole group, a **double click enters it** to work on single planes while the others fade (also in Solid shading), with a **GROUP** badge styled like Solo. Esc goes up one level.
- 🎛️ **Group Controller.** One button (Layer List side bar, or the sidebar's Item tab) adds an Empty that the group's layers follow without moving. Move, rotate, scale and **keyframe** it to animate the whole group; its **Group Opacity** fades every layer of the group and can be keyframed too. A click on the group selects the controller, so G, R, S and I act on the group.
- ✂️ **Ungroup:** Ctrl+Shift+G on a selected group dissolves it; every layer stays where it is.
- 👁️ **Solo a group:** Z Pie Solo with a group selected shows the whole group.
- 📐 **Layer Transform** in Properties > Object and in the sidebar's Item tab: exact Location, Rotation and Scale of the layer, keyable with I, shown in the Graph Editor and Dope Sheet. Alt or Copy All to Selected sets every selected layer.
- 🎯 **Set Layer Origin** (right click > Frame By Plane > Layer): Origin to Geometry, Origin to 3D Cursor and Geometry to Origin, without moving the drawing. The Crop effect has an **Origin to Centre** button.
- 🔗 **Link Timelines:** a link button at the right of every timeline header (Timeline, Dope Sheet, Graph Editor, NLA, Sequencer), on by default, keeps them aligned frame by frame: the playhead and Start/End line up even when one editor has a wider channel list or an open sidebar. Scroll, zoom or resize any of them and the others follow. If the scene is used as a clip in the Sequencer of another scene, the Timeline lines up under that clip.
- ⏯️ **Choose the playback buttons.** Show Buttons in the Playback Options popover (arrow beside Play, in every timeline) turns Jump to Endpoint, Jump to Keyframe, Jump by Delta and Play Reverse on or off. Jump to Endpoint is on by default; the other jump buttons are hidden. A paste button before Start and End sets the In or Out to the current frame.

## 🛠️ Better and fixed in 9.0.0

- 🎚️ **Keyframed Opacity on image layers plays back and renders.** Before, the layer kept the last value of the slider at every frame. Solid shading follows it too.
- 🔄 **Infinite Rotation is smooth** during playback and keeps the drawing's proportions on a layer stretched on one axis.
- 🏷️ **Top and Side views with many layers:** names are laid out up to ten times faster and never end up on top of each other, even with dozens of layers close together. Moving the mouse no longer recomputes them.
- 🔲 **Rig styles:** a Legacy layer shows only its coloured wire; an Alpha Outline box sits around the drawing, not the whole canvas.
- 🩺 **Project Doctor > Runtime messages** lists the errors caught while drawing the viewport or changing frame in this session, with how many times they happened.
