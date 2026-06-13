"""Registration facade for Frame by Plane operators.

The implementation is split by responsibility; this module preserves the
public import path and the historical registration order.
"""

import bpy

try:
    from .operator_common import (
        _fbp_bg_clear_runtime_state, _fbp_bg_process_running,
        _fbp_bg_terminate_process, _fbp_hide_generation_overlay, fbp_warn,
    )
    from .operator_layers import *
    from .operator_import import *
    from .operator_sequence import *
    from .operator_render import *
    from .operator_procedural import *
    from .operator_project import *
except ImportError:
    from operator_common import (
        _fbp_bg_clear_runtime_state, _fbp_bg_process_running,
        _fbp_bg_terminate_process, _fbp_hide_generation_overlay, fbp_warn,
    )
    from operator_layers import *
    from operator_import import *
    from operator_sequence import *
    from operator_render import *
    from operator_procedural import *
    from operator_project import *


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
    FBP_OT_RelinkFromProjectRoot,
    FBP_OT_SelectMissingLayers,
    FBP_OT_SyncCollectionColors,
    FBP_OT_ShowImportProfile,
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
    except Exception as exc:
        for cls in reversed(registered):
            try:
                bpy.utils.unregister_class(cls)
            except (RuntimeError, ValueError) as rollback_exc:
                fbp_warn(f"Could not roll back operator {cls.__name__}", rollback_exc)
        raise exc
    try:
        _fbp_hide_generation_overlay()
        if _fbp_bg_process_running():
            _fbp_bg_terminate_process(getattr(bpy.context, 'scene', None))
        _fbp_bg_clear_runtime_state(getattr(bpy.context, 'scene', None))
    except (AttributeError, ReferenceError, RuntimeError) as exc:
        fbp_warn("Could not initialize background-render runtime state", exc)


def unregister():
    _fbp_hide_generation_overlay()
    try:
        if _fbp_bg_process_running():
            _fbp_bg_terminate_process(getattr(bpy.context, 'scene', None))
        _fbp_bg_clear_runtime_state(getattr(bpy.context, 'scene', None))
    except (AttributeError, ReferenceError, RuntimeError) as exc:
        fbp_warn("Could not clear background-render runtime state", exc)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError) as exc:
            fbp_warn(f"Could not unregister operator {cls.__name__}", exc)
