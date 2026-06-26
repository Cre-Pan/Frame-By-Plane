"""Privacy-friendly update notes and review prompts for Frame By Plane.

The What's New popup is stored entirely in AddonPreferences and appears at
most once for each installed extension version. The separate review reminder
is still driven only by local usage counters and never appears at Blender
startup. No telemetry, project data or automatic messages are transmitted.
"""

from __future__ import annotations

import time
import textwrap

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from .constants import (
    FBP_PUBLIC_VERSION_STRING, FBP_VERSION_FAMILY, FBP_VERSION_STRING, fbp_icon,
)
from .properties import fbp_get_addon_preferences
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_render_mutation_blocked,
    fbp_undo_guard_active,
    fbp_warn,
)
from .safe_tasks import schedule_once


FBP_REVIEW_URL = "https://extensions.blender.org/add-ons/frame-by-plane/reviews/"
FBP_SUPPORT_URL = "https://github.com/Cre-Pan/Frame-By-Plane/issues/new"
FBP_WHATS_NEW_URL = "https://extensions.blender.org/add-ons/frame-by-plane/#new"
FBP_REVIEW_RELEASE_FAMILY = FBP_VERSION_FAMILY
FBP_CURRENT_RELEASE = FBP_VERSION_STRING
FBP_PUBLIC_RELEASE = FBP_PUBLIC_VERSION_STRING

# Keep the public update popup deliberately user-facing. Internal audits,
# migration details and release-gate mechanics belong in diagnostic reports,
# not in the first screen shown after an update.
FBP_PUBLIC_RELEASE_ITEMS = (
    (
        "New effects",
        "Create inner and outer shadows with blur, position, opacity and blend modes; deform layers with the new planar 2D Lattice and its controllable mesh density.",
        "MODIFIER",
    ),
    (
        "More creative control",
        "Use effect masks, Layer Blend, transparent canvas expansion, Camera Flatten, effect presets and improved mesh controls directly on each layer.",
        "COLOR",
    ),
    (
        "Cleaner interface",
        "Image and Mesh effects are easier to find, Settings are split into clearer panels, advanced tools stay out of the way and the most important controls include deeper tooltips.",
        "PREFERENCES",
    ),
    (
        "Faster and more stable",
        "Effect updates are lighter and projects are safer across native sequence playback, rendering, save/reopen and Undo/Redo workflows.",
        "CHECKMARK",
    ),
)

FBP_FUTURE_ROADMAP_ITEMS = (
    (
        "Grease Pencil integration",
        "Use Grease Pencil objects as editable masks, guides and hybrid drawn elements inside Frame By Plane rigs.",
        "OUTLINER_COLLECTION",
    ),
    (
        "Production interchange",
        "Strengthen real-project import and relink workflows for PSD, PSB, Procreate, Toon Boom exports and video sources.",
        "IMPORT",
    ),
    (
        "Batch publishing",
        "Add reusable output presets, background-render queues and clearer validation for production delivery.",
        "RENDER_ANIMATION",
    ),
    (
        "Shareable libraries",
        "Package and exchange user-authored effects, presets and project templates without modifying the add-on source.",
        "NODETREE",
    ),
)


FBP_REVIEW_MIN_OPERATIONS = 5
FBP_REVIEW_MIN_AGE_SECONDS = 2 * 24 * 60 * 60
FBP_REVIEW_SNOOZE_OPERATIONS = 10
FBP_REVIEW_SNOOZE_SECONDS = 14 * 24 * 60 * 60


def _review_preferences(context=None):
    try:
        return fbp_get_addon_preferences(context)
    except FBP_DATA_ERRORS:
        return None


def _version_tuple(value):
    """Return a comparable numeric release tuple, or an empty tuple."""
    try:
        parts = tuple(int(part) for part in str(value or "").strip().split("."))
    except (TypeError, ValueError):
        return ()
    return parts if parts and all(part >= 0 for part in parts) else ()


