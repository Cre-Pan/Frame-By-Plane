"""Registration facade for Frame by Plane operators.

The implementation is split by responsibility; this module preserves the
public import path and a deterministic registration order.
"""

import bpy

from .operator_common import (
    _fbp_bg_clear_runtime_state,
    _fbp_bg_process_running,
    _fbp_bg_terminate_process,
    _fbp_hide_generation_overlay,
    fbp_warn,
)
from .operator_layers import (
    FBP_OT_SaveFile,
    FBP_OT_OpenCreateRig,
    FBP_OT_SelectLinkedPlane,
    FBP_OT_SelectCollectionPlanes,
    FBP_OT_AddColorPlaneVariant,
    FBP_OT_UIListNameAction,
    FBP_OT_SelectLayerExclusive,
    FBP_OT_DuplicateOrDefault,
    FBP_OT_SelectAllLayers,
    FBP_OT_ToggleLock,
    FBP_OT_ToggleSelectLayer,
    FBP_OT_ToggleSolo,
    FBP_OT_MoveLayerStack,
    FBP_OT_IsolateLayer,
    FBP_OT_FitToCamera,
    FBP_OT_MultiFitCamera,
    FBP_OT_PopupGenerateCamera,
    FBP_OT_SetCurrentFrame,
    FBP_OT_ToggleCollectionCollapse,
    FBP_OT_TogglePendingCollectionCollapse,
    FBP_OT_SetPendingCollectionsOpen,
    FBP_OT_SelectCollectionLayers,
    FBP_OT_ToggleCollectionVisibility,
    FBP_OT_ToggleCollectionLock,
    FBP_OT_DeleteCollectionLayers,
)
from .operator_import import (
    FBP_OT_ImportFolderHierarchy,
    FBP_OT_AddPendingPlane,
    FBP_OT_EditPendingPlane,
    FBP_OT_MovePendingPlane,
    FBP_OT_RemovePendingPlane,
    FBP_OT_ClearPendingPlanes,
    FBP_OT_ScanProjectToSetup,
    FBP_OT_AddPendingCollection,
    FBP_OT_AutoSceneBuilder,
    FBP_OT_GenerateMultiplane,
    FBP_OT_ImportSequence,
    FBP_OT_ReplaceSequence,
    FBP_OT_RenameSequenceForBlender,
    FBP_UL_GenerationRenameList,
    FBP_OT_GenerationReportPopup,
    FBP_OT_RemoveCorruptedGeneratedPlanes,
    FBP_OT_RenameGenerationProblemSequence,
    FBP_OT_ClearGenerationReport,
    FBP_OT_ImportSingleImage,
    FBP_OT_ImportFolderMultiplane,
    FBP_OT_PopupSinglePlane,
    FBP_OT_PopupSinglePlaneAnimation,
    FBP_OT_PopupMultiplane,
    FBP_OT_PopupColorPlane,
    FBP_OT_CreateColorPlaneFromHex,
    FBP_OT_ImportSingleImageFromClipboard,
)
from .operator_sequence import (
    FBP_OT_UpdateAnimation,
    FBP_OT_Transform,
    FBP_OT_PopupTransform,
    FBP_OT_UpdateEmission,
    FBP_OT_UpdateOpacity,
    FBP_OT_UpdateTrack,
    FBP_OT_SelectImageExclusive,
    FBP_OT_InsertImagesAfterSelected,
    FBP_OT_InsertLinkedImageAfterSelected,
    FBP_OT_InsertTransparentFrame,
    FBP_OT_LinkImageFrame,
    FBP_OT_SelectAll,
    FBP_OT_ListAction,
    FBP_OT_ReverseSequence,
    FBP_OT_PopupSequenceSettings,
    FBP_OT_DuplicateSelectedLayers,
    FBP_OT_MergeSelectedToActiveSequence,
    FBP_OT_SplitSelectedImagesToNewPlane,
    FBP_OT_DeleteSequence,
    FBP_OT_DeleteOrDefault,
)
from .operator_render import (
    FBP_OT_RepairRenderState,
    FBP_OT_BackgroundRenderFrames,
    FBP_OT_StopBackgroundRender,
    FBP_OT_BackgroundRenderStatus,
)
from .operator_procedural import (
    FBP_OT_CreateColorPlane,
    FBP_OT_ResetCrop,
    FBP_OT_ResetExtend,
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
    FBP_OT_DeepAddonAudit,
    FBP_OT_RelinkFromProjectRoot,
    FBP_OT_SelectMissingLayers,
    FBP_OT_SyncCollectionColors,
    FBP_OT_ApplyPreferencesToScene,
    FBP_OT_ProfileEffects,
    FBP_OT_CreateEffectRegressionScene,
)


_addon_keymaps = []


def _register_keymaps():
    """Route Object Mode Shift+D through the FBP-aware duplicate operator.

    Every current FBP layer type uses the same rig/linked-plane contract, so the
    explicit operator can duplicate Image, Sequence, Color, Gradient and Holdout
    layers consistently. Non-FBP selections fall back to Blender's native
    duplicate-and-move operator.
    """
    wm = getattr(bpy.context, "window_manager", None)
    keyconfig = getattr(getattr(wm, "keyconfigs", None), "addon", None)
    if not keyconfig:
        return

    km = keyconfig.keymaps.new(name='Object Mode', space_type='EMPTY')

    # Defensive cleanup for development reloads that did not get a clean
    # unregister. Only remove entries owned by this add-on operator.
    for item in list(km.keymap_items):
        try:
            if item.idname == 'fbp.duplicate_or_default':
                km.keymap_items.remove(item)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue

    kmi = km.keymap_items.new(
        'fbp.duplicate_or_default',
        type='D',
        value='PRESS',
        shift=True,
    )
    _addon_keymaps.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in reversed(_addon_keymaps):
        try:
            km.keymap_items.remove(kmi)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _addon_keymaps.clear()


