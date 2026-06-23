"""Optional, privacy-friendly review reminder for Frame By Plane.

The reminder is driven only by counters stored in AddonPreferences. It never
collects or transmits usage data and it never appears at Blender startup.
"""

from __future__ import annotations

import time

import bpy
from bpy.types import Operator

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
FBP_REVIEW_RELEASE_FAMILY = "5.8"
FBP_REVIEW_MIN_OPERATIONS = 5
FBP_REVIEW_MIN_AGE_SECONDS = 2 * 24 * 60 * 60
FBP_REVIEW_SNOOZE_OPERATIONS = 10
FBP_REVIEW_SNOOZE_SECONDS = 14 * 24 * 60 * 60


def _review_preferences(context=None):
    try:
        return fbp_get_addon_preferences(context)
    except FBP_DATA_ERRORS:
        return None


def _ensure_review_state(prefs, *, now=None):
    """Initialize persistent reminder state without opening any UI."""
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
        fbp_warn("Could not initialize review reminder preferences", exc)
        return None
    return prefs


def _review_is_eligible(prefs, *, now=None):
    prefs = _ensure_review_state(prefs, now=now)
    if prefs is None:
        return False
    now = float(time.time() if now is None else now)
    try:
        if not bool(getattr(prefs, "review_reminders_enabled", True)):
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


def _review_window_context():
    """Return a safe interactive window, or None while Blender is busy."""
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return None
    try:
        from .importer import fbp_fast_import_is_active
        if fbp_fast_import_is_active():
            return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None

    wm = getattr(bpy.context, "window_manager", None)
    windows = tuple(getattr(wm, "windows", ()) or ()) if wm else ()
    if not windows:
        return None
    try:
        if any(bool(getattr(getattr(window, "screen", None), "is_animation_playing", False)) for window in windows):
            return None
        if any(bool(getattr(scene, "fbp_background_render_running", False)) for scene in bpy.data.scenes):
            return None
    except FBP_DATA_ERRORS:
        return None

    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is not None:
            return window, screen
    return None


def _try_show_review_prompt():
    prefs = _review_preferences()
    if not _review_is_eligible(prefs):
        return None

    window_context = _review_window_context()
    if window_context is None:
        return 1.5

    window, screen = window_context
    try:
        with bpy.context.temp_override(window=window, screen=screen):
            result = bpy.ops.fbp.review_prompt('INVOKE_DEFAULT')
        if 'CANCELLED' in result:
            return 2.0
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not show the optional review reminder", exc)
    return None


def fbp_schedule_review_prompt(*, delay=2.5):
    """Schedule a deduplicated prompt check after the current operation ends."""
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
        bpy.ops.wm.url_open(url=str(url))
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not open {url}", exc)
        return False


class FBP_OT_ReviewPrompt(Operator):
    bl_idname = "fbp.review_prompt"
    bl_label = "Enjoying Frame By Plane? :)"
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
        intro = layout.column(align=False)
        intro.label(text="Hey! I hope Frame By Plane is making your 2D workflow a little easier :)")
        intro.label(text="If you have a minute, a quick review helps other 2D animators find it")
        intro.label(text="and gives me a hand making the next update even better.")
        intro.label(text="Thank you for using it!", icon='INFO')

        layout.separator()
        primary = layout.row()
        primary.scale_y = 1.25
        primary.operator("fbp.open_review_page", text="Leave a Review :)", icon='CHECKMARK')

        row = layout.row(align=True)
        row.operator("fbp.open_support_page", text="Report a Problem", icon='URL')
        row.operator("fbp.review_later", text="Maybe Later", icon='TIME')

        quiet = layout.row()
        quiet.alignment = 'CENTER'
        quiet.operator("fbp.review_never", text="Don't Ask Again", icon='CANCEL')

        note = layout.column(align=True)
        note.enabled = False
        note.label(text="No telemetry, no automatic messages, no data collection.", icon='LOCKED')


class FBP_OT_OpenReviewPage(Operator):
    bl_idname = "fbp.open_review_page"
    bl_label = "Leave a Review :)"
    bl_description = (
        "Open the official Frame By Plane review page on Blender Extensions. "
        "Frame By Plane does not send any usage or project data"
    )

    def execute(self, context):
        prefs = _ensure_review_state(_review_preferences(context))
        if prefs is not None:
            try:
                prefs.review_completed_version = FBP_REVIEW_RELEASE_FAMILY
                prefs.review_snooze_until = 0.0
                prefs.review_snooze_operation_target = 0
            except FBP_DATA_ERRORS:
                pass
        if not _open_external_url(FBP_REVIEW_URL):
            self.report({'WARNING'}, "Could not open the review page")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_OpenSupportPage(Operator):
    bl_idname = "fbp.open_support_page"
    bl_label = "Report a Problem"
    bl_description = (
        "Open the public Frame By Plane GitHub issue page. Nothing is submitted "
        "automatically and you can review the report before posting"
    )

    def execute(self, context):
        _set_review_snooze(_ensure_review_state(_review_preferences(context)))
        if not _open_external_url(FBP_SUPPORT_URL):
            self.report({'WARNING'}, "Could not open the support page")
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
        self.report({'INFO'}, "No problem — maybe another time :)")
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
    FBP_OT_ReviewPrompt,
    FBP_OT_OpenReviewPage,
    FBP_OT_OpenSupportPage,
    FBP_OT_ReviewLater,
    FBP_OT_ReviewNever,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _ensure_review_state(_review_preferences())


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_IO_ERRORS:
            pass