def _ensure_review_state(prefs, *, now=None):
    """Initialize persistent prompt state without opening any UI."""
    if prefs is None:
        return None
    now = float(time.time() if now is None else now)
    try:
        if float(getattr(prefs, "review_install_time", 0.0) or 0.0) <= 0.0:
            prefs.review_install_time = now
        if str(getattr(prefs, "review_campaign_version", "") or "") != FBP_REVIEW_RELEASE_FAMILY:
            prefs.review_campaign_version = FBP_REVIEW_RELEASE_FAMILY
            prefs.review_snooze_until = 0.0
            prefs.review_snooze_operation_target = 0
            prefs.review_prompt_count = 0
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not initialize feedback preferences", exc)
        return None
    return prefs


def _whats_new_is_pending_ready(prefs):
    """Check pending release notes when preferences are already initialized."""
    if prefs is None:
        return False
    try:
        if not bool(getattr(prefs, "whats_new_enabled", True)):
            return False
        seen = str(getattr(prefs, "whats_new_last_seen_version", "") or "")
        if seen == FBP_CURRENT_RELEASE:
            return False
        current_key = _version_tuple(FBP_CURRENT_RELEASE)
        seen_key = _version_tuple(seen)
        # Never advertise an older release after a deliberate downgrade. A
        # missing or malformed value is treated as a first install/update.
        if seen_key and current_key and current_key <= seen_key:
            return False
        return True
    except FBP_DATA_ERRORS:
        return False


def _mark_whats_new_seen(prefs, *, now=None):
    if prefs is None:
        return False
    try:
        prefs.whats_new_last_seen_version = FBP_CURRENT_RELEASE
        prefs.whats_new_last_shown_time = float(time.time() if now is None else now)
        return True
    except FBP_DATA_ERRORS:
        return False


def _review_is_eligible(prefs, *, now=None):
    prefs = _ensure_review_state(prefs, now=now)
    if prefs is None:
        return False
    now = float(time.time() if now is None else now)
    try:
        if not bool(getattr(prefs, "review_reminders_enabled", True)):
            return False
        if _whats_new_is_pending_ready(prefs):
            # Never stack the optional review reminder on top of release notes.
            return False
        if str(getattr(prefs, "review_completed_version", "") or "") == FBP_REVIEW_RELEASE_FAMILY:
            return False

        installed_at = float(getattr(prefs, "review_install_time", 0.0) or 0.0)
        if installed_at <= 0.0 or now - installed_at < FBP_REVIEW_MIN_AGE_SECONDS:
            return False

        operations = int(getattr(prefs, "review_successful_operations", 0) or 0)
        completed_multiplane = bool(getattr(prefs, "review_multiplane_completed", False))
        if operations < FBP_REVIEW_MIN_OPERATIONS and not completed_multiplane:
            return False

        snooze_until = float(getattr(prefs, "review_snooze_until", 0.0) or 0.0)
        snooze_target = int(getattr(prefs, "review_snooze_operation_target", 0) or 0)
        if snooze_until > 0.0 or snooze_target > 0:
            time_ready = snooze_until > 0.0 and now >= snooze_until
            operations_ready = snooze_target > 0 and operations >= snooze_target
            if not (time_ready or operations_ready):
                return False
        return True
    except FBP_DATA_ERRORS:
        return False


def _set_review_snooze(prefs, *, now=None):
    if prefs is None:
        return False
    now = float(time.time() if now is None else now)
    try:
        operations = int(getattr(prefs, "review_successful_operations", 0) or 0)
        prefs.review_snooze_until = now + FBP_REVIEW_SNOOZE_SECONDS
        prefs.review_snooze_operation_target = operations + FBP_REVIEW_SNOOZE_OPERATIONS
        return True
    except FBP_DATA_ERRORS:
        return False