classes = (
    FBP_OT_SaveFile,
    FBP_OT_OpenCreateRig,
    FBP_OT_SelectLinkedPlane,
    FBP_OT_SelectCollectionPlanes,
    FBP_OT_AddColorPlaneVariant,
    FBP_OT_UIListNameAction,
    FBP_OT_SelectLayerExclusive,
    FBP_OT_DuplicateOrDefault,
    FBP_OT_SelectAllLayers,
    FBP_OT_ToggleLock,
    FBP_OT_ToggleSelectLayer,
    FBP_OT_ToggleSolo,
    FBP_OT_MoveLayerStack,
    FBP_OT_IsolateLayer,
    FBP_OT_FitToCamera,
    FBP_OT_MultiFitCamera,
    FBP_OT_PopupGenerateCamera,
    FBP_OT_SetCurrentFrame,
    FBP_OT_ImportFolderHierarchy,
    FBP_OT_AddPendingPlane,
    FBP_OT_EditPendingPlane,
    FBP_OT_MovePendingPlane,
    FBP_OT_RemovePendingPlane,
    FBP_OT_ClearPendingPlanes,
    FBP_OT_ScanProjectToSetup,
    FBP_OT_AddPendingCollection,
    FBP_OT_AutoSceneBuilder,
    FBP_OT_GenerateMultiplane,
    FBP_OT_ImportSequence,
    FBP_OT_ReplaceSequence,
    FBP_OT_RenameSequenceForBlender,
    FBP_UL_GenerationRenameList,
    FBP_OT_GenerationReportPopup,
    FBP_OT_RemoveCorruptedGeneratedPlanes,
    FBP_OT_RenameGenerationProblemSequence,
    FBP_OT_ClearGenerationReport,
    FBP_OT_UpdateAnimation,
    FBP_OT_Transform,
    FBP_OT_PopupTransform,
    FBP_OT_UpdateEmission,
    FBP_OT_UpdateOpacity,
    FBP_OT_UpdateTrack,
    FBP_OT_SelectImageExclusive,
    FBP_OT_InsertImagesAfterSelected,
    FBP_OT_InsertLinkedImageAfterSelected,
    FBP_OT_InsertTransparentFrame,
    FBP_OT_LinkImageFrame,
    FBP_OT_SelectAll,
    FBP_OT_ListAction,
    FBP_OT_ReverseSequence,
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
    FBP_OT_ToggleCollectionVisibility,
    FBP_OT_ToggleCollectionLock,
    FBP_OT_DeleteCollectionLayers,
    FBP_OT_RepairRenderState,
    FBP_OT_BackgroundRenderFrames,
    FBP_OT_StopBackgroundRender,
    FBP_OT_BackgroundRenderStatus,
    FBP_OT_CreateColorPlane,
    FBP_OT_ResetCrop,
    FBP_OT_ResetExtend,
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
    FBP_OT_DeepAddonAudit,
    FBP_OT_RelinkFromProjectRoot,
    FBP_OT_SelectMissingLayers,
    FBP_OT_SyncCollectionColors,
    FBP_OT_ApplyPreferencesToScene,
    FBP_OT_ProfileEffects,
    FBP_OT_CreateEffectRegressionScene,
    FBP_OT_ImportSingleImage,
    FBP_OT_ImportFolderMultiplane,
    FBP_OT_PopupSinglePlane,
    FBP_OT_PopupSinglePlaneAnimation,
    FBP_OT_PopupMultiplane,
    FBP_OT_PopupColorPlane,
    FBP_OT_CreateColorPlaneFromHex,
    FBP_OT_ImportSingleImageFromClipboard,
)


def register():
    registered = []
    try:
        for cls in classes:
            bpy.utils.register_class(cls)
            registered.append(cls)
    except Exception:
        for cls in reversed(registered):
            try:
                bpy.utils.unregister_class(cls)
            except Exception as rollback_exc:
                fbp_warn(f"Could not roll back operator {cls.__name__}", rollback_exc)
        raise
    try:
        _register_keymaps()
    except Exception as exc:
        fbp_warn("Could not register Frame by Plane keymaps", exc)
    try:
        _fbp_hide_generation_overlay()
        if _fbp_bg_process_running():
            _fbp_bg_terminate_process(getattr(bpy.context, 'scene', None))
        _fbp_bg_clear_runtime_state(getattr(bpy.context, 'scene', None))
    except Exception as exc:
        fbp_warn("Could not initialize background-render runtime state", exc)


def unregister():
    _unregister_keymaps()
    _fbp_hide_generation_overlay()
    try:
        if _fbp_bg_process_running():
            _fbp_bg_terminate_process(getattr(bpy.context, 'scene', None))
        _fbp_bg_clear_runtime_state(getattr(bpy.context, 'scene', None))
    except Exception as exc:
        fbp_warn("Could not clear background-render runtime state", exc)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            fbp_warn(f"Could not unregister operator {cls.__name__}", exc)
