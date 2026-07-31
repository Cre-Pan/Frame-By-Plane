"""Registration facade for Frame By Plane operators.

The implementation is split by responsibility; this module preserves the
public import path and a deterministic registration order.
"""

import bpy

from .registration import register_classes, unregister_classes
from .shortcut_runtime import (
    addon_keymap,
    refresh_keymap_registration,
    primary_modifier_kwargs,
    remove_matching_keymap_items,
    shortcut_enabled,
    unregister_keymap_items,
)
from .operator_common import (
    _fbp_bg_clear_runtime_state,
    _fbp_bg_process_running,
    _fbp_bg_terminate_process,
    _fbp_hide_generation_overlay,
    fbp_warn,
)
from .operator_layers import (
    FBP_OT_SaveFile,
    FBP_OT_LinkCircleMaskNull,
    FBP_OT_PerfectObjectMaskShape,
    FBP_OT_RecreateObjectMaskHelper,
    FBP_OT_EditObjectMaskHelper,
    FBP_OT_ToggleClippingMask,
    FBP_OT_SelectLayerRelationSource,
    FBP_OT_RepairLayerRelation,
    FBP_OT_RepairAllLayerRelations,
    FBP_OT_SetLayerBlendMode,
    FBP_OT_ShowLayerBlendMenu,
    FBP_OT_OpenCreateRig,
    FBP_OT_SelectLinkedPlane,
    FBP_OT_SelectCollectionPlanes,
    FBP_OT_AddColorPlaneVariant,
    FBP_OT_UIListNameAction,
    FBP_OT_SelectLayerExclusive,
    FBP_OT_DuplicateOrDefault,
    FBP_OT_GroupOrPass,
    FBP_OT_UngroupOrPass,
    FBP_OT_SelectAllLayers,
    FBP_OT_ToggleLock,
    FBP_OT_ToggleSelectLayer,
    FBP_OT_ToggleSolo,
    FBP_OT_CreateLayerCollection,
    FBP_OT_MoveLayerCollection,
    FBP_OT_MoveLayerCollectionTo,
    FBP_OT_DragLayerCollection,
    FBP_OT_UngroupSelectedLayers,
    FBP_OT_DragLayerTree,
    FBP_OT_MoveLayerStack,
    FBP_OT_ReverseSelectedLayerOrder,
    FBP_OT_IsolateLayer,
    FBP_OT_FitToCamera,
    FBP_OT_MultiFitCamera,
    FBP_OT_PopupGenerateCamera,
    FBP_OT_SetCurrentFrame,
    FBP_OT_ToggleCollectionCollapse,
    FBP_OT_TogglePendingCollectionCollapse,
    FBP_OT_SetPendingCollectionsOpen,
    FBP_OT_SelectCollectionLayers,
    FBP_OT_ToggleCollectionState,
    FBP_OT_ToggleCollectionVisibility,
    FBP_OT_ToggleCollectionLock,
    FBP_OT_DeleteLayerCollection,
    FBP_OT_DeleteCollectionLayers,
)
from .operator_import import (
    FBP_OT_ImportFolderHierarchy,
    FBP_OT_AddPendingPlane,
    FBP_OT_EditPendingPlane,
    FBP_OT_DragPendingPlane,
    FBP_OT_MovePendingPlane,
    FBP_OT_RemovePendingPlane,
    FBP_OT_ClearPendingPlanes,
    FBP_OT_TogglePendingSequenceCollection,
    FBP_OT_ReversePendingSelectedOrder,
    FBP_OT_ReversePendingSequence,
    FBP_OT_ScanProjectToSetup,
    FBP_OT_AddPendingCollection,
    FBP_OT_AutoSceneBuilder,
    FBP_OT_GenerateMultiplane,
    FBP_OT_ImportSequence,
    FBP_OT_ReplaceSequence,
    FBP_OT_RenameSequenceForBlender,
    FBP_UL_GenerationRenameList,
    FBP_OT_SelectGenerationRenameRow,
    FBP_OT_GenerationReportPopup,
    FBP_OT_RemoveCorruptedGeneratedPlanes,
    FBP_OT_RenameGenerationProblemSequence,
    FBP_OT_ClearGenerationReport,
    FBP_OT_ImportSingleImage,
    FBP_OT_ImportFolderMultiplane,
    FBP_OT_ImportToonBoomExport,
    FBP_OT_LayeredImportReport,
    FBP_OT_ImportPSD,
    FBP_OT_ImportProcreate,
    FBP_FH_ProcreateDrop,
    FBP_FH_LayeredDrop,
    FBP_OT_DropMedia,
    FBP_FH_MediaDrop,
    FBP_OT_PopupSinglePlane,
    FBP_OT_PopupVideoPlane,
    FBP_OT_PopupMultiplane,
    FBP_OT_PopupColorPlane,
    FBP_OT_CreateColorPlaneFromHex,
    FBP_OT_ImportSingleImageFromClipboard,
)
from .operator_sequence import (
    FBP_OT_UpdateAnimation,
    FBP_OT_RefreshMedia,
    FBP_OT_RefreshAllMedia,
    FBP_OT_SetColorPlaneMode,
    FBP_OT_GradientController,
    FBP_OT_Transform,
    FBP_OT_PopupTransform,
    FBP_OT_UpdateEmission,
    FBP_OT_UpdateOpacity,
    FBP_OT_UpdateTrack,
    FBP_OT_SelectImageExclusive,
    FBP_OT_DragSequenceFrame,
    FBP_OT_InsertImagesAfterSelected,
    FBP_OT_ConvertColorPlaneToAnimation,
    FBP_OT_InsertLinkedImageAfterSelected,
    FBP_OT_InsertTransparentFrame,
    FBP_OT_LinkImageFrame,
    FBP_OT_SelectAll,
    FBP_OT_ListAction,
    FBP_OT_ReverseSequence,
    FBP_OT_OptimizeSequenceFrames,
    FBP_OT_PopupSequenceSettings,
    FBP_OT_DuplicateSelectedLayers,
    FBP_OT_MergeSelectedToActiveSequence,
    FBP_OT_SplitSelectedImagesToNewPlane,
    FBP_OT_DeleteSequence,
    FBP_OT_DeleteOrDefault,
)
from .operator_render import (
    FBP_OT_RepairRenderState,
    FBP_OT_SyncRenderOutput,
    FBP_OT_OpenRenderOutputFolder,
    FBP_OT_NextRenderTestFolder,
    FBP_OT_BackgroundRenderFrames,
    FBP_OT_StopBackgroundRender,
    FBP_OT_BackgroundRenderStatus,
)
from .operator_procedural import (
    FBP_OT_CreateColorPlane,
    FBP_OT_ResetCrop,
    FBP_OT_ResetExtend,
    FBP_OT_FocusCropExtend,
    FBP_OT_PopupCrop,
    FBP_OT_PopupExtend,
    FBP_OT_SetSelectedHoldout,
    FBP_OT_HoldoutAllExceptSelected,
    FBP_OT_RestoreHoldoutMaterials,
    FBP_OT_ToggleCollectionHoldout,
    FBP_OT_ToggleLayerHoldout,
)
from .operator_project import (
    FBP_OT_RemovePendingTreeSelection,
    FBP_OT_RemovePendingPlaneAtIndex,
    FBP_OT_ProjectHealthCheck,
    FBP_OT_OpenLastDiagnosticReport,
    FBP_OT_CopyLastDiagnosticReport,
    FBP_OT_OpenDiagnosticReport,
    FBP_OT_CopyDiagnosticMessages,
    FBP_OT_ExportProjectDoctorReport,
    FBP_OT_RelinkFromProjectRoot,
    FBP_OT_SelectMissingLayers,
    FBP_OT_SyncCollectionColors,
    FBP_OT_ApplyPreferencesToScene,
)
from .persistence import FBP_OT_RunPersistenceAudit