def _feedback_window_context():
    """Return ``(window_context, retry_delay)`` for safe feedback UI."""
    if bool(getattr(bpy.app, "background", False)):
        return None, None
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return None, 0.75
    try:
        from .importer import fbp_fast_import_is_active
        if fbp_fast_import_is_active():
            return None, 0.5
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None, 0.5

    wm = getattr(bpy.context, "window_manager", None)
    windows = tuple(getattr(wm, "windows", ()) or ()) if wm else ()
    if not windows:
        # During extension enable/startup the first window usually appears on
        # the following UI beat, so keep this retry deliberately short.
        return None, 0.10
    try:
        if any(bool(getattr(getattr(window, "screen", None), "is_animation_playing", False)) for window in windows):
            return None, 0.75
        if any(bool(getattr(scene, "fbp_background_render_running", False)) for scene in bpy.data.scenes):
            return None, 0.75
    except FBP_DATA_ERRORS:
        return None, 0.5

    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is not None:
            return (window, screen), None
    return None, 0.10


def _try_show_whats_new_prompt():
    if bool(getattr(bpy.app, "background", False)):
        return None
    prefs = _ensure_review_state(_review_preferences())
    if not _whats_new_is_pending_ready(prefs):
        return None

    window_context, retry_delay = _feedback_window_context()
    if window_context is None:
        return retry_delay

    window, screen = window_context
    try:
        with bpy.context.temp_override(window=window, screen=screen):
            result = bpy.ops.fbp.whats_new_prompt('INVOKE_DEFAULT')
        if 'CANCELLED' in result:
            # Context can still be settling immediately after an extension
            # update. Retry on the next UI beat instead of waiting seconds.
            return 0.15
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not show Frame By Plane release notes", exc)
    return None


def _try_show_review_prompt():
    prefs = _review_preferences()
    if not _review_is_eligible(prefs):
        return None

    window_context, retry_delay = _feedback_window_context()
    if window_context is None:
        return retry_delay

    window, screen = window_context
    try:
        with bpy.context.temp_override(window=window, screen=screen):
            result = bpy.ops.fbp.review_prompt('INVOKE_DEFAULT')
        if 'CANCELLED' in result:
            return None
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not show the optional review reminder", exc)
    return None


def fbp_schedule_whats_new_prompt(*, delay=0.0):
    """Schedule release notes immediately after a new version is enabled."""
    if bool(getattr(bpy.app, "background", False)):
        return False
    prefs = _ensure_review_state(_review_preferences())
    if not _whats_new_is_pending_ready(prefs):
        return False
    return schedule_once(
        "fbp_whats_new_prompt",
        _try_show_whats_new_prompt,
        first_interval=max(0.0, float(delay)),
    )


def fbp_schedule_review_prompt(*, delay=2.5):
    """Schedule a review check only when the local campaign is eligible."""
    if bool(getattr(bpy.app, "background", False)):
        return False
    if not _review_is_eligible(_review_preferences()):
        return False
    return schedule_once(
        "fbp_optional_review_prompt",
        _try_show_review_prompt,
        first_interval=max(0.5, float(delay)),
    )


def fbp_note_successful_operation(context=None, *, multiplane=False):
    """Record one successful user operation and schedule an optional prompt."""
    prefs = _ensure_review_state(_review_preferences(context))
    if prefs is None:
        return False
    try:
        prefs.review_successful_operations = max(
            0, int(getattr(prefs, "review_successful_operations", 0) or 0)
        ) + 1
        if multiplane:
            prefs.review_multiplane_completed = True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not update review reminder counters", exc)
        return False

    # The timer performs all eligibility and busy-state checks. No popup is ever
    # opened from the import operator itself.
    fbp_schedule_review_prompt(delay=3.0 if multiplane else 2.0)
    return True


def _open_external_url(url):
    try:
        result = bpy.ops.wm.url_open(url=str(url))
        return bool(result and 'FINISHED' in result)
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not open {url}", exc)
        return False


