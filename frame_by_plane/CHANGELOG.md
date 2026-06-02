## 2.3.13 Fixes

- Fixed folder/layer Holdout toggles so repeated clicks no longer overwrite the original material backup with temporary holdout materials.
- Replaced Holdout UI property buttons with explicit toggle operators for safer one-click enable/disable behavior on layers and collections.
- Folder Holdout now clears the whole collection if any child layer is already in temporary holdout mode.
- Added fallback recovery for old scenes where temporary holdout materials were accidentally stored as the original materials.

## 2.3.12 Fixes

- Fixed normal Blender X/Delete cleanup for Frame by Plane layers: the addon now remembers rig/image-plane links and removes the linked plane when a native delete removes only the rig.
- Added a Frame by Plane delete entry to Blender's delete/context menus when an FBP rig or linked plane is selected.
- Made selected linked planes resolve back to their rig more reliably for delete/duplicate actions, including old files with only the stored parent-rig name.
- Updated Single Plane import: selecting multiple images now creates one animated plane/sequence instead of importing only the first selected image.

## 2.3.11 Fixes

- Added the Vertical / Horizontal orientation selector to the Color Plane creation UI.
- Added the same orientation selector to the Hex Color Plane popup.
- Made Frame by Plane duplication more robust: selected linked planes are now resolved back to their rig before duplication.
- Added an automatic repair pass for rigs duplicated with Blender's native Shift+D, so the copied rig receives its own linked image plane and copied material slots instead of pointing to the original plane.

## 2.3.10 Release Candidate
- Prepared package for Blender Extensions release candidate.
- Manifest tags set to 3D View and Animation.
- Kept v2.3.9 cleanup state as release base.

## 2.3.9
- Fixed missing Color and Gradient icons by adding IMAGE/NODE_TEXTURE icon keys.
- Added a collapsible Maintenance / Diagnostics area in Settings.
- Moved Health Check, Import Report, Relink, Select Missing, Color Variants, Auto-clean and Emergency Render into the maintenance dropdown.
- Removed unused Open Project Folder operator from registration.
- Removed legacy White/Black Color Plane properties that are no longer exposed.
- Continued Blender Extensions cleanup and Python compile validation.

