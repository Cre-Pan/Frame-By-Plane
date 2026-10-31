"""Centralized, audited tooltips for Frame By Plane UI actions.

Blender uses ``Operator.bl_description`` for button hover help. Keeping the
descriptions here makes it possible to review every action in one place.
Each tooltip is one short sentence: Blender already shows the operator name
as the title and adds the keyboard shortcut when one is assigned.
"""

from __future__ import annotations


# Context-sensitive actions keep their class ``description()`` method. These
# strings are used for the remaining operators and as a readable fallback.
EXACT_TOOLTIPS = {
    # UI, filter and row actions.
    "fbp.reset_uilist_filter": "Clear search and sorting for this list.",
    "fbp.uilist_column_visibility": "Show or hide this column in the list.",
    "fbp.uilist_column_drag": "Drag to reorder this list column. Esc or right-click cancels.",
    "fbp.uilist_columns_reset": "Restore the default columns for this list.",
    "fbp.uilist_label_alignment": "Align names left, center or right in Frame By Plane lists.",
    "fbp.move_layer_filter_preset": "Move the active Layer Filter up or down.",

    # Grease Pencil Scrub Bar and mask-edit bridge.
    "fbp.safe_gp_mask_shrink_fatten": "Shrink/Fatten strokes on the active Grease Pencil mask.",
    "fbp.copy_grease_pencil_scrub_keyframes": "Copy the selected drawing keys of the active Grease Pencil layer.",
    "fbp.paste_grease_pencil_scrub_keyframes": "Paste the copied drawing keys at the current frame.",
    "fbp.duplicate_grease_pencil_scrub_keyframes": "Duplicate the selected drawing keys and move the copies.",
    "fbp.delete_grease_pencil_scrub_keyframes": "Delete the selected drawing keys.",
    "fbp.select_all_grease_pencil_scrub_keyframes": "Select, deselect or invert the drawing keys.",
    "fbp.mirror_grease_pencil_scrub_keyframes": "Mirror the selected drawing keys around the chosen pivot.",
    "fbp.set_grease_pencil_scrub_keyframe_type": "Set the key type of the selected drawing keys.",
    "fbp.set_grease_pencil_scrub_position": "Move the Scrub Bar to the chosen position in the viewport.",

    # Quick libraries, layer selection and import rows.
    "fbp.set_quick_mask_slot": "Store this mask in a Favourite Mask slot.",
    "fbp.reset_quick_mask_slots": "Clear all five Favourite Mask slots.",
    "fbp.quick_mask_library_popup": "Choose the mask for this Favourite Mask slot.",
    "fbp.quick_effect_library_popup": "Choose the effect for this Quick Effect slot.",
    "fbp.gradient_controller": "Select or create the Empty that moves the gradient. Alt-click unlinks.",
    "fbp.apply_layer_set": "Select this Layer Set. Shift adds, Ctrl/Cmd subtracts.",
    "fbp.motion_select_row": "Select this Motion row. Shift extends, Ctrl/Cmd toggles.",
    "fbp.select_generation_rename_row": "Select this sequence in the report. Shift extends, Ctrl/Cmd toggles.",
    "fbp.drop_media": "Import the dropped images, videos or folders as layers.",

    # Compositor Layers is explicitly Preview in the 8 LTS policy.
    "fbp.stack_row_action": "Edit a row of the Composite Stack (Preview).",
    "fbp.add_compositor_asset": "Add this node asset to the Compositor (Preview).",
    "fbp.layer_set_row_action": "Edit a source row of the Compositor Layer Set (Preview).",
    "fbp.layer_set_batch": "Enable, disable, invert or remove all sources of the Layer Set (Preview).",
    "fbp.remap_layer_set_source": "Replace a missing Layer Set source with the selected one (Preview).",
    "fbp.layer_set_preview": "Preview the output, mask or active source of the Layer Set (Preview).",
    "fbp.output_pass_action": "Add, remove, select or reorder output passes (Preview).",
    "fbp.validate_composite": "Check the composite for missing sources and broken links (Preview).",
    "fbp.compositor_package_action": "Add, remove, duplicate or reorder a compositor package (Preview).",
    "fbp.compositor_auto_layers": "Generate compositor layers from the scene (Preview).",
    "fbp.compositor_select_row": "Select this Compositor Layer. Shift extends, Ctrl/Cmd toggles (Preview).",
    "fbp.compositor_layer_action": "Add, remove, group, reorder or remap Compositor Layers (Preview).",
    "fbp.compositor_effect_select_row": "Select this effect in the Compositor Layer (Preview).",
    "fbp.compositor_sync": "Rebuild the Frame By Plane compositor nodes (Preview).",
    "fbp.move_effect_stack_preset": "Move the active Effect Stack preset up or down.",
    "fbp.gradient_light_controller": "Select or create the Empty that moves the Gradient Light. Alt-click unlinks.",

    # Context-sensitive effect and list actions also receive a static fallback
    # for API documentation, search results and disabled-button hover states.
    "fbp.capture_camera_scale_reference": "Store the current camera as the Camera Scale Lock reference.",
    "fbp.select_effect": "Make this the active effect.",
    "fbp.add_effect": "Add this effect to the selected layers.",
    "fbp.effect_header_warning": "Show this effect's warning. Click to fix the order when possible.",
    "fbp.list_action": "Move, duplicate, delete or reverse the checked frames.",
    "fbp.open_effect_masks": "Edit the masks of this effect.",
    "fbp.close_effect_masks": "Back to the Effects Stack.",
    "fbp.add_effect_mask": "Add this mask to the effect on the selected layers.",
    "fbp.open_effect_toolbar_menu": "Open the Effects Stack menu.",
    "fbp.toggle_clipping_mask": "Clip this layer to the alpha of the layer below.",
        # Cutout Plane
    "fbp.import_drawing_plane": "Create a Cutout Plane from the selected images.",
    "fbp.add_drawing_images": "Add images to the Cutout library.",
    "fbp.replace_drawing_image": "Replace the image of the active Cutout drawing.",
    "fbp.drawing_index_step": "Show the previous or next Cutout drawing.",
    "fbp.set_drawing_index": "Show this Cutout drawing.",
    "fbp.remove_drawing": "Remove the selected drawing from the Cutout library.",
    "fbp.move_drawing": "Move the selected Cutout drawing up or down.",

    # Effects stack and presets
    "fbp.set_effect_input_source": "Choose what feeds this effect: previous effect, original or final material.",
    "fbp.set_effect_debug_mode": "Preview a debug output of this effect, such as UV, alpha or mask.",
    "fbp.copy_active_effect": "Copy the active effect and its settings.",
    "fbp.copy_selected_effects": "Copy the checked effects and their settings.",
    "fbp.copy_effect_stack": "Copy the whole effect stack of the active layer.",
    "fbp.paste_effect_stack": "Paste the copied effects onto the selected layers.",
    "fbp.clear_effect_stack": "Remove all effects from the selected layers.",
    "fbp.reset_active_effect": "Reset the active effect to its defaults.",
    "fbp.setup_lattice_camera_flatten": "Create the Lattice cage and correct the layer for the active camera.",
    "fbp.select_lattice_helper": "Select the Lattice cage.",
    "fbp.edit_lattice_helper": "Edit the Lattice cage points.",
    "fbp.finish_lattice_editing": "Leave Lattice editing and reselect the layer.",
    "fbp.update_lattice_flatten": "Recalculate Camera Flatten now.",
    "fbp.bake_lattice_flatten": "Bake Camera Flatten into the cage and stop live updates.",
    "fbp.freeze_lattice_flatten": "Freeze Camera Flatten into editable cage points.",
    "fbp.reset_effect_control": "Reset the viewport helper of this effect.",
    "fbp.repair_effect_controls": "Find and repair broken effect viewport helpers.",
    "fbp.sort_effect_stack": "Restore the recommended effect order.",
    "fbp.apply_effect_preset": "Apply this preset to the active effect.",
    "fbp.save_effect_preset": "Save the active effect settings as a preset. Undo cannot revert it.",
    "fbp.rename_effect_preset": "Rename this preset. Undo cannot revert it.",
    "fbp.delete_effect_preset": "Delete this preset. Undo cannot revert it.",
    "fbp.copy_custom_effect_values_to_selected": "Copy this custom effect's values to the selected layers.",
    "fbp.copy_effect_to_selected": "Copy this effect and its settings to the selected layers.",
    "fbp.duplicate_active_effect": "Copy the active effect to the other selected layers.",
    "fbp.set_effect_viewport": "Show or hide this effect in the viewport.",
    "fbp.drag_effect": "Drag to reorder this effect.",
    "fbp.set_effect_render": "Enable or disable this effect in the render.",
    "fbp.move_active_effect": "Move the checked effects up, down, to the top or to the bottom.",
    "fbp.move_selected_effects_relative": "Move the checked effects before or after another effect.",
    "fbp.set_selected_effects_visibility": "Show, hide or solo the checked effects.",
    "fbp.remove_selected_effects": "Remove the checked effects.",
    "fbp.create_effect_group": "Group the checked effects.",
    "fbp.select_active_effect_group": "Select all effects in the active group.",
    "fbp.ungroup_selected_effects": "Ungroup the checked effects.",
    "fbp.toggle_effect_group_collapse": "Expand or collapse this group.",
    "fbp.toggle_effect_group_selection": "Select or deselect the effects in this group.",
    "fbp.rename_effect_group": "Rename this group.",
    "fbp.effect_group_action": "Select, move, show, hide, solo or ungroup this group.",
    "fbp.effect_group_actions": "Open the Effect Group options.",
    "fbp.remove_effect": "Remove this effect.",
    "fbp.remove_active_effect": "Remove the active effect.",

    # Project setup and import
    "fbp.import_folder_hierarchy": "Scan a folder and add its media to Multiplane Setup.",
    "fbp.add_pending_plane": "Add an empty layer to Multiplane Setup.",
    "fbp.edit_pending_plane": "Choose the media for this layer.",
    "fbp.drag_pending_plane": "Drag to reorder this layer.",
    "fbp.move_pending_plane": "Move the active layer up or down.",
    "fbp.remove_pending_plane": "Remove the active layer from Multiplane Setup.",
    "fbp.clear_pending_planes": "Clear Multiplane Setup.",
    "fbp.scan_project_to_setup": "Fill Multiplane Setup from the Project Folder.",
    "fbp.add_pending_collection": "Add a collection to Multiplane Setup.",
    "fbp.auto_scene_builder": "Build the whole scene from the Project Folder.",
    "fbp.generate_multiplane": "Create the Multiplane scene from the setup.",
    "fbp.import_sequence": "Create a Single Plane from an image, sequence or video.",
    "fbp.replace_sequence": "Replace the media of the active layer, keeping transform and effects.",
    "fbp.rename_sequence_for_blender": "Rename sequence files to a pattern Blender can read. Undo cannot revert it.",
    "fbp.generation_report_popup": "Show the last generation report.",
    "fbp.remove_corrupted_generated_planes": "Delete the broken layers listed in the last report. Undo cannot revert it.",
    "fbp.repair_layer_relation": "Rebuild this Clipping Mask or Layer Blend link.",
    "fbp.repair_all_layer_relations": "Rebuild all Clipping Mask and Layer Blend links in the scene.",
    "fbp.sync_render_output": "Sync the output path with Blender's render settings.",
    "fbp.rename_generation_problem_sequence": "Rename the selected problem sequence.",
    "fbp.clear_generation_report": "Clear the generation report.",
    "fbp.import_single_image": "Create a layer from an image, video or image sequence.",
    "fbp.import_folder_multiplane": "Import a folder as a Multiplane.",
    "fbp.popup_single_plane": "Create a layer from an image, sequence or video.",
    "fbp.popup_video_plane": "Create a layer from a video.",
    "fbp.popup_multiplane": "Import a layered folder as a Multiplane.",
    "fbp.popup_color_plane": "Create a Color, Gradient or Holdout plane.",
    "fbp.popup_gradient_plane": "Create a Gradient plane.",
    "fbp.popup_holdout_plane": "Create a Holdout plane that cuts through the layers behind it.",
    "fbp.create_color_plane_from_hex": "Create a Color Plane from the hex code in the clipboard.",
    "fbp.import_single_image_from_clipboard": "Create a layer from the copied image or file path.",

    # Layers and collections
    "fbp.save_file": "Save the Blender file.",
    "fbp.open_create_rig": "Deselect layers and open the Create section.",
    "fbp.select_linked_plane": "Select the mesh plane of this layer.",
    "fbp.select_collection_planes": "Make the planes in this collection selectable or not.",
    "fbp.add_color_plane_variant": "Duplicate this Color, Gradient or Holdout layer as a new variant.",
    "fbp.ui_list_name_action": "Click to select. Double-click to rename.",
    "fbp.duplicate_or_default": "Duplicate the selection, keeping Frame By Plane layers intact.",
    "fbp.select_layer_exclusive": "Select only this layer.",
    "fbp.select_all_layers": "Select or deselect all layers.",
    "fbp.toggle_lock": "Lock or unlock the selected layer.",
    "fbp.toggle_select_layer": "Add or remove this layer from the selection.",
    "fbp.toggle_solo": "Add or remove this layer from Solo.",
    "fbp.move_layer_stack": "Move the active layer up or down in the stack.",
    "fbp.isolate_layer": "Hide all other layers.",
    "fbp.popup_generate_camera": "Open the camera settings for new projects.",
    "fbp.fit_camera": "Fit the selected layer to the camera frame.",
    "fbp.multi_fit_camera": "Fit all selected layers to the camera frame.",
    "fbp.set_current_frame": "Start the layer's animation at the current frame.",
    "fbp.toggle_collection_collapse": "Expand or collapse this collection.",
    "fbp.toggle_pending_collection_collapse": "Expand or collapse this collection.",
    "fbp.set_pending_collections_open": "Expand or collapse all collections.",
    "fbp.select_collection_layers": "Select or deselect all layers in this collection.",
    "fbp.toggle_collection_visibility": "Show or hide all layers in this collection.",
    "fbp.toggle_collection_lock": "Lock or unlock all layers in this collection.",
    "fbp.delete_collection_layers": "Delete all layers in this collection.",

    # Procedural planes and holdouts
    "fbp.create_color_plane": "Create a Color, Gradient or Holdout plane.",
    "fbp.reset_crop": "Reset the crop of the selected layers.",
    "fbp.crop_alpha": "Crop the selected layers to their visible pixels.",
    "fbp.reset_extend": "Reset the border extension of the selected layers.",
    "fbp.popup_crop": "Crop the selected layers.",
    "fbp.popup_extend": "Extend the borders of the selected layers.",
    "fbp.set_selected_holdout": "Make the selected layers holdouts.",
    "fbp.holdout_all_except_selected": "Make every layer except the selected ones a holdout.",
    "fbp.restore_holdout_materials": "Restore the original materials after a holdout.",
    "fbp.toggle_collection_holdout": "Toggle holdout for all layers in this collection.",
    "fbp.toggle_layer_holdout": "Toggle holdout for this layer.",

    # Project maintenance and rendering
    "fbp.remove_pending_tree_selection": "Remove the selected layer or collection from Multiplane Setup.",
    "fbp.remove_pending_plane_at_index": "Remove this layer from Multiplane Setup.",
    "fbp.project_health_check": "Check the project for missing media and broken layers.",
    "fbp.relink_from_project_root": "Find missing files in the Project Folder and relink them.",
    "fbp.select_missing_layers": "Select the layers with missing media.",
    "fbp.sync_collection_colors": "Color the layers with their collection color.",
    "fbp.apply_preferences_to_scene": "Apply the add-on defaults to this scene.",
    "fbp.repair_render_state": "Check and fix the layers before rendering.",
    "fbp.background_render_frames": "Render the frame range in the background.",
    "fbp.stop_background_render": "Stop the background render.",
    "fbp.background_render_status": "Show the background render progress.",

    # Sequence and timing
    "fbp.update_animation": "Rebuild the timing of the selected layers.",
    "fbp.refresh_media": "Reload the active layer's media from disk.",
    "fbp.refresh_all_media": "Reload all media from disk.",
    "fbp.transform": "Stand the selected layers up or lay them flat.",
    "fbp.popup_transform": "Open the transform tools.",
    "fbp.update_emission": "Apply the Emission/Shadeless setting to the selected layers.",
    "fbp.update_opacity": "Apply the opacity to the selected layers.",
    "fbp.update_track": "Make the selected layers face the camera, or stop it.",
    "fbp.select_image_exclusive": "Make this frame active and jump to it.",
    "fbp.convert_color_plane_to_animation": "Turn this Color or Gradient plane into an animation.",
    "fbp.insert_images_after_selected": "Insert images after the active frame.",
    "fbp.insert_linked_image_after_selected": "Insert a linked image after the active frame.",
    "fbp.insert_transparent_frame": "Insert a transparent frame after the active frame.",
    "fbp.link_image_frame": "Choose new media for this frame.",
    "fbp.select_all": "Select, deselect or invert all frames.",
    "fbp.reverse_sequence": "Reverse the frame order.",
    "fbp.optimize_sequence_frames": "Merge identical frames into holds and replace empty frames.",
    "fbp.reverse_pending_sequence": "Reverse this sequence.",
    "fbp.popup_sequence_settings": "Open the timing and playback settings.",
    "fbp.duplicate_selected_layers": "Duplicate the selected layers.",
    "fbp.merge_selected_to_active_sequence": "Merge the selected layers into the active one as a sequence.",
    "fbp.split_selected_images_to_new_plane": "Move the checked frames to a new layer.",
    "fbp.split_sequence_to_planes": "Split every frame into its own layer.",
    "fbp.delete_sequence": "Delete the selected layers.",
    "fbp.delete_or_default": "Delete the selection, including Frame By Plane layer data.",

    # Custom effects
    "fbp.create_custom_node_effect": "Create a new custom node effect.",
    "fbp.edit_custom_node_effect_nodes": "Open this custom effect in the node editor.",
    "fbp.register_custom_node_effect": "Turn an existing node group into a custom effect.",
    "fbp.hide_custom_node_effect": "Hide this custom effect from the Add Effect menu.",

    # Grease Pencil workflow refinements
    "fbp.select_grease_pencil_canvas": "Select the Grease Pencil drawing of this layer.",
    "fbp.restore_grease_pencil_reference_opacity": "Restore the reference opacity of the image layer.",

    # Other actions across the add-on.
    "fbp.compositor_toggle": "Turn the Frame By Plane compositor on or off. Off restores your own setup.",
    "fbp.render_checked": "Render the image or animation, asking first if the compositor needs a Refresh.",
    "fbp.compositor_repair_rebuild": "Rebuild the Frame By Plane compositor nodes, keeping your own nodes.",
    "fbp.sync_compositor_layer_node_prototype": "Sync the Layers node, its outputs and View Layers.",
    "fbp.audit_compositor_layer_node_prototype": "Check the Layers node without rebuilding it.",
    "fbp.repair_composite_safe": "Repair the composite without replacing your own links.",
    "fbp.apply_image_effects": "Bake the image effects into new images, so they show in Solid view too.",
    "fbp.whats_new_gpu_popup": "Show what's new in this version.",
    "fbp.test_whats_new_cover": "Check that the What's New images load.",
    "fbp.open_whats_new_page": "Open the release notes on Blender Extensions.",
    "fbp.open_review_page": "Leave a review on Blender Extensions.",
    "fbp.open_support_page": "Report an issue on GitHub. Nothing is sent automatically.",
    "fbp.open_effect_nodes": "Open this effect's node tree for this layer.",
    "fbp.set_effect_family_variant": "Switch this effect to another variant of the same family.",
    "fbp.repair_generic_mesh_duplicates": "Remove duplicate Generic Mesh effects, keeping the first one.",
    "fbp.fit_shadow_canvas": "Extend the plane just enough to fit the outer shadow.",
    "fbp.toggle_effect_solo": "Show only this effect in the viewport. Click again to restore the stack.",
    "fbp.rebuild_lattice_helper": "Recreate a clean Lattice cage for this layer.",
    "fbp.set_lattice_perspective_grid": "Set the cage grid size. Changing it resets point edits.",
    "fbp.add_lattice_pose": "Add a deformation slider that can be mixed and keyframed.",
    "fbp.refit_lattice_helper": "Refit the Lattice cage to the plane, keeping point edits.",
    "fbp.add_grease_pencil_canvas": "Create a Grease Pencil drawing, linked to a layer or free.",
    "fbp.bake_grease_pencil_mask": "Pack the Grease Pencil mask image into the .blend file.",
    "fbp.use_grease_pencil_as_mask": "Use the linked Grease Pencil drawing as a mask.",
    "fbp.add_grease_pencil_mask": "Create a Grease Pencil layer and use it as a mask.",
    "fbp.split_gp_single_layer": "Move this Grease Pencil layer into its own object.",
    "fbp.collapse_gp_canvases_to_one": "Join the selected Grease Pencil drawings into one object.",
    "fbp.delete_grease_pencil_canvas": "Delete the selected Grease Pencil drawing. The layer stays.",
    "fbp.toggle_gp_canvas_clipping": "Clipping between Grease Pencil and planes is not available yet.",
    "fbp.add_scrub_bookmark": "Add a named bookmark at the current frame.",
    "fbp.grease_pencil_scrub_preview": "Preview the Scrub Bar while editing its preferences.",
    "fbp.timeline_hold_scrub": "Hold and move to scrub. Shift slows down, Esc cancels.",
    "fbp.motion_remove": "Remove the active Motion.",
    "fbp.motion_create_follow_helper": "Create the helper needed by this Follow preset.",
    "fbp.toggle_pending_sequence_collection": "Turn this sequence into still layers, or merge them back.",
    "fbp.reverse_pending_selected_order": "Reverse the order of the checked layers.",
    "fbp.import_toon_boom_export": "Import a Toon Boom Harmony image export as a Multiplane.",
    "fbp.layered_import_report": "Show what was imported, flattened or skipped from the layered file.",
    "fbp.import_psd": "Import Photoshop layers as a Multiplane.",
    "fbp.import_procreate": "Import Procreate layers as a Multiplane.",
    "fbp.set_layer_blend_mode": "Apply this blend mode to the selected layers.",
    "fbp.perfect_object_mask_shape": "Restore a perfect square, circle or triangle.",
    "fbp.edit_object_mask_helper": "Edit the Shape Mask vertices.",
    "fbp.group_or_pass": "Group the selected layers into a collection.",
    "fbp.ungroup_or_pass": "Move the selected layers out of their collection.",
    "fbp.move_layer_collection": "Move the active collection in or out of the one above.",
    "fbp.drag_layer_collection": "Drag up or down to reorder, right to nest, left to move out.",
    "fbp.create_layer_collection": "Create a new collection.",
    "fbp.ungroup_selected_layers": "Move the selected layers out of their collection.",
    "fbp.drag_layer_tree": "Drag to move the layer in the list.",
    "fbp.reverse_selected_layer_order": "Reverse the order of the selected layers.",
    "fbp.delete_layer_collection": "Remove this collection, keeping its layers.",
    "fbp.copy_preview_diagnostics": "Copy the Preview features info to the clipboard.",
    "fbp.finalize_render_state_background": "Restore the render settings after a background render.",
    "fbp.profile_120_frames": "Measure performance over 120 frames.",
    "fbp.run_persistence_audit": "Check that layers and effects survive save and reopen.",
    "fbp.select_project_health_issue": "Select the next object with a Project Doctor issue.",
}