class FBP_OT_WhatsNewPrompt(Operator):
    bl_idname = "fbp.whats_new_prompt"
    bl_label = f"Frame By Plane {FBP_PUBLIC_RELEASE} — What’s New"
    bl_description = (
        "See the current Frame By Plane improvements and the focused future roadmap"
    )

    force: BoolProperty(
        name="Show Again",
        description="Open the current release notes even if this version was already viewed",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    def invoke(self, context, event):
        prefs = _ensure_review_state(_review_preferences(context))
        if prefs is None:
            return {'CANCELLED'}
        if not bool(self.force) and not _whats_new_is_pending_ready(prefs):
            return {'CANCELLED'}

        wm = context.window_manager
        try:
            result = wm.invoke_props_dialog(
                self,
                width=700,
                title=self.bl_label,
                confirm_text="Got It",
                cancel_default=False,
            )
        except TypeError:
            result = wm.invoke_props_dialog(self, width=700)
        if 'CANCELLED' not in result:
            _mark_whats_new_seen(prefs)
        return result

    def execute(self, context):
        _mark_whats_new_seen(_ensure_review_state(_review_preferences(context)))
        return {'FINISHED'}

    @staticmethod
    def _draw_cards(layout, items, *, columns=2):
        grid = layout.grid_flow(
            row_major=True,
            columns=columns,
            even_columns=True,
            even_rows=False,
            align=False,
        )
        for title, description, icon_key in items:
            card = grid.column(align=False)
            title_row = card.row(align=False)
            title_row.scale_y = 1.08
            title_row.label(text=title, icon=fbp_icon(icon_key))
            for line_text in textwrap.wrap(str(description), width=50) or (str(description),):
                detail = card.row(align=False)
                detail.enabled = False
                detail.label(text=line_text)
            card.separator(factor=0.25)

    def draw(self, context):
        layout = self.layout

        header = layout.column(align=False)
        title_row = header.row(align=False)
        title_row.alignment = 'CENTER'
        title_row.scale_y = 1.30
        title_row.label(
            text=f"Frame By Plane {FBP_PUBLIC_RELEASE}",
            icon=fbp_icon('PRESET'),
        )
        subtitle = header.row(align=False)
        subtitle.alignment = 'CENTER'
        subtitle.scale_y = 1.08
        subtitle.label(text="New effects, more creative control and a cleaner workflow")

        layout.separator(factor=0.55)
        current_box = layout.box()
        current_title = current_box.row(align=False)
        current_title.alignment = 'CENTER'
        current_title.scale_y = 1.16
        current_title.label(text="What’s New", icon=fbp_icon('CHECKMARK'))
        current_box.separator(factor=0.30)
        self._draw_cards(current_box, FBP_PUBLIC_RELEASE_ITEMS, columns=2)
        discover = current_box.row(align=False)
        discover.scale_y = 1.12
        discover.operator(
            "fbp.open_whats_new_page",
            text="Discover More",
            icon=fbp_icon('URL'),
        )

        layout.separator(factor=0.45)
        roadmap_box = layout.box()
        roadmap_title = roadmap_box.row(align=False)
        roadmap_title.alignment = 'CENTER'
        roadmap_title.scale_y = 1.16
        roadmap_title.label(text="Future Road Map", icon=fbp_icon('TIME'))
        roadmap_note = roadmap_box.row(align=False)
        roadmap_note.alignment = 'CENTER'
        roadmap_note.enabled = False
        roadmap_note.label(text="Focused long-term roadmap", icon=fbp_icon('INFO'))
        roadmap_box.separator(factor=0.30)
        self._draw_cards(roadmap_box, FBP_FUTURE_ROADMAP_ITEMS, columns=2)

        prefs = _ensure_review_state(_review_preferences(context))
        reviewed = bool(
            prefs is not None
            and str(getattr(prefs, "review_completed_version", "") or "")
            == FBP_REVIEW_RELEASE_FAMILY
        )

        layout.separator(factor=0.45)
        community = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=False,
            align=False,
        )

        feedback = community.box()
        feedback_title = feedback.row(align=False)
        feedback_title.alignment = 'CENTER'
        feedback_title.scale_y = 1.10
        feedback_title.label(text="Feedback", icon=fbp_icon('MESH_MONKEY'))
        feedback_text = feedback.row(align=False)
        feedback_text.alignment = 'CENTER'
        feedback_text.enabled = False
        feedback_text.label(text="Found a bug or a workflow that can be improved?")
        feedback_action = feedback.row(align=False)
        feedback_action.scale_y = 1.12
        feedback_action.operator(
            "fbp.open_support_page",
            text="Report a Bug",
            icon=fbp_icon('GHOST_DISABLED'),
        )

        review = community.box()
        review_title = review.row(align=False)
        review_title.alignment = 'CENTER'
        review_title.scale_y = 1.10
        review_title.label(text="Reviews", icon=fbp_icon('SOLO_ON'))
        if reviewed:
            review_text = review.row(align=False)
            review_text.alignment = 'CENTER'
            review_text.label(text="Thank you for supporting Frame By Plane!", icon=fbp_icon('CHECKMARK'))
        else:
            review_text = review.row(align=False)
            review_text.alignment = 'CENTER'
            review_text.enabled = False
            review_text.label(text="A quick review helps other animators discover it.")
            review_action = review.row(align=False)
            review_action.scale_y = 1.12
            review_action.operator(
                "fbp.open_review_page",
                text="Leave a Review",
                icon=fbp_icon('SOLO_ON'),
            )

        note = layout.row(align=False)
        note.enabled = False
        note.label(
            text="Shown once per installed update. No telemetry or project data is collected.",
            icon=fbp_icon('LOCKED'),
        )


