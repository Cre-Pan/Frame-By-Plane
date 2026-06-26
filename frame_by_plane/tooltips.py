"""Centralized, audited tooltips for Frame By Plane UI actions.

Blender uses ``Operator.bl_description`` for button hover help. Keeping the
long-form descriptions here makes it possible to review every action in one
place without mixing documentation text into implementation modules.
"""

from __future__ import annotations


# Context-sensitive actions keep their class ``description()`` method. These
# strings are used for the remaining operators and as a readable fallback.
EXACT_TOOLTIPS = {
    # Context-sensitive effect and list actions also receive a static fallback
    # for API documentation, search results and disabled-button hover states.
    "fbp.capture_camera_scale_reference": (
        "Capture the active camera, camera-space depth, focal length and sensor width as the reference used by Camera Scale Lock. Later camera movement or lens changes can preserve the plane's apparent framing relative to this stored state."
    ),
    "fbp.select_effect": (
        "Make this effect the active Effects-stack row on the selected Frame By Plane layer. The operation changes UI focus only and does not enable, disable, rebuild or reorder the effect."
    ),
    "fbp.add_effect": (
        "Add the chosen registered effect to every selected compatible Frame By Plane layer. Existing instances are preserved, incompatible layers are skipped and the new effect is inserted into the correct shader or geometry stage."
    ),
    "fbp.effect_header_warning": (
        "Show the diagnostic warning associated with the active effect. When the warning offers an automatic order repair, clicking it restores the recommended compatible effect order without changing effect parameters."
    ),
    "fbp.list_action": (
        "Run the requested Frames-list edit, such as move, duplicate, delete or reverse, on the checked entries. Frame durations move with their media and the native sequence backend is rebuilt only after the logical list changes."
    ),
    "fbp.open_effect_masks": (
        "Open the mask editor for this effect on the selected Frame By Plane layers. Existing masks remain attached and the operation changes only the Effects-panel editing target."
    ),
    "fbp.close_effect_masks": (
        "Close the per-effect mask editor and return to the normal Effects Stack. Attached masks, assignments and mask parameters remain unchanged."
    ),
    "fbp.add_effect_mask": (
        "Add the selected compatible mask to this effect across the current layer selection. Assignment is transactional: if one layer cannot be updated, all touched layers are restored."
    ),
    "fbp.open_effect_toolbar_menu": (
        "Open the selected Effects Stack menu for adding effects, managing Effect Groups or running stack-wide actions. Opening the menu does not modify any layer."
    ),
    "fbp.toggle_clipping_mask": (
        "Enable or disable Clipping Mask for this layer. When enabled, the layer uses the alpha of the physically lower compatible layer in the same collection; alphabetical display sorting does not change the source."
    ),
    # Cutout Plane
    "fbp.import_drawing_plane": (
        "Create a Cutout Plane replacement-animation rig and import the selected images as an ordered drawing library. "
        "The active drawing is shown through one lightweight plane; source files remain unchanged on disk."
    ),
    "fbp.add_drawing_images": (
        "Append one or more images to the active Cutout Plane library. New entries preserve their source paths and are added after the current library content without changing existing animation keys."
    ),
    "fbp.replace_drawing_image": (
        "Replace the image stored in the active Cutout library slot while preserving its slot index, timing and animation references. Only the selected entry changes; the original file is not deleted."
    ),
    "fbp.drawing_index_step": (
        "Move to the previous or next Cutout drawing and update the active library index. When Auto Key is enabled, the new drawing choice is keyed at the current timeline frame."
    ),
    "fbp.set_drawing_index": (
        "Make this Cutout library entry the active drawing. The operation updates the visible image and can insert an index keyframe when Cutout Auto Key is enabled."
    ),
    "fbp.remove_drawing": (
        "Remove the selected drawing from the Cutout library and safely remap subsequent indices. Driven or animated libraries preserve the numeric slot as an Empty entry when compacting would invalidate existing animation."
    ),
    "fbp.move_drawing": (
        "Move the selected Cutout drawing up or down while remapping the library and its animation references so keyed poses continue to display the intended image."
    ),

    # Effects stack and presets
    "fbp.set_effect_input_source": (
        "Choose which material stage feeds the selected effect: the previous compatible effect result, the untouched original Frame By Plane material, or the completed final material. Applied to every selected layer that contains this effect."
    ),
    "fbp.set_effect_debug_mode": (
        "Switch the selected effect to one of its diagnostic preview outputs, such as UV, alpha, mask or intermediate color. This changes only the effect preview mode and is useful for troubleshooting the stack."
    ),
    "fbp.copy_active_effect": (
        "Copy the active effect, including its editable properties, custom node inputs and input-source settings, to Frame By Plane's internal effect clipboard. No selected layer is modified until Paste Effects is used."
    ),
    "fbp.copy_selected_effects": (
        "Copy every checked effect from the active Frame By Plane layer to the internal clipboard while preserving their relative processing order. When no checkbox is enabled, the active effect is copied as a safe fallback."
    ),
    "fbp.copy_effect_stack": (
        "Copy the complete ordered effect stack from the active Frame By Plane layer, including visibility, render state, parameters and compatible custom inputs, to the internal effect clipboard."
    ),
    "fbp.paste_effect_stack": (
        "Paste the internally copied effect stack onto all selected compatible Frame By Plane layers. Existing effects with matching identities are updated; missing effects are created in the copied order."
    ),
    "fbp.clear_effect_stack": (
        "Remove every Frame By Plane effect from all selected layers and restore their base material and geometry state. This is undoable, but custom node groups remain available in the effect library."
    ),
    "fbp.reset_active_effect": (
        "Restore the active effect on every selected compatible layer to its registered defaults. For Lattice this is also the single recovery action: it removes an incomplete setup, refits the cage to the current plane and rebuilds the Lattice and mesh-detail modifiers."
    ),
    "fbp.setup_lattice_camera_flatten": (
        "Create or repair the planar cage, switch it to Camera Flatten and calculate a camera-relative correction using the active Perspective or Orthographic Scene Camera. The action is unavailable when no supported camera is active."
    ),
    "fbp.select_lattice_helper": (
        "Reveal and select the generated planar Lattice cage without changing its deformation. Object Mode transforms remain locked; use Edit Cage to move individual control points."
    ),
    "fbp.edit_lattice_helper": (
        "Select the generated planar cage and enter Lattice Edit Mode with all control points deselected. Select one point to move one corner or loop intersection, or press A to transform the entire cage."
    ),
    "fbp.finish_lattice_editing": (
        "Exit Lattice Edit Mode, return to Object Mode and restore selection to the owning Frame By Plane layer while keeping the deformation intact."
    ),
    "fbp.update_lattice_flatten": (
        "Recalculate Camera Flatten immediately from the active supported Scene Camera and the layer's current transform. This does not bake or disable live updating."
    ),
    "fbp.bake_lattice_flatten": (
        "Bake the current camera correction into the cage, stop live recalculation and return the Lattice to normal Freeform deformation so the layer can continue to be animated."
    ),
    "fbp.freeze_lattice_flatten": (
        "Freeze the current Camera Flatten result into editable Lattice points, stop live recalculation and enter a state suitable for manual cage editing."
    ),
    "fbp.reset_effect_control": (
        "Reset only the spatial values represented by this effect's viewport helper, such as center, angle, distance, range or softness. Other effect settings, stack order and visibility remain unchanged."
    ),
    "fbp.repair_effect_controls": (
        "Audit the current Scene for missing, duplicated, stale or orphaned Frame By Plane viewport controls, safely repair recoverable contracts and write a detailed report to the Text Editor."
    ),
    "fbp.sort_effect_stack": (
        "Reorder active effects into Frame By Plane's recommended processing order: base and UV stages first, color stages next, then mesh effects. Parameters and visibility states are preserved."
    ),
    "fbp.apply_effect_preset": (
        "Apply this built-in or user preset to the active effect on every selected layer that already contains it. Only parameters stored by the preset are changed; unrelated effects remain untouched."
    ),
    "fbp.save_effect_preset": (
        "Save the active effect's current parameters as a reusable user preset. Presets are stored in Frame By Plane's user configuration and remain available in other Blender projects."
    ),
    "fbp.rename_effect_preset": (
        "Open a rename dialog for this user preset. The preset values are preserved and only its library name changes; built-in presets cannot be renamed."
    ),
    "fbp.delete_effect_preset": (
        "Delete this user-created effect preset from Frame By Plane's preset library. Existing layers that previously used the preset keep their current values and are not modified."
    ),
    "fbp.copy_custom_effect_values_to_selected": (
        "Copy the active custom effect's exposed node-socket values from the active layer to every selected compatible layer containing the same effect. Node groups and effect order are not replaced."
    ),
    "fbp.copy_effect_to_selected": (
        "Add this effect and all of its current settings to selected compatible layers that do not already contain it. Layers that already have the effect are intentionally left unchanged."
    ),
    "fbp.duplicate_active_effect": (
        "Copy the selected effect from the active layer to every other selected compatible layer that does not already contain it. This is a multi-layer copy, not a second instance on the same layer."
    ),
    "fbp.set_effect_viewport": (
        "Enable or disable this effect in the 3D Viewport for all selected layers containing it. Final-render participation is controlled separately by the render icon."
    ),
    "fbp.drag_effect": (
        "Drag vertically to reorder this effect inside its compatible processing chain. Frame By Plane prevents moves that would cross an incompatible shader or geometry stage."
    ),
    "fbp.set_effect_render": (
        "Include or exclude this effect from final rendering on all selected layers containing it. Viewport visibility is controlled independently by the eye icon."
    ),
    "fbp.move_active_effect": (
        "Move all checked effects one valid step earlier or later, or directly to the beginning or end of each compatible chain, across every selected layer. Their relative order is preserved and a failed multi-layer move is rolled back."
    ),
    "fbp.move_selected_effects_relative": (
        "Move the checked effects as one stable block immediately before or after a chosen effect in the same shader or geometry chain. Every selected layer is validated first and partial failures restore the original ordering."
    ),
    "fbp.set_selected_effects_visibility": (
        "Show, hide or solo the checked effects in either the viewport or final render across all selected layers. Enable All restores every effect represented by the current 2D or 3D Effects view."
    ),
    "fbp.remove_selected_effects": (
        "Remove every checked effect from all selected Frame By Plane layers and reconnect the remaining chains. When nothing is checked, only the active effect is removed; Blender Undo can restore the operation."
    ),
    "fbp.create_effect_group": (
        "Create one persistent organizational group from the checked effects. All members must belong to the same shader or Geometry Nodes chain and exist on every selected layer; grouping does not change evaluation order, parameters or visibility."
    ),
    "fbp.select_active_effect_group": (
        "Select every effect assigned to the active effect's organizational group in the current Image Effects or Mesh Effects view. The operation changes only the grouped-action checkboxes."
    ),
    "fbp.ungroup_selected_effects": (
        "Remove the checked effects from their organizational groups across all selected layers. Effect order, node connections, parameters, viewport state and render state remain unchanged."
    ),
    "fbp.toggle_effect_group_collapse": (
        "Expand or collapse this Effect Group in the Effects Stack. Collapsing hides member rows behind one summary row and does not change nodes, modifiers, parameters, visibility or evaluation order."
    ),
    "fbp.toggle_effect_group_selection": (
        "Select or deselect every effect represented by this collapsed group row. The checkboxes are used by copy, remove, visibility and movement actions and do not change effect output by themselves."
    ),
    "fbp.rename_effect_group": (
        "Rename this Effect Group on every selected layer that shares it. Names are limited to 64 characters and must remain unique per layer; membership, effect order and parameters are preserved."
    ),
    "fbp.effect_group_action": (
        "Run the chosen shared action on every Effect Group member: select, move as one contiguous block, show, hide, solo or remove the organizational grouping. Multi-layer movement uses rollback on failure."
    ),
    "fbp.effect_group_actions": (
        "Open the complete Effect Group control popup with rename, collapse, selection, block movement, viewport visibility, render visibility and ungroup commands."
    ),
    "fbp.remove_effect": (
        "Remove this specific effect from every selected layer that contains it, then reconnect the remaining material or geometry chain. Other effects and the source plane material are preserved."
    ),
    "fbp.remove_active_effect": (
        "Remove the currently selected effect from all selected compatible layers and reconnect the remaining stack. The underlying image, sequence and base Frame By Plane material are not deleted."
    ),

    # Project setup and import
    "fbp.import_folder_hierarchy": (
        "Scan a folder hierarchy and add valid images, videos and numbered sequences to the Multiplane Setup preview. Subfolders become setup collections; no planes are generated until Generate Multiplane is pressed."
    ),
    "fbp.add_pending_plane": (
        "Add an empty layer row to Multiplane Setup below the active layer or inside the active setup collection. Assign media with Choose Images before generating the project."
    ),
    "fbp.edit_pending_plane": (
        "Open Blender's file browser to assign or replace the images, image sequence or video used by this Multiplane Setup layer. The operation edits only the pending setup, not existing scene planes."
    ),
    "fbp.drag_pending_plane": (
        "Click and drag vertically to reorder this pending Multiplane Setup layer inside its current collection. The grip stays visible but is disabled when no sibling position is available or alphabetical sorting controls the display order."
    ),
    "fbp.move_pending_plane": (
        "Move the active pending layer one position up or down within Multiplane Setup. Collection membership and the final generated depth order follow the updated tree position."
    ),
    "fbp.remove_pending_plane": (
        "Remove the active layer from Multiplane Setup before generation. Referenced source files are not deleted and existing Frame By Plane scene layers are unaffected."
    ),
    "fbp.clear_pending_planes": (
        "Clear every pending layer and collection from Multiplane Setup. This resets only the import preview; files on disk and already generated scene objects remain untouched."
    ),
    "fbp.scan_project_to_setup": (
        "Scan the configured Project Folder and rebuild the Multiplane Setup preview from supported media. Review names, collections, order and color tags before generating scene objects."
    ),
    "fbp.add_pending_collection": (
        "Create a new collection in Multiplane Setup with one empty child layer. The collection is created in the Blender scene only when the setup is generated."
    ),
    "fbp.auto_scene_builder": (
        "Scan the Project Folder and directly build collections, camera setup and Frame By Plane layers using the current creation defaults. Use Multiplane Setup instead when you need to review or reorder layers first."
    ),
    "fbp.generate_multiplane": (
        "Generate the complete Multiplane project from the current setup tree, including collections, rigs, image planes, native sequence materials, depth spacing and optional camera fitting."
    ),
    "fbp.import_sequence": (
        "Open the file browser and create an Image Plane from one image, a numbered image sequence or a supported video. Multiple selected stills become one animated native sequence."
    ),
    "fbp.replace_sequence": (
        "Replace the active layer's media while preserving its rig transform, layer identity, timing controls, keyframes and compatible effects. Source files are linked, not copied or deleted."
    ),
    "fbp.rename_sequence_for_blender": (
        "Safely rename source sequence files to a simple consecutive pattern that Blender's native image-sequence reader can load reliably. Review the preview carefully because this operation changes filenames on disk."
    ),
    "fbp.generation_report_popup": (
        "Open the latest generation report with created layers, warnings, skipped media and repair actions. The report is diagnostic and does not modify the current project by itself."
    ),
    "fbp.remove_corrupted_generated_planes": (
        "Delete only generated Frame By Plane objects identified by the last report as incomplete, missing or unsafe. Valid layers and all source image files on disk are preserved."
    ),
    "fbp.rename_generation_problem_sequence": (
        "Open the safe sequence-renaming dialog for the currently selected problem entry in the generation report. The dialog previews the new pattern before changing files on disk."
    ),
    "fbp.clear_generation_report": (
        "Clear the stored generation report and its problem list from the current scene. This does not remove generated objects, relink files or alter source media."
    ),
    "fbp.import_single_image": (
        "Create one Frame By Plane rig from the chosen image or video, or one animated plane from multiple selected images. Uses Blender's native image or movie texture backend."
    ),
    "fbp.import_folder_multiplane": (
        "Choose a folder, reuse the last import folder or read a copied folder path. Frame By Plane scans supported images, numbered image sequences, videos and subfolders, then opens a confirmation preview with counts and the first detected layer names. Auto Detect creates one Single Plane for one logical layer or a Multiplane for several layers. Forced Single Plane is accepted only for one real root-level still, video or numbered sequence. When additional layers would be ignored, a separate root-only confirmation is required. The reviewed folder snapshot fingerprints both the detected structure and lightweight source-file metadata, so generation stops if files are renamed, removed, replaced or edited before import. Dialog-only choices reuse the current preview instead of rechecking every source file, while confirmation always performs the final validation. Very large imports require explicit confirmation. Blender 5.1 does not pass ordinary dropped folders to extension File Handlers, so use this action or drop any supported media file from the target folder."
    ),
    "fbp.popup_single_plane": (
        "Open the compact Image Plane setup, then choose a still image, image sequence or video. Advanced defaults remain available in the Frame By Plane N-panel."
    ),
    "fbp.popup_single_plane_animation": (
        "Open the compact animated Image Plane setup and choose multiple images for one native sequence. Timing, loop mode, filtering and orientation are applied during generation."
    ),
    "fbp.popup_multiplane": (
        "Open the compact Multiplane setup for importing layered folders or multiple media sources. Send the setup to the N-panel when detailed review, grouping or reordering is required."
    ),
    "fbp.popup_color_plane": (
        "Open the compact procedural-plane setup and create a solid Color, editable Gradient or Holdout plane at the active camera ratio. No external image file is required."
    ),
    "fbp.create_color_plane_from_hex": (
        "Read a hexadecimal color code from the clipboard and create a solid Frame By Plane Color Plane using that value. Invalid or unsupported clipboard text is rejected without changing the scene."
    ),
    "fbp.import_single_image_from_clipboard": (
        "Create an Image Plane from a copied bitmap or copied media-file path. Temporary clipboard images are written to Frame By Plane's managed clipboard folder and imported as static images."
    ),

    # Layers and collections
    "fbp.save_file": (
        "Save the current Blender project to its existing path. If the project has never been saved, Blender opens the standard Save As dialog instead."
    ),
    "fbp.open_create_rig": (
        "Deselect current Frame By Plane layers and reveal the Create section so a new Image, Multiplane, Cutout, Color, Gradient or Holdout rig can be generated."
    ),
    "fbp.select_linked_plane": (
        "Unlock and select the mesh plane or planes controlled by this Frame By Plane rig for direct viewport editing. Click again to relock plane selection and return to rig-based control."
    ),
    "fbp.select_collection_planes": (
        "Toggle direct viewport selectability for every linked plane in this collection. Rig selection remains independent, and hidden layers are not made visible automatically."
    ),
    "fbp.add_color_plane_variant": (
        "Duplicate the active procedural Color, Gradient or Holdout layer as a separate editable variant with its own rig, material settings and layer entry."
    ),
    "fbp.ui_list_name_action": (
        "Click once to select the represented layer, frame, collection or setup item. Double-click the visible name to rename it while preserving Frame By Plane links and internal identities."
    ),
    "fbp.duplicate_or_default": (
        "Use Frame By Plane's safe duplication when selected objects belong to FBP rigs, preserving planes, materials, media lists and internal links. Otherwise fall back to Blender's normal duplicate command."
    ),
    "fbp.select_layer_exclusive": (
        "Select only this Frame By Plane layer and make it active. Use the row checkbox or collection selection controls when you need additive multi-selection."
    ),
    "fbp.select_all_layers": (
        "Select or deselect all Frame By Plane rig layers in the active scene according to the requested action. Locked layers remain protected from direct viewport selection."
    ),
    "fbp.toggle_lock": (
        "Lock or unlock the selected Frame By Plane rig so it cannot be accidentally selected or transformed in the viewport. Shift-click applies the same state to all selected FBP layers."
    ),
    "fbp.toggle_select_layer": (
        "Add this Frame By Plane layer to the current selection or remove it without clearing other selected layers. Locked layers cannot be selected until unlocked."
    ),
    "fbp.toggle_solo": (
        "Toggle this layer in the current solo set. When one or more layers are soloed, non-solo Frame By Plane layers are hidden without changing their normal visibility settings."
    ),
    "fbp.move_layer_stack": (
        "Move the active layer up or down in the Frame By Plane stack and recalculate its depth relative to neighboring layers while preserving its animation and effects."
    ),
    "fbp.isolate_layer": (
        "Temporarily hide every other Frame By Plane layer and keep only the active layer visible. Run again to restore the previous full-layer view."
    ),
    "fbp.popup_generate_camera": (
        "Open camera-generation options for the next project, including projection, output ratio, lens or orthographic scale, clipping range, fitting and pivot behavior."
    ),
    "fbp.fit_camera": (
        "Resize and position the selected layer so its actual image rectangle fits inside the active camera frame without changing the source image aspect ratio."
    ),
    "fbp.multi_fit_camera": (
        "Fit every selected Frame By Plane layer inside the active camera using each layer's actual media dimensions. Layer depth and source aspect ratios are preserved."
    ),
    "fbp.set_current_frame": (
        "Set the selected layer's animation start frame to the current timeline frame and rebuild native timing so the first logical frame begins here."
    ),
    "fbp.toggle_collection_collapse": (
        "Expand or collapse this collection in the Frame By Plane Layers tree. This is a UI-only change and does not alter Blender collection visibility or layer objects."
    ),
    "fbp.toggle_pending_collection_collapse": (
        "Expand or collapse this collection in the Multiplane Setup preview. The pending hierarchy and final generated collection structure remain unchanged."
    ),
    "fbp.set_pending_collections_open": (
        "Expand or collapse every collection in Multiplane Setup at once. This changes only the preview state and does not generate or remove scene objects."
    ),
    "fbp.select_collection_layers": (
        "Select or deselect all Frame By Plane rig layers inside this collection. Shift-click adds or removes the collection without clearing layers selected elsewhere."
    ),
    "fbp.toggle_collection_visibility": (
        "Show or hide all Frame By Plane layers inside this collection while preserving each layer's stored visibility state for later restoration."
    ),
    "fbp.toggle_collection_lock": (
        "Lock or unlock every Frame By Plane rig and linked plane in this collection to prevent accidental viewport selection and transformation."
    ),
    "fbp.delete_collection_layers": (
        "Delete all Frame By Plane rigs and owned planes inside this collection while leaving the collection itself available. Source media files on disk are never deleted."
    ),

    # Procedural planes and holdouts
    "fbp.create_color_plane": (
        "Create a rigged camera-ratio procedural Color, Gradient or Holdout plane using the current scene creation settings. The plane remains fully editable without an external image file."
    ),
    "fbp.reset_crop": (
        "Reset Left, Right, Top and Bottom crop values to zero on all selected compatible Frame By Plane layers and rebuild their visible image area."
    ),
    "fbp.reset_extend": (
        "Reset all border-extension values to zero on selected compatible layers, removing generated border geometry while leaving crop and the central image unchanged."
    ),
    "fbp.popup_crop": (
        "Open Crop controls for the selected layers. Crop changes the visible image boundaries without scaling the source texture or changing the rig transform."
    ),
    "fbp.popup_extend": (
        "Open Extend controls for the selected layers. Extend adds border geometry around the unchanged image center using edge-pixel clamping or repeated texture sampling."
    ),
    "fbp.set_selected_holdout": (
        "Convert all selected Frame By Plane layers to alpha-aware holdouts. Transparent source pixels remain transparent while visible pixels remove content behind them in the render."
    ),
    "fbp.holdout_all_except_selected": (
        "Apply alpha-aware holdout to every Frame By Plane layer except the currently selected layers, creating a quick inverse-mask setup for compositing."
    ),
    "fbp.restore_holdout_materials": (
        "Restore Frame By Plane materials that were changed by holdout tools and reconnect their normal color and alpha output without modifying source media or animation timing."
    ),
    "fbp.toggle_collection_holdout": (
        "Enable or disable alpha-aware holdout for all Frame By Plane layers in this collection. Each layer keeps transparent source pixels transparent."
    ),
    "fbp.toggle_layer_holdout": (
        "Enable or disable alpha-aware holdout on this layer. Visible source pixels become holdout while transparent pixels continue to pass through."
    ),

    # Project maintenance and rendering
    "fbp.remove_pending_tree_selection": (
        "Remove the selected pending layer, or remove the selected setup collection together with all of its pending child layers. No source files or generated scene objects are deleted."
    ),
    "fbp.remove_pending_plane_at_index": (
        "Remove this specific pending layer from Multiplane Setup before generation. The source media remains on disk and can be imported again later."
    ),
    "fbp.project_health_check": (
        "Inspect the current project for missing media, broken rig-plane links, invalid collections and common Frame By Plane consistency problems, then show a non-destructive report."
    ),
    "fbp.deep_addon_audit": (
        "Run an extended diagnostic over effect-stack contracts, the complete mask interaction matrix, render-only state restoration, native media bindings, material contracts, camera links, generated datablocks and scene ownership. Safe repair restores only recoverable generated relationships."
    ),
    "fbp.run_effects_contract_audit": (
        "Validate every active effect against its owner layer, detect unknown generated tags, inspect shader-stage order metadata and report stacks that differ from the recommended compatible order. Optional repair normalizes metadata and ordering without deleting effects."
    ),
    "fbp.run_mask_interaction_audit": (
        "Validate editable Shape Mask helpers and private images, clipping and matte source pointers, imported raster mask paths, source cycles and per-effect mask receiver wiring. Safe repair restores generated contracts and clears only invalid pointers."
    ),
    "fbp.run_render_parity_audit": (
        "Render the active Scene frame at a compact diagnostic resolution in Eevee and Cycles, compare premultiplied RGBA pixels and verify that real renders restore every tracked viewport, effect, modifier and shader-node state. Scene render settings are restored afterwards."
    ),
    "fbp.run_render_contract_audit": (
        "Execute the same temporary effect-state guard used by final rendering, verify lossless restoration of node, modifier and constraint values, and ensure generated Shape Mask and Lattice helpers cannot appear in Eevee or Cycles."
    ),
    "fbp.run_release_gate": (
        "Run lifecycle, native backend, effects, mask-interaction, render-contract, optional Eevee/Cycles pixel parity, persistence, Undo/Redo and Deep Add-on checks as one strict pre-release gate. Platform installation and add-on reload tests remain external."
    ),
    "fbp.relink_from_project_root": (
        "Search recursively inside the configured Project Folder for missing image and video filenames, then relink unambiguous matches without moving or renaming files."
    ),
    "fbp.select_missing_layers": (
        "Select every Frame By Plane rig whose current media list contains missing or unresolved source paths so the affected layers can be reviewed together."
    ),
    "fbp.sync_collection_colors": (
        "Apply Blender collection color tags to the viewport display colors of contained Frame By Plane layers, including configured per-layer variations. Materials and render colors are not changed."
    ),
    "fbp.apply_preferences_to_scene": (
        "Copy the current Frame By Plane add-on defaults into this scene's creation, camera, preview and render settings. Existing generated layers are not rebuilt automatically."
    ),
    "fbp.profile_effects": (
        "Measure actual frame-change and dependency-graph update time plus Blender process memory for the current scene, then report active and heavy effects. Profiling can temporarily evaluate the scene."
    ),
    "fbp.run_native_backend_regression": (
        "Run deterministic One Shot, Loop and Ping-Pong playback-math checks, inspect native Image cache ownership, validate every native layer and optionally evaluate representative timeline frames without changing media files."
    ),
    "fbp.create_native_regression_scene": (
        "Create a separate diagnostic scene covering static images, variable-duration One Shot, Loop, Ping-Pong, reversed rows, transparent rows, shared media sources, long sequences, mixed resolutions and missing-file recovery."
    ),
    "fbp.create_effect_regression_scene": (
        "Create a separate test scene with representative source planes, one sample for every registered effect, local per-effect masks and a real animated source/target matte matrix. Use it to compare viewport, render, Undo/Redo, save/reopen and future releases."
    ),
    "fbp.repair_render_state": (
        "Validate and repair native media bindings, timing, UV layers, material slots, material indices and render-sensitive effect state before rendering. Source image files are not modified."
    ),
    "fbp.background_render_frames": (
        "Launch a separate Blender process to render the configured frame range into the selected output folder, keeping the current Blender interface responsive during rendering."
    ),
    "fbp.stop_background_render": (
        "Request termination of the active Frame By Plane background-render process. Frames already written remain on disk; the current Blender session stays open."
    ),
    "fbp.background_render_status": (
        "Display the current background-render process state, completed frame count, total frame count and output directory without starting or stopping a render."
    ),

    # Sequence and timing
    "fbp.update_animation": (
        "Rebuild the selected layers' native sequence timing from Start Frame, frame durations and playback mode. Media files, transforms and unrelated effects are preserved."
    ),
    "fbp.transform": (
        "Apply the requested orientation transform to selected Frame By Plane rigs, such as standing the plane vertically or laying it on the ground, without altering image timing."
    ),
    "fbp.popup_transform": (
        "Open the compact transform tools for selected Frame By Plane layers. Changes are not applied until a transform action inside the popup is chosen."
    ),
    "fbp.update_emission": (
        "Rebuild selected layers' base materials using the current Emission/Shadeless setting. Image, alpha, effects and animation timing are reconnected to the updated shader."
    ),
    "fbp.update_opacity": (
        "Apply the current layer-opacity value to selected Frame By Plane materials using the minimal required alpha nodes. Full opacity removes unnecessary multiply logic where safe."
    ),
    "fbp.update_track": (
        "Create, update or remove camera-tracking constraints on selected Frame By Plane rigs according to the Track Camera setting and current active camera."
    ),
    "fbp.select_image_exclusive": (
        "Make this frame the active frame-list entry and move the timeline to the first scene frame where it appears. Use row checkboxes for additive frame selection."
    ),
    "fbp.insert_images_after_selected": (
        "Choose one or more images and insert them after the active frame, or after the last checked frame. The sequence backend is rebuilt while existing frame durations are preserved."
    ),
    "fbp.insert_linked_image_after_selected": (
        "Import a new linked image frame after the active or last checked frame. The file remains external and Frame By Plane rebuilds native timing after insertion."
    ),
    "fbp.insert_transparent_frame": (
        "Insert a logical transparent frame after the active or last checked frame. No placeholder image file is created; the transparent interval is represented by sequence timing."
    ),
    "fbp.link_image_frame": (
        "Choose a new image or video for this frame-list entry while preserving its position and duration. The previous source datablock is released only when it is safely unused."
    ),
    "fbp.select_all": (
        "Select all frame-list entries, deselect all entries, or invert the current frame selection according to the requested action. The active timeline frame does not change."
    ),
    "fbp.reverse_sequence": (
        "Reverse the complete logical frame order with one click. Frame checkboxes are ignored; per-frame durations move with their images, while transforms, effects and source files stay unchanged."
    ),
    "fbp.reverse_pending_sequence": (
        "Reverse this detected sequence directly inside Multiplane Setup. Frame filenames and source files remain unchanged; only the stored import order is inverted."
    ),
    "fbp.popup_sequence_settings": (
        "Open timing, playback and native-sequence controls for the selected Frame By Plane layer, including Start Frame, frame hold, loop mode and filtering."
    ),
    "fbp.duplicate_selected_layers": (
        "Safely duplicate selected Frame By Plane rigs together with owned planes, materials, frame lists, media bindings and effect settings, then assign independent internal identities."
    ),
    "fbp.merge_selected_to_active_sequence": (
        "Append selected Frame By Plane layers into the active layer as one animated sequence, preserve compatible frame data, then delete the merged source rigs and planes."
    ),
    "fbp.split_selected_images_to_new_plane": (
        "Move the checked frames from the active sequence into a newly created Frame By Plane rig at the same transform. Both resulting native sequences are rebuilt safely."
    ),
    "fbp.delete_sequence": (
        "Delete selected Frame By Plane rigs together with their owned planes and safely unused owned datablocks. Linked image files on disk are never deleted."
    ),
    "fbp.delete_or_default": (
        "When Frame By Plane rigs are selected, delete each rig together with its owned plane and safely unused data. For ordinary Blender objects, run Blender's standard Delete operation."
    ),

    # Custom effects
    "fbp.create_custom_node_effect": (
        "Create a new pass-through Shader or Geometry node group, register it as a custom Frame By Plane effect and apply it to the selected compatible layers for immediate editing."
    ),
    "fbp.edit_custom_node_effect_nodes": (
        "Select the linked plane, switch to the appropriate Shader or Geometry Nodes editor and open this custom effect's node group without changing effect values."
    ),
    "fbp.register_custom_node_effect": (
        "Register an existing local Shader or Geometry node group as a reusable Frame By Plane effect, with a chosen label, icon and description. The original node group remains editable."
    ),
    "fbp.hide_custom_node_effect": (
        "Hide this custom effect from future Add Effect menus without removing its node group or breaking layers that already use it. It can be registered again later."
    ),
}