MENU_TOOLTIPS = {
    "FBP_MT_add_effect": "Add an Image effect or Mask to the selected layers. Mesh effects are in Modifiers > Add Modifier > Mesh.",
    "FBP_MT_effect_presets": "Apply, save, rename or delete presets for the active effect.",
    "FBP_MT_effect_stack_actions": "Copy, paste, reset, sort or clear the effect stack.",
    "FBP_MT_object_effects": "Open the Image and Mask effect libraries.",
    "FBP_MT_object_masks": "Add a mask to the selected layer.",
    "FBP_MT_object_effects_2d": "Add an image effect to the selected layers.",
    "FBP_MT_object_effects_3d": "Add a mesh effect to the selected layers.",
    "FBP_MT_frame_by_plane_add": "Create Frame By Plane layers.",
    "FBP_MT_frame_by_plane_more": "More import options: folders, PSD/PSB, Toon Boom.",
    "FBP_MT_layer_blend_dropdown": "Choose the layer blend mode.",
    "FBP_MT_object_holdout": "Holdout tools for the selected layers.",
}


def _short_description(text: str) -> str:
    """Return one tidy hover line, keeping the text the translations look up."""
    return " ".join(str(text or "").split())


def _operator_description(cls, operator_id: str) -> str:
    exact = EXACT_TOOLTIPS.get(operator_id)
    if exact:
        return _short_description(exact)
    current = str(getattr(cls, "bl_description", "") or "").strip()
    if not current:
        current = str(getattr(cls, "bl_label", operator_id) or operator_id)
    return _short_description(current)


def apply_tooltips(modules) -> None:
    """Apply reviewed hover descriptions before Blender class registration."""
    seen = set()
    for module in modules:
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

            if bl_idname.startswith("FBP_PT_"):
                label = str(getattr(cls, "bl_label", "Frame By Plane") or "Frame By Plane")
                cls.bl_description = f"{label} panel."
                continue

            if not bl_idname.startswith("fbp."):
                continue
            # A custom classmethod description is already context-sensitive;
            # keep it and only provide a static fallback for API inspection.
            cls.bl_description = _operator_description(cls, bl_idname)