class FBP_OT_ReviewPrompt(Operator):
    bl_idname = "fbp.review_prompt"
    bl_label = "Enjoying Frame By Plane?"
    bl_description = (
        "Show Frame By Plane's optional review reminder after real use. "
        "No usage data is collected or transmitted"
    )

    def invoke(self, context, event):
        prefs = _ensure_review_state(_review_preferences(context))
        if prefs is None or not _review_is_eligible(prefs):
            return {'CANCELLED'}
        now = time.time()
        try:
            prefs.review_last_prompt_time = now
            prefs.review_prompt_count = max(0, int(getattr(prefs, "review_prompt_count", 0) or 0)) + 1
            # Closing the popup without choosing a button behaves like Later,
            # preventing the reminder from reappearing on the next operation.
            _set_review_snooze(prefs, now=now)
        except FBP_DATA_ERRORS:
            pass
        return context.window_manager.invoke_popup(self, width=430)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        title = layout.row()
        title.alignment = 'CENTER'
        title.scale_y = 1.18
        title.label(text="Enjoying Frame By Plane?", icon=fbp_icon('MESH_MONKEY'))

        intro_lines = (
            "I hope Frame By Plane is making your 2D workflow a little easier.",
            "If you have a minute, a quick review helps other 2D animators find it",
            "and gives me a hand making the next update even better.",
        )
        for text in intro_lines:
            line = layout.row()
            line.alignment = 'CENTER'
            line.scale_y = 1.08
            line.label(text=text)
        thanks = layout.row()
        thanks.alignment = 'CENTER'
        thanks.scale_y = 1.08
        thanks.label(text="Thank you for using it!", icon=fbp_icon('MESH_MONKEY'))

        layout.separator()
        primary_actions = layout.row(align=False)
        primary_actions.scale_y = 1.25
        primary_actions.operator("fbp.open_review_page", text="Leave a Review", icon=fbp_icon('SOLO_ON'))
        primary_actions.operator("fbp.open_support_page", text="Report a Bug", icon=fbp_icon('GHOST_DISABLED'))

        secondary = layout.row(align=True)
        secondary.operator("fbp.review_later", text="Maybe Later", icon=fbp_icon('TIME'))
        secondary.operator("fbp.review_never", text="Don't Ask Again", icon=fbp_icon('CANCEL'))

        note = layout.column(align=True)
        note.enabled = False
        note.label(text="No telemetry, no automatic messages, no data collection.", icon=fbp_icon('LOCKED'))