CATEGORY_DETAILS = {
    "custom_effects": " This action works only with local custom node effects and does not modify external files.",
    "drawing_plane": " This action is limited to Cutout Plane library data and preserves external source files.",
    "feedback": " This optional action never collects project data or sends telemetry; external pages open only after an explicit click.",
    "geometry_nodes": " The operation is applied only to compatible selected Frame By Plane layers and supports Blender Undo unless the action only changes user-library metadata.",
    "operator_import": " Source media is linked from disk; files are not deleted unless the action explicitly states that it renames them.",
    "operator_layers": " This changes Frame By Plane scene organization or selection while preserving linked media files.",
    "operator_procedural": " This updates generated Frame By Plane material or geometry state and is applied only to compatible selected layers.",
    "operator_project": " This project-management action avoids modifying source media unless its description explicitly says otherwise.",
    "operator_render": " This render utility preserves the current project and reports errors instead of silently discarding frames.",
    "operator_sequence": " This sequence action preserves rig transforms and linked source files while rebuilding native timing only when necessary.",
}


MENU_TOOLTIPS = {
    "FBP_MT_add_effect": "Open the effect library for the current Image Effects or Mesh Effects view and add a compatible effect to the selected Frame By Plane layers.",
    "FBP_MT_effect_presets": "Open built-in and user presets for the active effect. User presets can be applied, renamed or deleted, and the current settings can be saved as a new preset.",
    "FBP_MT_effect_stack_actions": "Open actions for copying, pasting, resetting, sorting or clearing the selected layers' effect stack.",
    "FBP_MT_object_effects": "Open Frame By Plane's Image, Mask and Mesh libraries for the selected layer directly from Blender's object context menu.",
    "FBP_MT_object_masks": "Add Alpha Matte or Luma Matte effects from the dedicated Mask Stack.",
    "FBP_MT_object_effects_2d": "Browse compatible base, UV and image-processing effects for the selected Frame By Plane layers.",
    "FBP_MT_object_effects_3d": "Browse compatible Geometry Nodes and mesh effects for the selected Frame By Plane layers.",
    "FBP_MT_frame_by_plane_add": "Create the primary Frame By Plane layer types from Blender's Add menu. Secondary folder, PSD/PSB, Procreate and Toon Boom imports are grouped in the final More submenu.",
    "FBP_MT_frame_by_plane_more": "Open secondary import workflows for folders, copied folder paths, the last-used folder, PSD/PSB, Procreate and Toon Boom exports.",
    "FBP_MT_layer_blend_dropdown": "Choose a principal PSD or Procreate-style layer blend mode from a compact multi-column submenu. The current shared mode is marked with a check.",
    "FBP_MT_object_holdout": "Open alpha-aware holdout operations for selected Frame By Plane layers, including selected-only, inverse selection and material restoration workflows.",
}