_addon_keymaps = []


def _register_keymaps():
    """Register optional Object Mode shortcuts without duplicating stale entries."""
    _unregister_keymaps()
    keymap = addon_keymap(
        'Object Mode',
        fallback_space_type='VIEW_3D',
        fallback_region_type='WINDOW',
    )
    if keymap is None:
        return

    owned_ids = {
        'fbp.duplicate_or_default',
        'fbp.create_layer_collection',
        'fbp.ungroup_selected_layers',
        'fbp.group_or_pass',
        'fbp.ungroup_or_pass',
    }
    remove_matching_keymap_items(
        keymap,
        lambda item: str(getattr(item, 'idname', '') or '') in owned_ids,
    )

    if shortcut_enabled('shortcut_duplicate_layer'):
        item = keymap.keymap_items.new(
            'fbp.duplicate_or_default',
            type='D',
            value='PRESS',
            shift=True,
        )
        _addon_keymaps.append((keymap, item))

    if shortcut_enabled('shortcut_group_layers'):
        group_item = keymap.keymap_items.new(
            'fbp.group_or_pass',
            type='G',
            value='PRESS',
            **primary_modifier_kwargs(),
        )
        _addon_keymaps.append((keymap, group_item))

        ungroup_item = keymap.keymap_items.new(
            'fbp.ungroup_or_pass',
            type='G',
            value='PRESS',
            **primary_modifier_kwargs(shift=True),
        )
        _addon_keymaps.append((keymap, ungroup_item))