class FBP_OT_OpenWhatsNewPage(Operator):
    bl_idname = "fbp.open_whats_new_page"
    bl_label = "Discover More"
    bl_description = (
        "Open the official Frame By Plane page on Blender Extensions, where the "
        "public What's New section and release notes are published"
    )

    def execute(self, context):
        if not _open_external_url(FBP_WHATS_NEW_URL):
            self.report({'WARNING'}, "Could not open the What's New page")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_OpenReviewPage(Operator):
    bl_idname = "fbp.open_review_page"
    bl_label = "Leave a Review"
    bl_description = (
        "Open the official Frame By Plane review page on Blender Extensions. "
        "Frame By Plane does not send any usage or project data"
    )

    def execute(self, context):
        if not _open_external_url(FBP_REVIEW_URL):
            self.report({'WARNING'}, "Could not open the review page")
            return {'CANCELLED'}
        prefs = _ensure_review_state(_review_preferences(context))
        if prefs is not None:
            try:
                prefs.review_completed_version = FBP_REVIEW_RELEASE_FAMILY
                prefs.review_snooze_until = 0.0
                prefs.review_snooze_operation_target = 0
            except FBP_DATA_ERRORS:
                pass
        return {'FINISHED'}


class FBP_OT_OpenSupportPage(Operator):
    bl_idname = "fbp.open_support_page"
    bl_label = "Report a Bug"
    bl_description = (
        "Open the public Frame By Plane GitHub issue page. Nothing is submitted "
        "automatically and you can review the report before posting"
    )

    def execute(self, context):
        _set_review_snooze(_ensure_review_state(_review_preferences(context)))
        if not _open_external_url(FBP_SUPPORT_URL):
            self.report({'WARNING'}, "Could not open the bug report page")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_ReviewLater(Operator):
    bl_idname = "fbp.review_later"
    bl_label = "Maybe Later"
    bl_description = (
        "Hide this reminder for at least fourteen days or ten more successful "
        "Frame By Plane operations, whichever happens first"
    )

    def execute(self, context):
        _set_review_snooze(_ensure_review_state(_review_preferences(context)))
        self.report({'INFO'}, "No problem. Maybe another time.")
        return {'FINISHED'}


class FBP_OT_ReviewNever(Operator):
    bl_idname = "fbp.review_never"
    bl_label = "Don't Ask Again"
    bl_description = (
        "Disable optional review reminders permanently. They can be enabled "
        "again at any time from the Frame By Plane extension preferences"
    )

    def execute(self, context):
        prefs = _ensure_review_state(_review_preferences(context))
        if prefs is not None:
            try:
                prefs.review_reminders_enabled = False
                prefs.review_snooze_until = 0.0
                prefs.review_snooze_operation_target = 0
            except FBP_DATA_ERRORS:
                pass
        self.report({'INFO'}, "Review reminders disabled")
        return {'FINISHED'}


classes = (
    FBP_OT_WhatsNewPrompt,
    FBP_OT_ReviewPrompt,
    FBP_OT_OpenWhatsNewPage,
    FBP_OT_OpenReviewPage,
    FBP_OT_OpenSupportPage,
    FBP_OT_ReviewLater,
    FBP_OT_ReviewNever,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _ensure_review_state(_review_preferences())
    fbp_schedule_whats_new_prompt(delay=0.0)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_IO_ERRORS:
            pass