def _expanded_description(cls, module_name: str, operator_id: str) -> str:
    exact = EXACT_TOOLTIPS.get(operator_id)
    if exact:
        return exact

    current = str(getattr(cls, "bl_description", "") or "").strip()
    if not current:
        label = str(getattr(cls, "bl_label", operator_id) or operator_id)
        current = f"Run {label} for the current Frame By Plane context"
    current = current.rstrip(". ") + "."

    short_module = module_name.rsplit(".", 1)[-1]
    suffix = CATEGORY_DETAILS.get(short_module, "")
    return current + suffix


def apply_tooltips(modules) -> None:
    """Apply reviewed hover descriptions before Blender class registration."""
    seen = set()
    for module in modules:
        module_name = str(getattr(module, "__name__", ""))
        for cls in vars(module).values():
            if not isinstance(cls, type) or cls in seen:
                continue
            seen.add(cls)
            bl_idname = str(getattr(cls, "bl_idname", "") or "")
            if not bl_idname:
                continue

            menu_description = MENU_TOOLTIPS.get(bl_idname)
            if menu_description:
                cls.bl_description = menu_description
                continue

            if not bl_idname.startswith("fbp."):
                continue
            # A custom classmethod description is already context-sensitive;
            # keep it and only provide a static fallback for API inspection.
            cls.bl_description = _expanded_description(cls, module_name, bl_idname)