def _unregister_keymaps():
    unregister_keymap_items(_addon_keymaps)


def refresh_keymaps():
    """Public hook used by Add-on Preferences after a shortcut toggle changes."""
    return refresh_keymap_registration(_register_keymaps)


classes = (
    FBP_OT_LinkCircleMaskNull,
    FBP_OT_PerfectObjectMaskShape,
    FBP_OT_RecreateObjectMaskHelper,
    FBP_OT_EditObjectMaskHelper,
    FBP_OT_ToggleClippingMask,
    FBP_OT_SelectLayerRelationSource,
    FBP_OT_RepairLayerRelation,
    FBP_OT_RepairAllLayerRelations,
    FBP_OT_SetLayerBlendMode,
    FBP_OT_ShowLayerBlendMenu,
    FBP_OT_SaveFile,
    FBP_OT_OpenCreateRig,
    FBP_OT_SelectLinkedPlane,
    FBP_OT_SelectCollectionPlanes,
    FBP_OT_AddColorPlaneVariant,
    FBP_OT_UIListNameAction,
    FBP_OT_SelectLayerExclusive,
    FBP_OT_DuplicateOrDefault,
    FBP_OT_GroupOrPass,
    FBP_OT_UngroupOrPass,
    FBP_OT_SelectAllLayers,
    FBP_OT_ToggleLock,
    FBP_OT_ToggleSelectLayer,
    FBP_OT_ToggleSolo,
    FBP_OT_CreateLayerCollection,
    FBP_OT_MoveLayerCollection,
    FBP_OT_MoveLayerCollectionTo,
    FBP_OT_DragLayerCollection,
    FBP_OT_UngroupSelectedLayers,
    FBP_OT_DragLayerTree,
    FBP_OT_MoveLayerStack,
    FBP_OT_ReverseSelectedLayerOrder,
    FBP_OT_IsolateLayer,
    FBP_OT_FitToCamera,
    FBP_OT_MultiFitCamera,
    FBP_OT_PopupGenerateCamera,
    FBP_OT_SetCurrentFrame,
    FBP_OT_ImportFolderHierarchy,
    FBP_OT_AddPendingPlane,
    FBP_OT_EditPendingPlane,
    FBP_OT_DragPendingPlane,
    FBP_OT_MovePendingPlane,
    FBP_OT_RemovePendingPlane,
    FBP_OT_ClearPendingPlanes,
    FBP_OT_TogglePendingSequenceCollection,
    FBP_OT_ReversePendingSelectedOrder,
    FBP_OT_ReversePendingSequence,
    FBP_OT_ScanProjectToSetup,
    FBP_OT_AddPendingCollection,
    FBP_OT_AutoSceneBuilder,
    FBP_OT_GenerateMultiplane,
    FBP_OT_ImportSequence,
    FBP_OT_ReplaceSequence,
    FBP_OT_RenameSequenceForBlender,
    FBP_UL_GenerationRenameList,
    FBP_OT_SelectGenerationRenameRow,
    FBP_OT_GenerationReportPopup,
    FBP_OT_RemoveCorruptedGeneratedPlanes,
    FBP_OT_RenameGenerationProblemSequence,
    FBP_OT_ClearGenerationReport,
    FBP_OT_UpdateAnimation,
    FBP_OT_RefreshMedia,
    FBP_OT_RefreshAllMedia,
    FBP_OT_SetColorPlaneMode,
    FBP_OT_GradientController,
    FBP_OT_Transform,
    FBP_OT_PopupTransform,
    FBP_OT_UpdateEmission,
    FBP_OT_UpdateOpacity,
    FBP_OT_UpdateTrack,
    FBP_OT_SelectImageExclusive,
    FBP_OT_DragSequenceFrame,
    FBP_OT_InsertImagesAfterSelected,
    FBP_OT_ConvertColorPlaneToAnimation,
    FBP_OT_InsertLinkedImageAfterSelected,
    FBP_OT_InsertTransparentFrame,
    FBP_OT_LinkImageFrame,
    FBP_OT_SelectAll,
    FBP_OT_ListAction,
    FBP_OT_ReverseSequence,
    FBP_OT_OptimizeSequenceFrames,
    FBP_OT_PopupSequenceSettings,
    FBP_OT_DuplicateSelectedLayers,
    FBP_OT_MergeSelectedToActiveSequence,
    FBP_OT_SplitSelectedImagesToNewPlane,
    FBP_OT_DeleteSequence,
    FBP_OT_DeleteOrDefault,
    FBP_OT_ToggleCollectionCollapse,
    FBP_OT_TogglePendingCollectionCollapse,
    FBP_OT_SetPendingCollectionsOpen,
    FBP_OT_SelectCollectionLayers,
    FBP_OT_ToggleCollectionState,
    FBP_OT_ToggleCollectionVisibility,
    FBP_OT_ToggleCollectionLock,
    FBP_OT_DeleteLayerCollection,
    FBP_OT_DeleteCollectionLayers,
    FBP_OT_RepairRenderState,
    FBP_OT_SyncRenderOutput,
    FBP_OT_OpenRenderOutputFolder,
    FBP_OT_NextRenderTestFolder,
    FBP_OT_BackgroundRenderFrames,
    FBP_OT_StopBackgroundRender,
    FBP_OT_BackgroundRenderStatus,
    FBP_OT_CreateColorPlane,
    FBP_OT_ResetCrop,
    FBP_OT_ResetExtend,
    FBP_OT_FocusCropExtend,
    FBP_OT_PopupCrop,
    FBP_OT_PopupExtend,
    FBP_OT_SetSelectedHoldout,
    FBP_OT_HoldoutAllExceptSelected,
    FBP_OT_RestoreHoldoutMaterials,
    FBP_OT_ToggleCollectionHoldout,
    FBP_OT_ToggleLayerHoldout,
    FBP_OT_RemovePendingTreeSelection,
    FBP_OT_RemovePendingPlaneAtIndex,
    FBP_OT_ProjectHealthCheck,
    FBP_OT_RunPersistenceAudit,
    FBP_OT_OpenLastDiagnosticReport,
    FBP_OT_CopyLastDiagnosticReport,
    FBP_OT_OpenDiagnosticReport,
    FBP_OT_CopyDiagnosticMessages,
    FBP_OT_ExportProjectDoctorReport,
    FBP_OT_RelinkFromProjectRoot,
    FBP_OT_SelectMissingLayers,
    FBP_OT_SyncCollectionColors,
    FBP_OT_ApplyPreferencesToScene,
    FBP_OT_ImportSingleImage,
    FBP_OT_ImportFolderMultiplane,
    FBP_OT_ImportToonBoomExport,
    FBP_OT_LayeredImportReport,
    FBP_OT_ImportPSD,
    FBP_OT_ImportProcreate,
    FBP_FH_ProcreateDrop,
    FBP_FH_LayeredDrop,
    FBP_OT_DropMedia,
    FBP_FH_MediaDrop,
    FBP_OT_PopupSinglePlane,
    FBP_OT_PopupVideoPlane,
    FBP_OT_PopupMultiplane,
    FBP_OT_PopupColorPlane,
    FBP_OT_CreateColorPlaneFromHex,
    FBP_OT_ImportSingleImageFromClipboard,
)



