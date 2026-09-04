# Frame By Plane 7.1.19 LTS

Frame By Plane 7.1.19 is a Blender 5.2 LTS stability and compatibility update for image-sequence, Grease Pencil and 2.5D animation workflows.

## Bookmark palette compatibility

- Replaced fixed White with adaptive `NONE`, which follows the Viewport background contrast.
- Removed the Blue entry and matched Grey to Blender's `STRIP_COLOR_09` swatch.
- Automatically migrates legacy `WHITE` tags to `NONE` and legacy `BLUE` tags to `CYAN`.
- Added native regression checks for the complete palette and legacy migration.

## Preserved artist workflows

- Simplified Shift+A and moved hexadecimal Color Plane creation under More....
- Removed folder and clipboard-path imports from that menu while retaining Reimport Last Folder.
- Kept all Frame By Plane 7.1 project data compatible without a manual migration step.

## Blender 5.2 stability

- Repairs Preview Generic Mesh effects for Blender 5.2's dynamic modifier inputs, including transactional rollback and ownership that cannot adopt an artist's shared node group. Camera-dependent effects are excluded and Infinite Rotation direction is transferred correctly.
- Rechecks queued-task history epochs, runtime guards and rescheduled deadlines immediately before execution, even when an earlier callback changed them in the same batch.
- Fixes incomplete scene-index recovery and avoids repeat scans of unrelated objects after a validated empty result. Reduces camera aspect-label parsing during redraw.
- Separates a 10-shape aspect dropdown from SD/HD/2K/4K/8K/Custom resolution. Shapes default to landscape (4:5 starts as 5:4), with an icon-only Swap Dimensions button for portrait. Resolution changes preserve orientation.
- Always shows editable Width/Height pixels beside Resolution, wrapping to a second row in narrow panels, with an unaligned Swap Dimensions button.
- Links dimensions by default to preserve the aspect ratio; unlinked edits create a Custom aspect. Out-of-range linked edits are rejected atomically.
- Adds save/apply/remove Camera Format Presets in the blend file, preserving orientation and link state with Undo support. Render scale and pixel-aspect settings remain in Output Properties.
- Keeps GP material and native effect settings read-only in Edit Mode, with an explicit Object Mode action to retain reliable Undo. Point colors continue to use native GP Edit Mode history.
- Keeps Blender's native Viewport header draw function untouched, places the Scrub Bar controls in Blender's centered transform or Grease Pencil lane, and uses an official append callback only for remaining modes without either lane.
- Moves selected Frame By Plane layer settings to Object Data Properties with an Image icon, while the Layers and Grease Pencil stacks remain in Blender's Tool tab.
- Restores the complete root-panel set in the optional Frame By Plane N-Panel and removes the registered-panel inheritance that could make Blender lose the panels' `poll` callbacks.
- Makes the custom camera projection, lens/scale, clipping and aspect controls update the selected or Scene camera immediately.
- Gives Interface preference sections distinct icons and uses the Monkey icon for Updates and Support.
- Removes Interaction Info and its preference, Add Bookmark and the obsolete transparent-viewport label from the Scrub Bar popover; Add Bookmark remains available with right-click or A.
- Orders the Scrub Bar context menu as Add Bookmark, Select/Deselect All, active Keyframe Type, Mirror, Duplicate (Shift+D) and Delete.
- Includes reliable ownership for all 27 native Grease Pencil effect backends.
- Preserves add, remove, reorder, reset and duplicate repair while keeping artist-authored effects outside Frame By Plane cleanup.
- Uses a selectable effect list with a compact action toolbar and shows settings only for the selected effect.
- Adds a grouped icon menu for Stylize, Light & Edge, Warp, Stroke, Motion & Build, Utility and Surface effects.
- Keeps Compositor Safe Repair fail-closed while supporting Blender 5.2 RNA arrays and mathutils values.
- Fixes the canonical Felt Fuzz `Seed` and Alpha Mask socket contract while preserving the saved `Base Seed` alias used by earlier 7.1 files.
- Clears Grease Pencil raster-mask buffers during reload, Main replacement and add-on teardown.
- Removes proven orphan code and unused imports, including the retired Tool Sequence draw path, without changing saved project contracts.
- Avoids Windows long-path failures when rollback-safe rename manifests are finalized.
- Keeps image and layered-import file browsers available after Animation/Storyboard template changes and replaces missing Scene-property tracebacks from an incomplete live reload with actionable recovery guidance.
- Cancels cleanly when an already-open import dialog retains a stale Scene wrapper across New/Open/Reload.
- Uses Blender 5.2's valid Geometry Nodes icon in the expanded Grease Pencil Compatibility Matrix.

## Timeline and time editors

- Backports the compact playback controls from Blender PR 162412 to Blender 5.2 LTS.
- Lets artists show or hide endpoint, keyframe and delta jump controls.
- Adds time synchronization controls to Timeline, Dope Sheet, Graph Editor, NLA and Sequencer.
- Synchronizes Scene Strip frames bidirectionally without forcing an editor to switch its current Scene.

## Effect audit

- 6 Base effects passed isolated load/add/evaluate/remove checks.
- 79 Shader effects passed.
- 21 Geometry Nodes effects passed.
- All 27 native Grease Pencil effects passed.
- The new list, grouped menus, selection and native reorder path passed Blender UI and lifecycle tests.
- A Blender 5.2 UI-reference audit validated 1,037 literal icons, 71 enum icons and 565 operator calls.
- Cold/warm profiling confirmed that Shape Mask and Text Matrix initialization costs are cached rather than repeated.
- Rim, Shadow, Blur, Glow and Outline expose their additional Blender 5.2 native controls directly in the effect stack.
- Glow now resets to the intended 0.35 opacity and 6×6 size; Rim and Shadow use four quality samples.

## Platform support

- Blender 5.2.x LTS only.
- Windows x64 and ARM64.
- macOS Intel and Apple Silicon.
- Linux x64.
- Use the platform-specific package so Pillow and psd-tools match the operating system and processor.