## 2.3.8
- Updated Color Plane presets: removed old Yellow, renamed/recolored Orange as Yellow (#FFB300FF), updated Purple (#9450F3FF) and Blue (#6697FFFF).
- Manual color edits now switch the preset selector back to Custom.
- Gradient choice rows now use full-width buttons: Linear/Radial with icons, Color-to-Color/Transparent-to-Color as text.
- Removed Open Project Folder button next to Build Direct.
- Converted Settings checkboxes into wider toggle buttons where practical.
- Changed Color Plane icon from BRUSH_DATA to IMAGE and Gradient icon to NODE_TEXTURE.

## 2.3.7
- Removed the Color Adjust tool and its unused properties/operators.
- Restored visible Emission button beside Color / Gradient / Holdout in Color Plane creation.
- Added icons to Gradient mode/type enum buttons.
- Changed default Gradient to Linear + Color to Color with #FF5E98 to #0F213E.
- Preserved ColorRamp data when changing gradient mode/type.
- Continued cleanup pass for Blender Extensions release preparation.

## 2.3.6
- Continued Blender Extensions cleanup.
- Create panel now uses EVENT_PLUS icon.
- Fixed Color Plane preset dropdown beside color picker.
- Synced Gradient controls between N-Panel and Shift+A popup.
- Gradient mode/type no longer reset the existing ColorRamp.
- Color-to-Color / Transparent-to-Visible now update the preview and active gradient material.
- Improved live updates for Adjust and Wiggle controls.

## 2.3.5
- Fixed Gradient creation buttons by drawing enum choices explicitly.
- Added Color Plane solid color presets next to the color picker.
- Moved render guard runtime state to WindowManager.
- Added cached collection-content flags for a lighter Layer View draw path.

## 2.3.4
- Gradient controls split into two rows: Center/Linear and Color-to-Color/Transparent-to-Visible.
- Emission Texture moved to the first Color Plane row and disabled for Holdout.
- Removed Fast Import operator monkey-patching; import operators now enter Fast Import directly.
- Moved Fast Import depth tracking from module global to WindowManager IDProperty.
- Kept Python compile clean for Blender Extensions release preparation.

## 2.3.3
- Release cleanup pass for Blender Extensions.
- Layer and collection names are clickable while reducing icon/name spacing.
- Restored collection color-tag icons in Layer View.
- Color Plane creation uses three buttons: Color, Gradient, Holdout.
- Holdout disables the Emission Texture control.
- Removed redundant INFO helper messages from UI panels/popups.

## 2.3.2
- Restored click-to-select on layer names.
- Simplified Color Plane creation to Color / Gradient / Holdout.
- Removed the creation name field; generated planes use automatic names.
- Reworked Gradient controls as button groups and removed the manual ColorRamp initialization step.
- Reordered and expanded camera ratio presets with Custom at the top and 4:3 still as default.
- Restored timing controls to the main Sequence panel.
- Made Color Adjust controls live via update callbacks.

## 2.3.1
- Improved Color Plane creation UI with Color / Gradient / Holdout dropdown.
- Combined Crop and Extend into one Edges floating window.
- Added Color Adjust floating window for image saturation, light/dark and contrast nodes.
- Forced Layer View names back to left-aligned labels.

# Frame by Plane v2.3.0

- Added three main generation modes: Color Plane, Single Plane and Multiplane.
- Reworked Layer View row drawing with compact left-side alignment and fixed right-side action strip.
- Kept the silent emission-property update fix to avoid recursive Color Plane freezes.

# v2.21.23 - Icon Registry Self-Reference Fix

- Fixed the Icon Registry import error caused by `constants.py` calling `fbp_icon()` before the function existed.
- Replaced dynamic `fbp_icon('STRIP_COLOR_XX')` keys in `FBP_ICONS` with raw icon string keys.
- Keeps the centralized Icon Registry workflow intact for live icon editing.

# Frame by Plane v2.21.22

- Fixed `name 'fbp_icon' is not defined` when live-testing or replacing only `core.py`.
- Added a local icon-registry fallback inside `core.py`, while keeping `constants.py` as the main place to edit icons.
- Updated Blender manifest version.

# Frame by Plane v2.21.21

- Added a centralized ICON REGISTRY in constants.py.
- Replaced hard-coded UI icon strings in core.py with fbp_icon() / fbp_strip_icon() references.
- Added inline comments for every registered icon, including duplicate-use markers.
- Kept current icon choices unchanged; this update only makes the icon system easier to edit and audit.

# Frame by Plane v2.21.20

- Rebuilt the Layers row layout with a simpler left/right split.
- Kept layer and collection names clickable while aligning them to the left.
- Left side now uses: visibility, compact nesting blanks, fold arrow, type/collection icon, name.
- Right side keeps the existing action icons compact and aligned: info, solo, holdout, linked plane selectability, lock, select rig/layers.
- Collection icons are now non-editable and follow collection color tags when available.
- Child layers use two BLANK icons per nesting level for a small, predictable indentation.
- Disabled, locked or solo-hidden rows visually dim only the icon/name area while keeping action buttons usable.

# Frame by Plane v2.21.18

- Removed the experimental GRIP drag row from the Layers panel.
- Restored the more stable v2.21.16 Layers behavior.
- Kept compact thin arrow icons and toggle behavior from the previous stable Layers pass.
- This is a rollback/fix build focused only on stabilizing the Layer View before further UI experiments.

# Frame by Plane v2.21.16

- Refined the Layers panel after testing the split layout.
- Restored thin arrow icons across the add-on where possible: SORT_ASC, SORT_DESC, RIGHTARROW and DOWNARROW_HLT.
- Removed the Rows slider from the Layers panel and shows all layers inside expanded collections.
- Removed vertical guide bars from nested collection rows and reduced nested indentation.
- Changed layer rig selection back to a real checkbox-style toggle, so clicking it again deselects the rig.
- Changed linked plane/image controls to toggle plane selectability instead of forcing selection; linked planes remain non-selectable by default.
- Made image-frame duration controls slightly more compact inside the frame list.

# Frame by Plane v2.21.15

- Reset the Layers panel row drawing to a 3-column split layout for better alignment.
- Kept visibility/type, name/frame and action icons in fixed columns.
- Restored native disclosure triangle icons for collapsible collections and native arrow buttons for layer move tools.
- Improved disabled visual feedback for hidden or locked layers without disabling the action buttons.

# Frame by Plane v2.21.14

- Reworked the Layers row layout while preserving the previous readable list style.
- Removed the collection object icon from collection rows and kept only the collection color tag.
- Moved visibility to the far-left column before expand/collapse arrows.
- Reordered row actions: Eye, tag/type, name and frame count, solo bulb, mask, select linked image plane, lock, select rig.
- Changed rig selection to checkbox icons, switching to LAYER_USED when the layer is locked.
- Changed linked image plane selection to reversible RESTRICT_SELECT icons.
- Replaced triangle icons with RIGHTARROW and DOWNARROW_HLT.
- Added compact indentation and a vertical guide for expanded collections.
- Simplified Shift+A > Frame By Plane to Color Plane, Image Plane and Multiplane, plus clipboard/hex helpers.
- Added Color Plane from Hex Color Code.
- Added Single Plane from Clipboard for image file paths copied to the clipboard.

# Frame by Plane v2.21.13

- Refined the Layers list layout: removed the Collection View label, added a Rows control, and reordered row icons to Eye, type/tag, name/frame count, Solo, Mask, Select Plane, Lock and Select Rig.
- Added procedural Color/Gradient layer behavior: selected color, gradient and holdout planes no longer expose image-frame import controls; the + workflow now creates/duplicates editable procedural planes.
- Added linked-plane selection tools for layer and collection rows.
- Updated layer icons: Gradient uses COLOR, custom Color uses BRUSH_DATA, White/Black uses IMAGE_ALPHA and Holdout uses GHOST_DISABLED.
- Updated mask icons to CLIPUV_HLT / CLIPUV_DEHLT and kept Shadeless/Emission on LIGHT_SUN everywhere.
- Reworked Color Plane creation options into White/Black, Holdout, Color and Gradient with contextual settings.

# Frame by Plane v2.21.12

- Improved Gradient Color Plane pivot behavior: radial gradients now scale and rotate around their visual center.
- Reworked gradient node mapping to use a real center pivot before Mapping, reducing radial drift and odd deformation while scaling.
- Added a Solid View fallback note/color update: Blender Solid View still cannot evaluate procedural ColorRamp shaders, but the plane keeps a readable viewport color.
- Kept the full editable Advanced Color Ramp workflow for Material Preview and Rendered view.

# Frame by Plane v2.21.11

- Fixed Advanced Color Ramp drawing so Blender no longer tries to create Material data-blocks from a read-only UI draw context.
- Added a safe Initialize Advanced Color Ramp operator for N-Panel creation UI.
- Prepared the gradient preview material during Shift+A Color Plane popup invoke, before the popup is drawn.

# Frame by Plane v2.21.10

- Improved Gradient Color Plane editing. The creation popup now exposes the native Advanced Color Ramp through a preview material.
- Gradient planes now use UV + Mapping nodes so linear/radial gradients display more reliably in viewport and render.
- Added gradient transform controls for offset, scale/ellipse and rotation on selected Gradient planes.
- Removed the old Basic Gradient Ramp UI in favor of the native Advanced Color Ramp.
- Removed depth sliders from the Layers list.
- Reordered layer icons: Bulb, Select, Mask, Eye, Lock.
- Added matching collection-level Select/Solo/Holdout/Visibility/Lock properties to support click-drag behavior across collection rows where Blender UI allows it.

# Frame by Plane v2.21.9

## Gradient ColorRamp Editing

- Added Blender native ColorRamp editing inside the Sequence panel for selected Gradient Color Planes.
- Named and tagged the internal ColorRamp node as `FBP_ColorRamp` for safer detection.
- Kept the creation popup simple with From/To colors, while the selected gradient plane exposes the real editable ramp.
- Native ramp edits are stored directly on the material, so color stops, interpolation and keyframes are handled by Blender.

# Frame by Plane v2.21.8

Layer list rollback and holdout icon alignment fix.

## Fixed

- Restored the previous Layers layout that was visually clearer.
- Kept the original icon order and row structure.
- Added only the Holdout toggle icon to layer rows.
- Added a matching Holdout toggle to collection rows without changing the rest of the layout.
- Removed the experimental aligned-column layout that made the Collection View confusing.

# Frame by Plane v2.21.6

Gradient and material editing cleanup.

- Improved Gradient Color Plane UI with a compact ramp-like From → To editor.
- Fixed gradient material generation: center gradients now use recentered generated coordinates and a real ColorRamp node.
- Gradient, solid color and holdout planes are now editable after creation from the selected layer panel.
- Refactored core rig/plane creation to use Blender Data API mesh creation instead of `bpy.ops.mesh.primitive_plane_add`.
- Fixed duplicate class registration in the previous test build.
- Added safer logging helpers for new code paths instead of silently swallowing unexpected errors.

# Changelog

## 2.21.5 - Layer, Camera, Crop and Gradient Fix

- Fixed camera ratio application before creating cameras and camera-ratio planes.
- Added more camera/render presets: HD 16:9, 4K UHD, Story 9:16, 4:3, Square, Photo 3:2, Cinema 2.39:1, 2:1 and Custom.
- Removed Tree View from the Layers panel and simplified the view to Collection View only.
- Removed the depth slider from layer rows to reduce visual clutter.
- Re-aligned Collection View rows so collection and layer control icons share the same order.
- Added an icon-only A-Z sort toggle.
- Added alpha-aware Holdout toggles back to layer and collection rows.
- Added per-layer Crop and Extend popup tools. Crop is evaluated before Extend.
- Made Crop/Extend values independent for each Frame by Plane rig.
- Added Gradient Color Plane support for center/linear alpha fades and color-to-color gradients.
- Restored safer viewport animation updates using a frame-change handler and viewport redraw tagging.

## 2.21.3 - UI Import Fix

- Fixed Layers Collection View and Tree View display issues by replacing fragile filtered UIList drawing with direct layer rows.
- Fixed Multiplane Setup collection dropdowns so opening a collection shows its pending layers.
- Added a per-layer Holdout toggle button directly in the Layers rows.
- Removed Holdout controls from the Sequence panel to keep masking actions with the layer stack.
- Changed Shift+A integration so Frame By Plane appears as its own top-level Add menu category instead of inside Image.
- Kept Object Color display as Texture while setting wireframe color to Object where Blender exposes that setting.
- Improved popup/tooltips and added missing English descriptions for internal update operators and key UI properties.
- Kept frame-change material preview handler registered for viewport animation playback.

## 2.21.2 - Import Foundation Update

- Reworked Layers into two clearer modes: Collection View and Tree View.
- Collection View now uses separate collapsible collection blocks with their own layer lists.
- Removed the adjustable layer-row slider from the Layers UI.
- Added persistent A-Z sorting for layers and collections.
- Kept layer row controls and side toolbar actions available in both layer workflows.
- Updated Import Project so it fills a collapsed Multiplane Setup grouped by collection before generation.
- Top-level project folders are preserved as setup collections when scanning imports.
- Added a collapsed-by-default setup view to make large imports easier to inspect before generating.
- Rebuilt Extend Plane as edge-padding geometry: the center image is no longer scaled or deformed.
- Extend Plane sliders now update selected planes live.
- Added Edge Pixel and Repeat Texture extension modes.
- Optimized material node trees: opacity at 100% no longer creates an opacity Multiply node.
- Shadeless/image-emission materials now use simpler Emission-based node trees instead of unnecessary Principled BSDF nodes.
- Color Plane emission materials now use simple Emission node trees.
- Added optional auto-clean for orphan Frame by Plane planes left after normal Blender deletion.
- Auto-clean removes unused Blender mesh/material/image datablocks when safe, but never deletes image files from disk.
- Corrected Shift+A menu name to Frame By Plane.
- Added Shift+A quick popup operators for Single Plane, Single Plane Animation, Multiplane, Multiplane Animation and Color Plane.
- Added Send To N-Panel option in the Multiplane popup for advanced setup review.

## 2.21.1 - UI & Workflow Update

- Added two clear layer-view modes: Collection View and Tree View.
- Added adjustable layer list height for the scrollable Layer Stack.
- Kept layer row controls available in both views, including depth slider, visibility, solo and lock controls.
- Removed the collection trash button from collection rows to avoid destructive clicks.
- Moved Tree View action buttons to a side toolbar.
- Added a Color Plane shortcut button to the Layers side toolbar.
- Added Shift+A > Frame By Plane menu entries:
  - Single Plane
  - Single Plane Animation
  - Multiplane
  - Multiplane Animation
  - Color Plane
- Improved Fit to Camera with a popup choice:
  - Fit Inside
  - Fill Camera
  - Match Width
  - Match Height
- Fit to Camera now uses the image ratio/base plane size instead of the extended rig mesh.
- Added alpha-aware holdout materials for image planes, preserving transparent image areas when possible.
- Added Import Project workflow that scans the Project Folder into the MultiPlane Setup list before generation.
- Added collection names to MultiPlane Setup rows.
- Added manual collection assignment for MultiPlane Setup rows.
- Generated setup collections are spaced with a larger gap between collection groups.
- Added Convert to Single Animated Plane operator for selected FBP layers.
- Added Split Sequence operator to move selected frames into a new plane at the same position.
- Removed the First Steps guide box from the creation UI.
- Kept Basic / Advanced toggle only in the Settings panel.

## 2.21.0 - Workflow Update

- Added Color Plane creation tools.
- Added Extend Plane controls.
- Added Holdout tools.
- Improved folder-based import behavior.
- Added Basic / Advanced UI mode.