_registered_operator_classes = globals().get("_registered_operator_classes", [])
if not isinstance(_registered_operator_classes, list):
    _registered_operator_classes = []


def register():
    _registered_operator_classes.clear()
    is_background = bool(getattr(bpy.app, "background", False))
    # Background processes use a deliberately small, headless-safe surface.
    # The render child remains isolated further upstream
    # because __init__.py skips operator_project for FBP_BACKGROUND_RENDER_CHILD.
    background_classes = (
        FBP_OT_RepairRenderState,
        FBP_OT_ProjectHealthCheck,
        FBP_OT_RunPersistenceAudit,
        )
    target_classes = background_classes if is_background else classes
    _registered_operator_classes.extend(register_classes(target_classes))
    if not is_background:
        try:
            _register_keymaps()
        except Exception as exc:
            fbp_warn("Could not register Frame By Plane keymaps", exc)
        try:
            _fbp_hide_generation_overlay()
            if _fbp_bg_process_running():
                _fbp_bg_terminate_process(getattr(bpy.context, 'scene', None))
            _fbp_bg_clear_runtime_state(getattr(bpy.context, 'scene', None))
        except Exception as exc:
            fbp_warn("Could not initialize background-render runtime state", exc)


def unregister():
    is_background = bool(getattr(bpy.app, "background", False))
    if not is_background:
        _unregister_keymaps()
        _fbp_hide_generation_overlay()
        try:
            if _fbp_bg_process_running():
                _fbp_bg_terminate_process(getattr(bpy.context, 'scene', None))
            _fbp_bg_clear_runtime_state(getattr(bpy.context, 'scene', None))
        except Exception as exc:
            fbp_warn("Could not clear background-render runtime state", exc)
    unregister_classes(tuple(_registered_operator_classes))
    _registered_operator_classes.clear()
