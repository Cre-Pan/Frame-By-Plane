"""Release notes and user-initiated feedback links for Frame By Plane.

The What's New dialog may appear once after an installed release-family update. Review links
are shown only inside extension preferences and are never opened or prompted
automatically. No telemetry, project data or automatic messages are sent.
"""

from __future__ import annotations

import re
import textwrap
import time
from pathlib import Path

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from .constants import FBP_FEEDBACK_RELEASE, FBP_PUBLIC_VERSION_STRING, fbp_icon
from .interface_preferences import fbp_get_addon_preferences
from .math_utils import clamp
from .registration import register_classes, unregister_classes
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_render_mutation_blocked,
    fbp_undo_guard_active,
    fbp_registration_busy,
    fbp_warn,
)
from .safe_tasks import schedule_once, scheduled_task_pending
from .ui_style import configure_layout


_PREVIOUS_GPU_POPUP = globals().get("_ACTIVE_GPU_POPUP")


def _retire_previous_gpu_popup_early():
    popup = _PREVIOUS_GPU_POPUP
    if popup is None:
        return False
    try:
        popup._cleanup()
        return True
    except FBP_DATA_ERRORS:
        return False


_retire_previous_gpu_popup_early()
_ACTIVE_GPU_POPUP = None


FBP_REVIEW_URL = "https://extensions.blender.org/add-ons/frame-by-plane/reviews/"
FBP_SUPPORT_URL = "https://github.com/Cre-Pan/Frame-By-Plane/issues/new"
FBP_WHATS_NEW_URL = "https://extensions.blender.org/add-ons/frame-by-plane/#new"
FBP_CURRENT_RELEASE = FBP_FEEDBACK_RELEASE
FBP_PUBLIC_RELEASE = FBP_PUBLIC_VERSION_STRING

# Native invoke_props_dialog() remains as a safe fallback. The preferred path
# draws the supplied release-splash PNGs directly, keeping custom button artwork
# pixel-aligned to the SVG hitboxes.
FBP_SPLASH_DISPLAY_SCALE = 0.82
FBP_WHATS_NEW_DIALOG_WIDTH = int(round(760 * FBP_SPLASH_DISPLAY_SCALE))
FBP_WHATS_NEW_DIALOG_HEIGHT = int(round(860 * FBP_SPLASH_DISPLAY_SCALE))
FBP_FEEDBACK_SCREEN_MARGIN = 18
FBP_WHATS_NEW_COVER_FILENAME = "splash/splash_bg_NORMAL.png"
FBP_SPLASH_ART_WIDTH = 903.0
FBP_SPLASH_ART_HEIGHT = 1010.0
# Exact top-left SVG coordinates from the 903 × 1010 source artwork.
FBP_SPLASH_BUTTON_RECTS = {
    "discover": (104.0, 830.0, 159.0, 40.0),
    "bug": (57.0, 926.0, 258.0, 40.0),
    "tutorial": (546.0, 926.0, 157.0, 40.0),
    "got": (718.0, 926.0, 128.0, 40.0),
}
FBP_SPLASH_BUTTON_SIZES = {
    "discover": (159, 40),
    "bug": (258, 40),
    "tutorial": (157, 40),
    "got": (128, 40),
}
FBP_SPLASH_BUTTON_FILES = {
    "discover": {
        "hover": "splash_button_discover_more_hover.png",
        "pressed": "splash_button_discover_more_pressed.png",
    },
    "bug": {
        "hover": "splash_button_bug_hover.png",
        "pressed": "splash_button_bug_pressed.png",
    },
    "tutorial": {
        "hover": "splash_button_tutorial_over.png",
        "pressed": "splash_button_tutorial_pressed.png",
    },
    "got": {
        "hover": "splash_button_got_it_hover.png",
        "pressed": "splash_button_got_it_pressed.png",
    },
}
FBP_SPLASH_COLORSPACE_FALLBACKS = ("Non-Color", "Raw")
FBP_SPLASH_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "splash"

FBP_SPLASH_SLICE_FILES = (
    ("splash_bg_slice_top.png", 0.0, 88.0),
    ("splash_bg_slice_upper.png", 88.0, 360.0),
    ("splash_bg_slice_lower.png", 448.0, 480.0),
    ("splash_bg_slice_footer.png", 928.0, 82.0),
)

FBP_SPLASH_CREDIT_TEXT = (
    "Cover made in Blender with Frame by Plane and Grease Pencil "
    "by Alessandro Pannoli"
)
FBP_SPLASH_CREDIT_FONT_SIZE = 15
FBP_SPLASH_CREDIT_BAND_HEIGHT = 34

FBP_GPU_POPUP_MAX_WIDTH = int(
    round(FBP_SPLASH_ART_WIDTH * FBP_SPLASH_DISPLAY_SCALE)
)
FBP_GPU_POPUP_MARGIN = 16
FBP_GPU_POPUP_RADIUS = 14
_FBP_WHATS_NEW_PREVIEW_COLLECTION = None
_FBP_WHATS_NEW_COVER_ICON_ID = 0
_FBP_GPU_UNIFORM_SHADER = None
_FBP_GPU_IMAGE_SHADER = None
# Keep the automatic release-splash state across an in-place extension reload.
# The normal presentation window is deliberately short, but time spent inside
# Preferences is suspended: an update performed there must wait until the user
# closes/leaves Preferences instead of opening a dialog inside that editor.
_FBP_AUTO_PROMPT_RELEASE = str(globals().get("_FBP_AUTO_PROMPT_RELEASE", "") or "")
_FBP_AUTO_PROMPT_DEADLINE = float(globals().get("_FBP_AUTO_PROMPT_DEADLINE", 0.0) or 0.0)
FBP_AUTO_PROMPT_WINDOW_SECONDS = 30.0
FBP_AUTO_PROMPT_PREFERENCES_POLL_SECONDS = 0.50

# Keep the public update popup deliberately user-facing. Internal audits and release-gate mechanics belong in diagnostic reports,
# not in the first screen shown after an update.
FBP_PUBLIC_RELEASE_ITEMS = (
    (
        "Dual Grease Pencil Colors",
        "Independent Stroke and Fill control in Draw Mode.",
        "COLOR",
    ),
    (
        "Edit Mode Color Control",
        "Recolor selected strokes and fills in one click.",
        "OUTLINER_OB_GREASEPENCIL",
    ),
    (
        "Smarter Camera Settings",
        "Aspect presets, orientation and linked pixel sizes.",
        "IMAGE_BACKGROUND",
    ),
    (
        "Bug Fixes",
        "Based on user reviews. Rate Frame By Plane and give feedback!",
        "GHOST_DISABLED",
    ),
    (
        "Better User Interface",
        "User interface and stability improvements.",
        "PREFERENCES",
    ),
)




def _preferences(context=None):
    try:
        return fbp_get_addon_preferences(context)
    except FBP_DATA_ERRORS:
        return None


def _version_tuple(value):
    """Return the comparable ``major.minor.patch`` release key."""
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(int(part) for part in match.groups()) if match else ()


def _whats_new_is_pending(prefs):
    """Check pending release notes when preferences are already initialized.

    Fresh installs start with an empty ``whats_new_last_seen_version``. Treat
    that as no pending popup so the add-on never opens a first-run splash
    unexpectedly. Once a user has viewed/dismissed the notes, every later
    intermediate release key may show the popup once. This keeps active testers
    informed without resurrecting the first-run splash on a clean install.
    """
    if prefs is None:
        return False
    try:
        if not bool(getattr(prefs, "whats_new_enabled", True)):
            return False
        seen = str(getattr(prefs, "whats_new_last_seen_version", "") or "").strip()
        if not seen:
            # Establish a silent baseline on first install. This prevents a
            # startup splash from appearing immediately, while still allowing
            # a later release-family upgrade to show release notes once.
            _mark_whats_new_seen(prefs)
            return False
        if seen == FBP_CURRENT_RELEASE:
            return False
        current_key = _version_tuple(FBP_CURRENT_RELEASE)
        seen_key = _version_tuple(seen)
        # Never advertise a release older than the stored 7.1.x feedback key.
        # Exact feedback keys are used so intermediate development releases can
        # still show What’s New once after the user has an established baseline.
        if seen_key and current_key and current_key <= seen_key:
            return False
        return bool(current_key and seen_key)
    except FBP_DATA_ERRORS:
        return False


def _save_feedback_preferences_soon():
    """Persist the feedback dismissal flag outside the current Blender session."""
    if bool(getattr(bpy.app, "background", False)):
        return False

    def _save():
        try:
            bpy.ops.wm.save_userpref()
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not persist Frame By Plane feedback preferences", exc)
        return None

    try:
        return bool(schedule_once(
            "feedback.save_preferences", _save, first_interval=0.05
        ))
    except FBP_DATA_ERRORS:
        return False


def _mark_whats_new_seen(prefs, *, persist=True):
    if prefs is None:
        return False
    try:
        current_value = str(getattr(prefs, "whats_new_last_seen_version", "") or "")
        prefs.whats_new_last_seen_version = FBP_CURRENT_RELEASE
        if bool(persist) and current_value != FBP_CURRENT_RELEASE:
            _save_feedback_preferences_soon()
        return True
    except FBP_DATA_ERRORS:
        return False


def _feedback_area_and_region(screen):
    """Return the best area/region pair for centered feedback UI.

    A visible 3D View is preferred so release prompts feel attached
    to the main creative workspace. When a workspace has no 3D View, the
    largest available editor is used and the cursor is placed at screen centre.
    """
    if screen is None:
        return None, None
    try:
        areas = tuple(getattr(screen, "areas", ()) or ())
    except FBP_DATA_ERRORS:
        return None, None
    if not areas:
        return None, None

    view_areas = tuple(area for area in areas if str(getattr(area, "type", "")) == 'VIEW_3D')
    candidates = view_areas or areas
    area = max(
        candidates,
        key=lambda item: max(1, int(getattr(item, "width", 1) or 1))
        * max(1, int(getattr(item, "height", 1) or 1)),
    )
    try:
        regions = tuple(getattr(area, "regions", ()) or ())
    except FBP_DATA_ERRORS:
        regions = ()
    region = next(
        (item for item in regions if str(getattr(item, "type", "")) == 'WINDOW'),
        None,
    )
    return area, region


def _feedback_screen_bounds(screen):
    """Return the Blender-window bounds described by all visible areas."""
    try:
        areas = tuple(getattr(screen, "areas", ()) or ()) if screen is not None else ()
    except FBP_DATA_ERRORS:
        areas = ()
    if not areas:
        return None
    try:
        min_x = min(int(getattr(item, "x", 0) or 0) for item in areas)
        min_y = min(int(getattr(item, "y", 0) or 0) for item in areas)
        max_x = max(
            int(getattr(item, "x", 0) or 0)
            + max(1, int(getattr(item, "width", 1) or 1))
            for item in areas
        )
        max_y = max(
            int(getattr(item, "y", 0) or 0)
            + max(1, int(getattr(item, "height", 1) or 1))
            for item in areas
        )
    except FBP_DATA_ERRORS:
        return None
    return min_x, min_y, max_x, max_y


def _feedback_center_coordinates(screen, area=None, region=None):
    """Return the geometric centre of the complete Blender window.

    ``area`` and ``region`` remain accepted for backwards compatibility and
    for the context override used to invoke the operator, but feedback windows
    are intentionally centred on the complete screen rather than one editor.
    """
    del area, region
    bounds = _feedback_screen_bounds(screen)
    if bounds is None:
        return None
    min_x, min_y, max_x, max_y = bounds
    return (min_x + max_x) // 2, (min_y + max_y) // 2


def _feedback_ui_scale(context):
    """Return the UI scale used to translate dialog units into window pixels."""
    try:
        preferences = getattr(context, "preferences", None)
        system = getattr(preferences, "system", None)
        value = float(getattr(system, "ui_scale", 1.0) or 1.0)
    except FBP_DATA_ERRORS:
        value = 1.0
    return max(0.75, min(3.0, value))


def _feedback_popup_anchor_coordinates(
    context,
    screen,
    *,
    popup_width,
    popup_height,
):
    """Return Blender's top-centre popup anchor for a centred dialog body.

    Desktop Blender places these feedback windows below the event Y position.
    Supplying the screen centre therefore centres only the popup's top pivot and
    makes the complete dialog appear too low.  This helper compensates for the
    popup dimensions and clamps the result inside the active Blender window.
    """
    bounds = _feedback_screen_bounds(screen)
    centre = _feedback_center_coordinates(screen)
    if bounds is None or centre is None:
        return None

    min_x, min_y, max_x, max_y = bounds
    scale = _feedback_ui_scale(context)
    width = max(1, int(round(float(popup_width) * scale)))
    height = max(1, int(round(float(popup_height) * scale)))
    margin = max(4, int(round(FBP_FEEDBACK_SCREEN_MARGIN * scale)))

    # Blender uses the event as a top-centre style anchor for these two popup
    # APIs.  Move it up by half the body height so the body centre aligns with
    # the actual Blender-window centre.
    anchor_x = int(centre[0])
    anchor_y = int(centre[1] + height * 0.5)

    half_width = width // 2
    if max_x - min_x > width + margin * 2:
        anchor_x = max(min_x + margin + half_width, min(max_x - margin - half_width, anchor_x))
    else:
        anchor_x = int(centre[0])

    # The popup extends downward from the anchor. Keep both the title and the
    # lower action row visible when the window is smaller than the estimate.
    anchor_y = min(max_y - margin, anchor_y)
    if anchor_y - height < min_y + margin:
        anchor_y = min(max_y - margin, min_y + margin + height)

    return anchor_x, anchor_y


def _feedback_override(window, screen, area=None, region=None):
    override = {"window": window, "screen": screen}
    if area is not None:
        override["area"] = area
    if region is not None:
        override["region"] = region
    return override


def _feedback_pointer(value):
    try:
        return int(value.as_pointer()) if value is not None else 0
    except FBP_DATA_ERRORS:
        return 0


def _feedback_resolve_ui_context(window_key, area_key=0, region_key=0):
    """Resolve live Window/Screen/Area/Region wrappers from primitive keys."""
    try:
        wm = getattr(bpy.context, "window_manager", None)
        windows = tuple(getattr(wm, "windows", ()) or ()) if wm is not None else ()
        window = next(
            (candidate for candidate in windows if _feedback_pointer(candidate) == int(window_key or 0)),
            None,
        )
        if window is None:
            return None
        screen = getattr(window, "screen", None)
        if screen is None:
            return None
        area = None
        if area_key:
            area = next(
                (candidate for candidate in tuple(getattr(screen, "areas", ()) or ())
                 if _feedback_pointer(candidate) == int(area_key)),
                None,
            )
        region = None
        if area is not None and region_key:
            region = next(
                (candidate for candidate in tuple(getattr(area, "regions", ()) or ())
                 if _feedback_pointer(candidate) == int(region_key)),
                None,
            )
        return window, screen, area, region
    except FBP_DATA_ERRORS:
        return None


def _restore_feedback_cursor(window, coordinates):
    if window is None or not coordinates:
        return None
    try:
        window.cursor_warp(int(coordinates[0]), int(coordinates[1]))
    except FBP_DATA_ERRORS:
        pass
    return None


def _schedule_feedback_cursor_restore(window, coordinates, *, delay=0.08):
    """Restore the cursor without retaining a Window RNA wrapper in a timer."""
    if window is None or not coordinates:
        return False
    try:
        window_key = int(window.as_pointer())
    except FBP_DATA_ERRORS:
        return False
    point = (int(coordinates[0]), int(coordinates[1]))

    def _restore():
        try:
            wm = getattr(bpy.context, "window_manager", None)
            current = next(
                (item for item in tuple(getattr(wm, "windows", ()) or ())
                 if int(item.as_pointer()) == window_key),
                None,
            )
        except FBP_DATA_ERRORS:
            current = None
        return _restore_feedback_cursor(current, point)

    return bool(schedule_once(
        f"feedback.cursor_restore:{window_key}",
        _restore,
        first_interval=max(0.01, float(delay)),
    ))


def _defer_centered_feedback_invoke(
    context,
    event,
    *,
    task_name,
    callback,
    popup_width,
    popup_height,
):
    """Reinvoke one feedback operator with a centred synthetic mouse event.

    Blender's popup APIs intentionally expose width but no x/y placement. The
    operator is therefore invoked on the next UI beat after temporarily warping
    the cursor to the centre of the largest 3D View. The original cursor
    location is restored immediately after the popup has been anchored.
    """
    if bool(getattr(bpy.app, "background", False)) or not callable(callback):
        return False

    window = getattr(context, "window", None)
    screen = getattr(context, "screen", None) or getattr(window, "screen", None)
    if window is None or screen is None:
        return False

    area, region = _feedback_area_and_region(screen)
    target = _feedback_popup_anchor_coordinates(
        context,
        screen,
        popup_width=popup_width,
        popup_height=popup_height,
    )
    if target is None:
        return False

    try:
        original = (int(getattr(event, "mouse_x", target[0])), int(getattr(event, "mouse_y", target[1])))
    except (TypeError, ValueError):
        original = target
    window_key = _feedback_pointer(window)
    area_key = _feedback_pointer(area)
    region_key = _feedback_pointer(region)
    if not window_key:
        return False

    def _invoke_centered():
        resolved = _feedback_resolve_ui_context(window_key, area_key, region_key)
        if resolved is None:
            return None
        current_window, current_screen, current_area, current_region = resolved
        override = _feedback_override(
            current_window, current_screen, current_area, current_region
        )
        try:
            current_window.cursor_warp(int(target[0]), int(target[1]))
            with bpy.context.temp_override(**override):
                callback()
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not centre Frame By Plane feedback UI", exc)
        finally:
            _schedule_feedback_cursor_restore(current_window, original)
        return None

    return schedule_once(
        str(task_name),
        _invoke_centered,
        first_interval=0.01,
    )


def _feedback_windows_show_preferences(windows):
    """Inspect a window snapshot without retaining any of its RNA wrappers."""
    try:
        for window in tuple(windows or ()):
            screen = getattr(window, "screen", None)
            areas = tuple(getattr(screen, "areas", ()) or ()) if screen else ()
            if any(
                str(getattr(area, "type", "") or "") == "PREFERENCES"
                for area in areas
            ):
                return True
    except FBP_DATA_ERRORS:
        # A window can disappear while its RNA list is being traversed. Treat
        # that beat as unsettled; the next poll resolves the live UI afresh.
        return True
    return False


def _feedback_preferences_open(window_manager=None):
    """Return whether any live Blender window is currently showing Preferences.

    Only primitive state escapes this function. In particular, no Window,
    Screen or Area RNA wrapper is retained while a dedicated Preferences window
    is being destroyed after an extension update.
    """
    if bool(getattr(bpy.app, "background", False)):
        return False
    try:
        wm = window_manager or getattr(bpy.context, "window_manager", None)
        windows = tuple(getattr(wm, "windows", ()) or ()) if wm else ()
        return _feedback_windows_show_preferences(windows)
    except FBP_DATA_ERRORS:
        return True


def _defer_auto_prompt_for_preferences(now):
    """Suspend expiry while Preferences owns the user's attention."""
    global _FBP_AUTO_PROMPT_DEADLINE
    _FBP_AUTO_PROMPT_DEADLINE = float(now) + FBP_AUTO_PROMPT_WINDOW_SECONDS
    return FBP_AUTO_PROMPT_PREFERENCES_POLL_SECONDS


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
        if any(bool(getattr(scene, "fbp_background_render_running", False)) for scene in tuple(getattr(bpy.data, "scenes", ()) or ())):
            return None, 0.75
    except FBP_DATA_ERRORS:
        return None, 0.5

    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is not None:
            area, region = _feedback_area_and_region(screen)
            return (window, screen, area, region), None
    return None, 0.10


def _try_show_whats_new_prompt():
    global _FBP_AUTO_PROMPT_RELEASE, _FBP_AUTO_PROMPT_DEADLINE
    if bool(getattr(bpy.app, "background", False)):
        return None
    if fbp_registration_busy():
        return 0.20
    prefs = _preferences()
    if not _whats_new_is_pending(prefs):
        _FBP_AUTO_PROMPT_DEADLINE = 0.0
        return None
    if _ACTIVE_GPU_POPUP is not None:
        _FBP_AUTO_PROMPT_DEADLINE = 0.0
        return None

    now = time.monotonic()
    # Automatic release notes never interrupt Preferences. Keep the deadline
    # sliding while any Preferences editor/window exists, then use a freshly
    # resolved creative-workspace context as soon as the user leaves it.
    if _feedback_preferences_open():
        return _defer_auto_prompt_for_preferences(now)

    if _FBP_AUTO_PROMPT_DEADLINE and now > _FBP_AUTO_PROMPT_DEADLINE:
        # Do not permanently consume an update notice if Blender never reached
        # a safe presentation context. A later enable/restart may claim it.
        _FBP_AUTO_PROMPT_RELEASE = ""
        _FBP_AUTO_PROMPT_DEADLINE = 0.0
        return None

    window_context, retry_delay = _feedback_window_context()
    if window_context is None:
        return retry_delay

    window, screen, area, region = window_context
    try:
        with bpy.context.temp_override(**_feedback_override(window, screen, area, region)):
            # The GPU card centers itself. Complete its invocation in this UI
            # beat so a reload cannot drop a second, deferred invocation after
            # the automatic request has already been considered successful.
            result = bpy.ops.fbp.whats_new_prompt('INVOKE_DEFAULT', centered_invoke=True)
        if 'CANCELLED' in result:
            # Context can still be settling immediately after an extension
            # update. Retry on the next UI beat instead of waiting seconds.
            return 0.15
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not show Frame By Plane release notes", exc)
        return 0.25
    _FBP_AUTO_PROMPT_DEADLINE = 0.0
    return None


def _claim_auto_whats_new_prompt(*, now=None):
    """Claim this release's sole automatic splash opportunity."""
    global _FBP_AUTO_PROMPT_RELEASE, _FBP_AUTO_PROMPT_DEADLINE
    if _FBP_AUTO_PROMPT_RELEASE == FBP_CURRENT_RELEASE and (
        not _FBP_AUTO_PROMPT_DEADLINE
        or scheduled_task_pending("fbp_whats_new_prompt")
    ):
        return False
    # A positive deadline denotes an unshown request. Enable/reload may retire
    # the scheduler while Preferences is still open; allow that request to be
    # queued again. A presented popup has deadline zero and stays one-shot.
    current_time = time.monotonic() if now is None else float(now)
    _FBP_AUTO_PROMPT_RELEASE = FBP_CURRENT_RELEASE
    _FBP_AUTO_PROMPT_DEADLINE = current_time + FBP_AUTO_PROMPT_WINDOW_SECONDS
    return True


def fbp_schedule_whats_new_prompt(*, delay=0.0):
    """Offer release notes once after a new version is safely enabled."""
    global _FBP_AUTO_PROMPT_RELEASE, _FBP_AUTO_PROMPT_DEADLINE
    if bool(getattr(bpy.app, "background", False)):
        return False
    prefs = _preferences()
    if not _whats_new_is_pending(prefs):
        return False
    previous_release = _FBP_AUTO_PROMPT_RELEASE
    previous_deadline = _FBP_AUTO_PROMPT_DEADLINE
    if not _claim_auto_whats_new_prompt():
        return False
    accepted = bool(schedule_once(
        "fbp_whats_new_prompt",
        _try_show_whats_new_prompt,
        first_interval=max(0.0, float(delay)),
    ))
    if not accepted:
        # A transient registration/Undo gate must not consume the one automatic
        # opportunity. A later safe registration can claim it again.
        _FBP_AUTO_PROMPT_RELEASE = previous_release
        _FBP_AUTO_PROMPT_DEADLINE = previous_deadline
    return accepted


def _open_external_url(url):
    try:
        result = bpy.ops.wm.url_open(url=str(url))
        return bool(result and 'FINISHED' in result)
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not open {url}", exc)
        return False


def _invoke_live_tutorial_from_view3d():
    """Open the live tutorial after splash/full-area teardown has settled."""
    view_context = _feedback_view3d_context()
    if view_context is None:
        return 0.10
    window, screen, area, region = view_context
    try:
        with bpy.context.temp_override(**_feedback_override(window, screen, area, region)):
            result = bpy.ops.fbp.live_tutorial('INVOKE_DEFAULT')
        if result and 'CANCELLED' not in result:
            return None
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not open Frame By Plane Live Tutorial", exc)
    return None


def _schedule_live_tutorial(*, delay=0.10):
    return schedule_once(
        "fbp_open_live_tutorial",
        _invoke_live_tutorial_from_view3d,
        first_interval=max(0.0, float(delay)),
    )


def _whats_new_cover_path():
    return FBP_SPLASH_ASSET_DIR / Path(FBP_WHATS_NEW_COVER_FILENAME).name


def _configured_splash_asset_filenames():
    """Return the PNG artwork still required by the release splash."""
    filenames = {Path(FBP_WHATS_NEW_COVER_FILENAME).name}
    filenames.update(str(filename) for filename, _y, _h in FBP_SPLASH_SLICE_FILES)
    for state_files in FBP_SPLASH_BUTTON_FILES.values():
        filenames.update(str(filename) for filename in state_files.values())
    return tuple(sorted(filenames))


def _splash_layout_errors():
    """Return deterministic packaging errors for the SVG-derived splash layout."""
    errors = []
    if FBP_SPLASH_ART_WIDTH <= 0.0 or FBP_SPLASH_ART_HEIGHT <= 0.0:
        errors.append("invalid splash artwork dimensions")
    expected_names = set(FBP_SPLASH_BUTTON_SIZES)
    if set(FBP_SPLASH_BUTTON_RECTS) != expected_names:
        errors.append("button hitbox names do not match button-size names")
    if set(FBP_SPLASH_BUTTON_FILES) != expected_names:
        errors.append("button asset names do not match button-size names")
    for name, rect in FBP_SPLASH_BUTTON_RECTS.items():
        try:
            x, y, width, height = (float(value) for value in rect)
        except (TypeError, ValueError):
            errors.append(f"{name}: invalid hitbox")
            continue
        expected_size = FBP_SPLASH_BUTTON_SIZES.get(name)
        if expected_size and (int(round(width)), int(round(height))) != expected_size:
            errors.append(f"{name}: hitbox size does not match PNG size")
        if x < 0.0 or y < 0.0 or width <= 0.0 or height <= 0.0:
            errors.append(f"{name}: hitbox is outside the artwork")
        elif x + width > FBP_SPLASH_ART_WIDTH or y + height > FBP_SPLASH_ART_HEIGHT:
            errors.append(f"{name}: hitbox exceeds the artwork bounds")
    slice_total = 0.0
    for filename, y, height in FBP_SPLASH_SLICE_FILES:
        try:
            y = float(y); height = float(height)
        except (TypeError, ValueError):
            errors.append(f"{filename}: invalid slice geometry")
            continue
        if y < 0.0 or height <= 0.0 or y + height > FBP_SPLASH_ART_HEIGHT:
            errors.append(f"{filename}: slice exceeds artwork bounds")
        slice_total += height
    if int(round(slice_total)) != int(round(FBP_SPLASH_ART_HEIGHT)):
        errors.append("background slice heights do not cover the full artwork")
    return tuple(errors)


def _release_whats_new_cover_preview():
    global _FBP_WHATS_NEW_PREVIEW_COLLECTION, _FBP_WHATS_NEW_COVER_ICON_ID
    if _FBP_WHATS_NEW_PREVIEW_COLLECTION is not None:
        try:
            bpy.utils.previews.remove(_FBP_WHATS_NEW_PREVIEW_COLLECTION)
        except FBP_DATA_IO_ERRORS:
            pass
    _FBP_WHATS_NEW_PREVIEW_COLLECTION = None
    _FBP_WHATS_NEW_COVER_ICON_ID = 0


def _load_whats_new_preview(path, key):
    global _FBP_WHATS_NEW_PREVIEW_COLLECTION
    pcoll = _FBP_WHATS_NEW_PREVIEW_COLLECTION
    if pcoll is None:
        pcoll = bpy.utils.previews.new()
        _FBP_WHATS_NEW_PREVIEW_COLLECTION = pcoll
    preview = pcoll.get(key)
    if preview is None:
        preview = pcoll.load(key, str(path), 'IMAGE')
    return int(getattr(preview, "icon_id", 0) or 0)


def _whats_new_cover_icon_id():
    """Fallback native-dialog preview ID for environments without View3D/GPU."""
    global _FBP_WHATS_NEW_COVER_ICON_ID
    if _FBP_WHATS_NEW_COVER_ICON_ID:
        return _FBP_WHATS_NEW_COVER_ICON_ID
    path = _whats_new_cover_path()
    if not path.exists() or not path.is_file():
        return 0
    try:
        _FBP_WHATS_NEW_COVER_ICON_ID = _load_whats_new_preview(path, "fbp_whats_new_cover")
        return _FBP_WHATS_NEW_COVER_ICON_ID
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not load What's New cover", exc)
        _release_whats_new_cover_preview()
        return 0


def _feedback_view3d_context(context=None):
    """Return a concrete View3D context for the GPU What's New overlay."""
    context = context or getattr(bpy, "context", None)
    if bool(getattr(bpy.app, "background", False)) or context is None:
        return None
    try:
        current_area = getattr(context, "area", None)
        current_region = getattr(context, "region", None)
        if str(getattr(current_area, "type", "")) == 'VIEW_3D' and str(getattr(current_region, "type", "")) == 'WINDOW':
            return (
                getattr(context, "window", None),
                getattr(context, "screen", None),
                current_area,
                current_region,
            )
    except FBP_DATA_ERRORS:
        pass
    wm = getattr(context, "window_manager", None) or getattr(bpy.context, "window_manager", None)
    for window in tuple(getattr(wm, "windows", ()) or ()) if wm else ():
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        view_areas = [area for area in tuple(getattr(screen, "areas", ()) or ()) if str(getattr(area, "type", "")) == 'VIEW_3D']
        if not view_areas:
            continue
        area = max(
            view_areas,
            key=lambda item: max(1, int(getattr(item, "width", 1) or 1))
            * max(1, int(getattr(item, "height", 1) or 1)),
        )
        region = next(
            (item for item in tuple(getattr(area, "regions", ()) or ()) if str(getattr(item, "type", "")) == 'WINDOW'),
            None,
        )
        if region is not None:
            return window, screen, area, region
    return None


def _gpu_uniform_shader():
    global _FBP_GPU_UNIFORM_SHADER
    if _FBP_GPU_UNIFORM_SHADER is not None:
        return _FBP_GPU_UNIFORM_SHADER
    try:
        import gpu
        _FBP_GPU_UNIFORM_SHADER = gpu.shader.from_builtin('UNIFORM_COLOR')
    except FBP_DATA_ERRORS:
        _FBP_GPU_UNIFORM_SHADER = None
    return _FBP_GPU_UNIFORM_SHADER


def _gpu_image_shader():
    global _FBP_GPU_IMAGE_SHADER
    if _FBP_GPU_IMAGE_SHADER is not None:
        return _FBP_GPU_IMAGE_SHADER
    try:
        import gpu
        _FBP_GPU_IMAGE_SHADER = gpu.shader.from_builtin('IMAGE')
    except FBP_DATA_ERRORS:
        _FBP_GPU_IMAGE_SHADER = None
    return _FBP_GPU_IMAGE_SHADER


def _gpu_rect(shader, x, y, width, height, color):
    try:
        from gpu_extras.batch import batch_for_shader
        width = float(width); height = float(height)
        if width <= 0.0 or height <= 0.0 or shader is None:
            return
        x = float(x); y = float(y)
        coords = ((x, y), (x + width, y), (x, y + height), (x + width, y + height))
        batch = batch_for_shader(shader, 'TRI_STRIP', {"pos": coords})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
    except FBP_DATA_ERRORS:
        pass


def _gpu_rounded_rect(shader, x, y, width, height, radius, color, *, segments=8):
    """Draw a filled rounded rectangle for the GPU overlay.

    Blender add-ons cannot reuse the built-in C splash-screen widgets, so the
    GPU What’s New overlay draws its own lightweight card. Keeping this helper
    allocation-local avoids retaining GPU batch objects across reloads.
    """
    try:
        import math
        from gpu_extras.batch import batch_for_shader
        x = float(x); y = float(y); width = float(width); height = float(height)
        if width <= 0.0 or height <= 0.0 or shader is None:
            return
        radius = float(max(0.0, min(radius, width * 0.5, height * 0.5)))
        if radius <= 0.5:
            _gpu_rect(shader, x, y, width, height, color)
            return
        # Horizontal strip tessellation avoids the diagonal fan artefacts that
        # can appear on some GPUs/drivers when a translucent rounded rect is
        # drawn as a single TRI_FAN.
        steps = max(6, int(segments) * 2)
        coords = []
        for step in range(steps + 1):
            yy = y + height * (step / steps)
            inset = 0.0
            bottom = yy - (y + radius)
            top = yy - (y + height - radius)
            if yy < y + radius:
                inset = radius - math.sqrt(max(0.0, radius * radius - bottom * bottom))
            elif yy > y + height - radius:
                inset = radius - math.sqrt(max(0.0, radius * radius - top * top))
            coords.append((x + inset, yy))
            coords.append((x + width - inset, yy))
        batch = batch_for_shader(shader, 'TRI_STRIP', {"pos": coords})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
    except FBP_DATA_ERRORS:
        pass

def _fbp_import_blf(gpu_module=None):
    try:
        blf_module = getattr(gpu_module, "blf", None) if gpu_module is not None else None
        if blf_module is not None:
            return blf_module
    except FBP_DATA_ERRORS:
        pass
    try:
        import blf as blf_module
        return blf_module
    except ImportError:
        return None


def _gpu_text(blf_module, text, x, y, size, color=(1.0, 1.0, 1.0, 1.0), *, font_id=0):
    try:
        blf_module.size(font_id, int(size))
        blf_module.color(font_id, *color)
        blf_module.position(font_id, float(x), float(y), 0.0)
        blf_module.draw(font_id, str(text))
    except FBP_DATA_ERRORS:
        pass


def _gpu_draw_texture(texture, x, y, width, height):
    """Draw a PNG texture in POST_PIXEL space using Blender's built-in image shader."""
    try:
        from gpu_extras.batch import batch_for_shader
        width = float(width); height = float(height)
        if width <= 0.0 or height <= 0.0 or texture is None:
            return
        shader = _gpu_image_shader()
        if shader is None:
            return
        x = float(x); y = float(y)
        coords = ((x, y), (x + width, y), (x, y + height), (x + width, y + height))
        tex_coords = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
        batch = batch_for_shader(shader, 'TRI_STRIP', {"pos": coords, "texCoord": tex_coords})
        shader.bind()
        try:
            shader.uniform_sampler("image", texture)
        except FBP_DATA_ERRORS:
            pass
        batch.draw(shader)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not draw Frame By Plane splash texture", exc)


def _load_splash_image_from_disk(path):
    """Load a splash asset and refresh same-path images after addon updates."""
    images = bpy.data.images
    previous_count = len(images)
    image = images.load(str(path), check_existing=True)
    # Image loading runs synchronously on Blender's main thread. A new
    # datablock is already decoded: only a reused one needs refreshing after
    # an in-place update. Avoid a second disk read/decode on the first load.
    if len(images) == previous_count:
        try:
            image.reload()
        except FBP_DATA_ERRORS:
            pass
    return image


def _prepare_splash_image_for_gpu(image):
    """Apply the stable GPU settings for release-splash artwork."""
    if image is None:
        return None
    try:
        image.alpha_mode = 'PREMUL'
    except FBP_DATA_ERRORS:
        pass
    try:
        image.use_view_as_render = False
    except FBP_DATA_ERRORS:
        pass
    for colorspace_name in FBP_SPLASH_COLORSPACE_FALLBACKS:
        try:
            image.colorspace_settings.name = colorspace_name
            break
        except FBP_DATA_ERRORS:
            continue
    return image
class FBP_OT_WhatsNewGpuPopup(Operator):
    bl_idname = "fbp.whats_new_gpu_popup"
    bl_label = "Frame By Plane What’s New Overlay"
    bl_description = "Show the current Frame By Plane update as a GPU-drawn overlay with a full-width cover image"
    bl_options = {'INTERNAL'}

    force: BoolProperty(description='Toggle this option for the current release or support popup. Disabled keeps the data available but prevents this behavior from being applied.', 
        name="Show Again",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    start_tutorial: BoolProperty(
        name="Start Tutorial",
        description="Open the interactive Frame By Plane Live Tutorial",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    _draw_handler = None
    _area = None
    _region = None
    _cover_image = None
    _cover_texture = None
    _slice_images = None
    _slice_textures = None
    _button_images = None
    _button_textures = None
    _buttons = None
    _hover_button = None
    _pressed_button = None
    _popup_offset = None
    _last_popup_rect = None
    _dragging = False
    _drag_start_mouse = None
    _drag_start_offset = None
    _cover_loaded_filename = ""
    _fullscreen_active = False
    _fullscreen_window = None
    _fullscreen_screen = None
    _fullscreen_restoring = False

    @classmethod
    def poll(cls, context):
        return _feedback_view3d_context(context) is not None

    def _enter_temporary_full_area(self, context, window, screen, area, region):
        """Temporarily maximize the target View3D for a single splash overlay.

        The GPU splash is tied to a View3D region. Expanding that region avoids
        duplicate overlays in split-viewport layouts and keeps the artwork
        visually centred in Blender while the splash/tutorial is open.
        """
        if window is None or screen is None or area is None or region is None:
            return False
        try:
            override = _feedback_override(window, screen, area, region)
            with context.temp_override(**override):
                try:
                    # Keep Blender's top/bottom UI chrome visible while the target
                    # area is temporarily maximized. Hiding panels made restore
                    # less reliable on some layouts and could leave Blender
                    # looking fullscreen after the splash closed.
                    bpy.ops.screen.screen_full_area(use_hide_panels=False)
                except TypeError:
                    bpy.ops.screen.screen_full_area()
            self._fullscreen_active = True
            self._fullscreen_restoring = False
            self._fullscreen_window = window
            self._fullscreen_screen = getattr(window, "screen", screen)
            return True
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not enter temporary Full Area for splash", exc)
            self._fullscreen_active = False
            self._fullscreen_restoring = False
            self._fullscreen_window = None
            self._fullscreen_screen = None
            return False

    @staticmethod
    def _restore_full_area_once(window, screen):
        """Try to leave Blender's temporary Full Area using several safe contexts."""
        if window is None:
            window = getattr(bpy.context, "window", None)
        if screen is None and window is not None:
            screen = getattr(window, "screen", None)
        if window is None or screen is None:
            return False

        candidates = []

        def _add(area, region):
            if area is None or region is None:
                return
            item = (area, region)
            if item not in candidates:
                candidates.append(item)

        try:
            current_area = getattr(bpy.context, "area", None)
            current_region = getattr(bpy.context, "region", None)
            if getattr(current_area, "id_data", None) is screen:
                _add(current_area, current_region)
        except FBP_DATA_IO_ERRORS:
            pass

        try:
            area, region = _feedback_area_and_region(screen)
            _add(area, region)
        except FBP_DATA_IO_ERRORS:
            pass

        try:
            for area in tuple(getattr(screen, "areas", ()) or ()):  # fallback: any WINDOW region
                region = next((item for item in tuple(getattr(area, "regions", ()) or ()) if str(getattr(item, "type", "")) == 'WINDOW'), None)
                _add(area, region)
        except FBP_DATA_IO_ERRORS:
            pass

        if not candidates:
            return False

        for area, region in candidates:
            override = _feedback_override(window, screen, area, region)
            try:
                with bpy.context.temp_override(**override):
                    try:
                        result = bpy.ops.screen.back_to_previous()
                        if not result or 'CANCELLED' not in result:
                            return True
                    except FBP_DATA_IO_ERRORS:
                        pass
                    try:
                        result = bpy.ops.screen.screen_full_area(use_hide_panels=False)
                        if not result or 'CANCELLED' not in result:
                            return True
                    except TypeError:
                        try:
                            result = bpy.ops.screen.screen_full_area()
                            if not result or 'CANCELLED' not in result:
                                return True
                        except FBP_DATA_IO_ERRORS:
                            pass
                    except FBP_DATA_IO_ERRORS:
                        pass
            except FBP_DATA_IO_ERRORS:
                continue
        return False

    def _schedule_full_area_restore_retry(self, window, screen, *, max_attempts=6):
        attempts = {"count": 0}
        window_key = _feedback_pointer(window)
        if not window_key:
            return False

        def _retry_restore():
            attempts["count"] += 1
            resolved = _feedback_resolve_ui_context(window_key)
            if resolved is None:
                return None
            current_window, current_screen, _area, _region = resolved
            try:
                if FBP_OT_WhatsNewGpuPopup._restore_full_area_once(
                    current_window, current_screen
                ):
                    return None
            except Exception as exc:
                fbp_warn("Could not retry temporary Full Area restore after splash", exc)
                return None
            if attempts["count"] >= int(max_attempts):
                return None
            return 0.08

        try:
            return bool(schedule_once(
                f"feedback.full_area_restore:{id(self)}",
                _retry_restore,
                first_interval=0.02,
            ))
        except Exception as exc:
            fbp_warn("Could not schedule temporary Full Area restore retry", exc)
            return False

    def _exit_temporary_full_area(self):
        if not bool(self._fullscreen_active) or bool(self._fullscreen_restoring):
            return False
        window = self._fullscreen_window or getattr(bpy.context, "window", None)
        screen = getattr(window, "screen", None) if window is not None else None
        if screen is None:
            screen = self._fullscreen_screen

        self._fullscreen_restoring = True
        self._fullscreen_active = False
        self._fullscreen_window = None
        self._fullscreen_screen = None
        try:
            restored = self._restore_full_area_once(window, screen)
            if not restored:
                self._schedule_full_area_restore_retry(window, screen)
            return bool(restored)
        finally:
            self._fullscreen_restoring = False

    def _tag_redraw(self):
        try:
            area = self._area
            if area is not None:
                area.tag_redraw()
        except FBP_DATA_ERRORS:
            pass

    def _cleanup(self):
        global _ACTIVE_GPU_POPUP
        if self._draw_handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, 'WINDOW')
            except FBP_DATA_ERRORS:
                pass
        self._draw_handler = None
        self._buttons = None
        self._hover_button = None
        self._pressed_button = None
        self._last_popup_rect = None
        self._dragging = False
        self._drag_start_mouse = None
        self._drag_start_offset = None
        self._tag_redraw()
        self._cover_texture = None
        self._cover_image = None
        self._slice_textures = None
        self._slice_images = None
        self._button_textures = None
        self._button_images = None
        self._exit_temporary_full_area()
        self._area = None
        self._region = None
        if _ACTIVE_GPU_POPUP is self:
            _ACTIVE_GPU_POPUP = None

    def _current_cover_filename(self):
        return Path(FBP_WHATS_NEW_COVER_FILENAME).name

    def _current_button_rects(self):
        return FBP_SPLASH_BUTTON_RECTS

    def _load_cover_image(self):
        expected_filename = self._current_cover_filename()
        if self._cover_image is not None and str(self._cover_loaded_filename or "") == str(expected_filename):
            return self._cover_image
        self._cover_image = None
        self._cover_texture = None
        self._cover_loaded_filename = ""
        path = self._splash_asset_path(expected_filename)
        if not path.exists() or not path.is_file():
            return None
        try:
            self._cover_image = _load_splash_image_from_disk(path)
            self._cover_loaded_filename = str(expected_filename)
            return _prepare_splash_image_for_gpu(self._cover_image)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not load GPU cover", exc)
            return None

    def _cover_texture_for_image(self, image):
        if image is None:
            return None
        if self._cover_texture is not None:
            return self._cover_texture
        try:
            import gpu
            self._cover_texture = gpu.texture.from_image(image)
            return self._cover_texture
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not create What's New GPU cover texture", exc)
            self._cover_texture = None
            return None

    def _current_cover_slices(self):
        return FBP_SPLASH_SLICE_FILES

    def _load_cover_slice_image(self, filename):
        if self._slice_images is None:
            self._slice_images = {}
        filename = str(filename or "")
        if not filename:
            return None
        cached = self._slice_images.get(filename)
        if cached is not None:
            return cached
        path = self._splash_asset_path(filename)
        if not path.exists() or not path.is_file():
            return None
        try:
            image = _load_splash_image_from_disk(path)
            self._slice_images[filename] = _prepare_splash_image_for_gpu(image)
            return self._slice_images[filename]
        except FBP_DATA_ERRORS as exc:
            fbp_warn(f"Could not load splash slice {filename}", exc)
            return None

    def _cover_slice_texture_for_filename(self, filename):
        if self._slice_textures is None:
            self._slice_textures = {}
        cached = self._slice_textures.get(filename)
        if cached is not None:
            return cached
        image = self._load_cover_slice_image(filename)
        if image is None:
            return None
        try:
            import gpu
            texture = gpu.texture.from_image(image)
            self._slice_textures[filename] = texture
            return texture
        except FBP_DATA_ERRORS as exc:
            fbp_warn(f"Could not create splash slice texture {filename}", exc)
            return None

    def _draw_cover_slices(self, popup_x, popup_y, popup_w, popup_h):
        drawn = False
        for filename, sy, sh in self._current_cover_slices():
            texture = self._cover_slice_texture_for_filename(filename)
            if texture is None:
                return False
            draw_x = float(popup_x)
            # Shared, rounded pixel edges prevent fractional gaps if this
            # compatibility fallback is used on a GPU that rejects the full
            # 903 × 1010 cover texture.
            draw_top = float(popup_y) + float(popup_h) - round(
                (float(sy) / FBP_SPLASH_ART_HEIGHT) * float(popup_h)
            )
            draw_bottom = float(popup_y) + float(popup_h) - round(
                ((float(sy) + float(sh)) / FBP_SPLASH_ART_HEIGHT)
                * float(popup_h)
            )
            draw_y = draw_bottom
            draw_w = float(popup_w)
            draw_h = draw_top - draw_bottom
            _gpu_draw_texture(texture, draw_x, draw_y, draw_w, draw_h)
            drawn = True
        return drawn

    def _draw_credit(self, blf_module, popup_x, popup_y, popup_w):
        """Draw the cover credit below the artwork, never inside the PNG."""
        text = FBP_SPLASH_CREDIT_TEXT
        font_size = int(FBP_SPLASH_CREDIT_FONT_SIZE)
        max_width = max(1.0, float(popup_w) - 16.0)
        font_id = 0
        try:
            while font_size > 10:
                blf_module.size(font_id, font_size)
                text_width, _text_height = blf_module.dimensions(font_id, text)
                if float(text_width) <= max_width:
                    break
                font_size -= 1
            blf_module.size(font_id, font_size)
            text_width, text_height = blf_module.dimensions(font_id, text)
            text_x = float(popup_x) + (float(popup_w) - float(text_width)) * 0.5
            band_bottom = float(popup_y) - float(FBP_SPLASH_CREDIT_BAND_HEIGHT)
            text_y = band_bottom + (float(FBP_SPLASH_CREDIT_BAND_HEIGHT) - float(text_height)) * 0.5
            _gpu_text(
                blf_module,
                text,
                text_x,
                text_y,
                font_size,
                (0.82, 0.82, 0.82, 1.0),
                font_id=font_id,
            )
            return True
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not draw splash cover credit", exc)
            return False

    def _cover_height_for_width(self, width):
        # The runtime package validates this exact 903 × 1010 artwork. Avoid an
        # RNA image-size read on every POST_PIXEL redraw.
        return int(round(float(width) * FBP_SPLASH_ART_HEIGHT / FBP_SPLASH_ART_WIDTH))

    def _layout_rects(self, region_width, region_height):
        available_width = max(1.0, float(region_width) - FBP_GPU_POPUP_MARGIN * 2.0)
        available_height = max(1.0, float(region_height) - FBP_GPU_POPUP_MARGIN * 2.0)
        credit_height = float(FBP_SPLASH_CREDIT_BAND_HEIGHT)
        artwork_height = max(1.0, available_height - credit_height)
        max_width_by_height = artwork_height * (FBP_SPLASH_ART_WIDTH / FBP_SPLASH_ART_HEIGHT)
        target_width = min(float(FBP_GPU_POPUP_MAX_WIDTH), available_width, max_width_by_height)
        # Shrink below the normal desktop size only when the active region requires it.
        width = int(max(1.0, target_width))
        height = self._cover_height_for_width(width)
        group_height = height + int(FBP_SPLASH_CREDIT_BAND_HEIGHT)
        x = int((region_width - width) * 0.5)
        group_y = int((region_height - group_height) * 0.5)
        offset = self._popup_offset if isinstance(self._popup_offset, tuple) else (0, 0)
        try:
            x += int(offset[0])
            group_y += int(offset[1])
        except (TypeError, ValueError, IndexError):
            pass
        x = int(clamp(
            x,
            FBP_GPU_POPUP_MARGIN,
            max(FBP_GPU_POPUP_MARGIN, region_width - width - FBP_GPU_POPUP_MARGIN),
        ))
        group_y = int(clamp(
            group_y,
            FBP_GPU_POPUP_MARGIN,
            max(FBP_GPU_POPUP_MARGIN, region_height - group_height - FBP_GPU_POPUP_MARGIN),
        ))
        y = group_y + int(FBP_SPLASH_CREDIT_BAND_HEIGHT)
        return x, y, width, height

    def _splash_asset_path(self, filename):
        return FBP_SPLASH_ASSET_DIR / str(filename or "")

    def _load_button_image(self, filename):
        if self._button_images is None:
            self._button_images = {}
        filename = str(filename or "")
        if not filename:
            return None
        cached = self._button_images.get(filename)
        if cached is not None:
            return cached
        path = self._splash_asset_path(filename)
        if not path.exists() or not path.is_file():
            return None
        try:
            image = _load_splash_image_from_disk(path)
            self._button_images[filename] = _prepare_splash_image_for_gpu(image)
            return self._button_images[filename]
        except FBP_DATA_ERRORS as exc:
            fbp_warn(f"Could not load splash button {filename}", exc)
            return None

    def _button_texture_for_filename(self, filename):
        if self._button_textures is None:
            self._button_textures = {}
        cached = self._button_textures.get(filename)
        if cached is not None:
            return cached
        image = self._load_button_image(filename)
        if image is None:
            return None
        try:
            import gpu
            texture = gpu.texture.from_image(image)
            self._button_textures[filename] = texture
            return texture
        except FBP_DATA_ERRORS as exc:
            fbp_warn(f"Could not create splash button texture {filename}", exc)
            return None

    def _button_state_name(self, name):
        name = str(name or "")
        if name == str(self._pressed_button or ""):
            return "pressed"
        if name == str(self._hover_button or ""):
            return "hover"
        return ""

    def _button_filename(self, name):
        name = str(name or "")
        state = self._button_state_name(name)
        if not state:
            return ""
        files = FBP_SPLASH_BUTTON_FILES.get(name, {})
        if state == "pressed":
            return files.get("pressed") or files.get("hover") or ""
        if state == "hover":
            return files.get("hover") or ""
        return ""

    def _button_rect_from_svg(self, popup_x, popup_y, popup_w, popup_h, svg_rect):
        sx, sy, sw, sh = (float(value) for value in svg_rect)
        x = popup_x + (sx / FBP_SPLASH_ART_WIDTH) * popup_w
        y = popup_y + ((FBP_SPLASH_ART_HEIGHT - sy - sh) / FBP_SPLASH_ART_HEIGHT) * popup_h
        w = (sw / FBP_SPLASH_ART_WIDTH) * popup_w
        h = (sh / FBP_SPLASH_ART_HEIGHT) * popup_h
        return int(round(x)), int(round(y)), int(round(w)), int(round(h))

    def _button_draw_rect_from_svg_hitbox(self, popup_x, popup_y, popup_w, popup_h, svg_rect):
        """Draw button-state PNGs inside their SVG hitbox.

        The current splash assets are small button-state images, not full-card
        overlays.  They must be placed on the hitbox coordinates supplied by
        the SVG, otherwise a hover/press state is stretched across the entire
        popup.
        """
        bx, by, bw, bh = self._button_rect_from_svg(popup_x, popup_y, popup_w, popup_h, svg_rect)
        return float(bx), float(by), float(bw), float(bh)

    def _event_region_coords(self, event):
        """Return mouse coordinates in the splash draw region.

        Temporary Full Area can leave modal events using a different active
        region than the one used by the GPU draw handler. Try Blender's local
        coordinates first, then derive coordinates from window/area/region
        positions and keep the candidate that actually hits the popup/buttons.
        """
        if event is None:
            return 0, 0
        candidates = []
        def _add(x, y):
            try:
                x = int(round(float(x))); y = int(round(float(y)))
            except (TypeError, ValueError):
                return
            pair = (x, y)
            if pair not in candidates:
                candidates.append(pair)
        _add(getattr(event, "mouse_region_x", 0), getattr(event, "mouse_region_y", 0))
        try:
            mx = int(round(float(getattr(event, "mouse_x", 0))))
            my = int(round(float(getattr(event, "mouse_y", 0))))
        except (TypeError, ValueError):
            mx = my = 0
        region = self._region
        area = self._area
        try:
            rx = int(getattr(region, "x", 0) or 0); ry = int(getattr(region, "y", 0) or 0)
        except FBP_DATA_ERRORS:
            rx = ry = 0
        try:
            ax = int(getattr(area, "x", 0) or 0); ay = int(getattr(area, "y", 0) or 0)
        except FBP_DATA_ERRORS:
            ax = ay = 0
        _add(mx - rx, my - ry)
        _add(mx - ax - rx, my - ay - ry)
        _add(mx - ax, my - ay)

        def _inside_popup(pair):
            rect = self._last_popup_rect
            if not rect:
                return False
            try:
                x, y, w, h = rect
                px, py = pair
                return x <= px <= x + w and y <= py <= y + h
            except (TypeError, ValueError):
                return False

        for pair in candidates:
            if self._button_name_at(*pair):
                return pair
        for pair in candidates:
            if _inside_popup(pair):
                return pair
        try:
            rw = int(getattr(region, "width", 0) or 0); rh = int(getattr(region, "height", 0) or 0)
        except FBP_DATA_ERRORS:
            rw = rh = 0
        for pair in candidates:
            px, py = pair
            if 0 <= px <= rw and 0 <= py <= rh:
                return pair
        return candidates[0] if candidates else (0, 0)

    def _button_name_at(self, mouse_x, mouse_y):
        try:
            mx = int(mouse_x); my = int(mouse_y)
        except (TypeError, ValueError):
            return None
        for name, rect in tuple((self._buttons or {}).items()):
            x, y, w, h = rect
            if x <= mx <= x + w and y <= my <= y + h:
                return name
        return None

    def _update_hover_from_event(self, event):
        mouse_x, mouse_y = self._event_region_coords(event)
        name = self._button_name_at(mouse_x, mouse_y)
        if name == self._hover_button:
            return False
        self._hover_button = name
        self._tag_redraw()
        return True

    def _title_drag_hit(self, mouse_x, mouse_y):
        rect = self._last_popup_rect
        if not rect:
            return False
        try:
            x, y, w, h = rect
            mx = int(mouse_x); my = int(mouse_y)
        except (TypeError, ValueError):
            return False
        title_h = max(34, int(h * 0.075))
        return x <= mx <= x + w and y + h - title_h <= my <= y + h

    def _activate_button(self, name, context):
        name = str(name or "")
        if name == "discover":
            _open_external_url(FBP_WHATS_NEW_URL)
            return {'RUNNING_MODAL'}
        if name == "bug":
            _open_external_url(FBP_SUPPORT_URL)
            self._tag_redraw()
            return {'RUNNING_MODAL'}
        if name == "tutorial":
            # Starting the tutorial is an explicit acknowledgement of this
            # splash. Persist it before teardown so Undo or mask deletion can
            # never make the same release look unseen again.
            _mark_whats_new_seen(_preferences(context))
            self._cleanup()
            _schedule_live_tutorial(delay=0.55)
            return {'FINISHED'}
        if name == "got":
            _mark_whats_new_seen(_preferences(context))
            self._cleanup()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def _draw_callback(self):
        blend_enabled = False
        try:
            import gpu
            blf = _fbp_import_blf(gpu)
            if blf is None:
                return
            region = getattr(bpy.context, "region", None)
            region_width = int(getattr(region, "width", 0) or getattr(self._region, "width", 0) or 0)
            region_height = int(getattr(region, "height", 0) or getattr(self._region, "height", 0) or 0)
            if region_width <= 0 or region_height <= 0:
                return
            shader = _gpu_uniform_shader()
            if shader is None:
                return
            try:
                gpu.state.depth_test_set('NONE')
            except FBP_DATA_ERRORS:
                pass
            try:
                gpu.state.depth_mask_set(False)
            except FBP_DATA_ERRORS:
                pass
            gpu.state.blend_set('ALPHA')
            blend_enabled = True
            # Darken the Blender viewport behind the floating splash with normal
            # straight-alpha blending.  The splash artwork itself switches to
            # premultiplied alpha immediately after this overlay.
            _gpu_rect(shader, 0, 0, region_width, region_height, (0.0, 0.0, 0.0, 0.46))

            try:
                gpu.state.blend_set('ALPHA_PREMULT')
            except FBP_DATA_ERRORS:
                gpu.state.blend_set('ALPHA')

            x, y, width, height = self._layout_rects(region_width, region_height)
            self._last_popup_rect = (x, y, width, height)

            # Draw the artwork as one texture so resampling cannot expose
            # horizontal seams between slices. The slices remain a fallback for
            # unusually constrained GPU backends.
            drew_cover = False
            cover = self._load_cover_image()
            if cover is not None:
                texture = self._cover_texture_for_image(cover)
                if texture is not None:
                    _gpu_draw_texture(texture, x, y, width, height)
                    drew_cover = True
            if not drew_cover:
                drew_cover = self._draw_cover_slices(x, y, width, height)
            if not drew_cover:
                _gpu_rounded_rect(shader, x, y, width, height, FBP_GPU_POPUP_RADIUS, (0.075, 0.075, 0.075, 0.985), segments=10)
                _gpu_text(blf, "Frame By Plane", x + 48, y + height - 120, 34, (1.0, 1.0, 1.0, 1.0))

            active_rects = self._current_button_rects()
            buttons = {}
            for name, svg_rect in active_rects.items():
                click_rect = self._button_rect_from_svg(x, y, width, height, svg_rect)
                buttons[name] = click_rect
            self._buttons = buttons

            for name, svg_rect in active_rects.items():
                filename = self._button_filename(name)
                if not filename:
                    continue
                image = self._load_button_image(filename)
                texture = self._button_texture_for_filename(filename)
                if image is not None and texture is not None:
                    bx, by, bw, bh = self._button_draw_rect_from_svg_hitbox(x, y, width, height, svg_rect)
                    _gpu_draw_texture(texture, bx, by, bw, bh)

            self._draw_credit(blf, x, y, width)

        except Exception as exc:
            fbp_warn("Could not draw Frame By Plane GPU What's New overlay", exc)
        finally:
            if blend_enabled:
                try:
                    import gpu
                    gpu.state.blend_set('NONE')
                    try:
                        gpu.state.depth_mask_set(True)
                    except FBP_DATA_ERRORS:
                        pass
                except FBP_DATA_ERRORS:
                    pass

    def invoke(self, context, event):
        global _ACTIVE_GPU_POPUP
        if _ACTIVE_GPU_POPUP is not None and _ACTIVE_GPU_POPUP is not self:
            try:
                _ACTIVE_GPU_POPUP._cleanup()
            except FBP_DATA_ERRORS:
                _ACTIVE_GPU_POPUP = None
        if bool(getattr(self, "start_tutorial", False)):
            _mark_whats_new_seen(_preferences(context))
            return bpy.ops.fbp.live_tutorial('INVOKE_DEFAULT')
        prefs = _preferences(context)
        if prefs is None:
            return {'CANCELLED'}
        if not bool(self.force) and not _whats_new_is_pending(prefs):
            return {'CANCELLED'}
        view_context = _feedback_view3d_context(context)
        if view_context is None:
            return {'CANCELLED'}
        _window, _screen, area, region = view_context
        self._cover_loaded_filename = ""
        self._fullscreen_active = False
        self._fullscreen_restoring = False
        self._fullscreen_window = None
        self._fullscreen_screen = None

        # Enter a temporary Full Area before registering the GPU overlay. This
        # gives the splash one large target region instead of one draw per split
        # viewport, and makes it feel centred over Blender rather than over a
        # small editor cell.
        self._enter_temporary_full_area(context, _window, _screen, area, region)
        refreshed = _feedback_view3d_context(context)
        if refreshed is not None:
            _window, _screen, area, region = refreshed
        self._area = area
        self._region = region
        try:
            self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_callback,
                (),
                'WINDOW',
                'POST_PIXEL',
            )
            context.window_manager.modal_handler_add(self)
            _ACTIVE_GPU_POPUP = self
            self._tag_redraw()
            return {'RUNNING_MODAL'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not start GPU What's New overlay", exc)
            self._cleanup()
            return {'CANCELLED'}

    def modal(self, context, event):
        event_type = str(getattr(event, "type", "") or "")
        event_value = str(getattr(event, "value", "") or "")
        if event_type in {'ESC'}:
            _mark_whats_new_seen(_preferences(context))
            self._cleanup()
            return {'CANCELLED'}
        if event_type in {'RET', 'NUMPAD_ENTER', 'SPACE'} and event_value in {'PRESS', ''}:
            _mark_whats_new_seen(_preferences(context))
            self._cleanup()
            return {'FINISHED'}
        if event_type == 'LEFTMOUSE' and event_value == 'PRESS':
            mouse_x, mouse_y = self._event_region_coords(event)
            name = self._button_name_at(mouse_x, mouse_y)
            if name:
                self._pressed_button = name
                self._hover_button = name
                self._tag_redraw()
                return {'RUNNING_MODAL'}
            if self._title_drag_hit(mouse_x, mouse_y):
                self._dragging = True
                self._drag_start_mouse = (int(mouse_x), int(mouse_y))
                self._drag_start_offset = self._popup_offset if isinstance(self._popup_offset, tuple) else (0, 0)
                return {'RUNNING_MODAL'}
        if event_type == 'LEFTMOUSE' and event_value == 'RELEASE':
            if self._dragging:
                self._dragging = False
                self._drag_start_mouse = None
                self._drag_start_offset = None
                return {'RUNNING_MODAL'}
            pressed = self._pressed_button
            self._pressed_button = None
            self._tag_redraw()
            if pressed:
                mouse_x, mouse_y = self._event_region_coords(event)
                name = self._button_name_at(mouse_x, mouse_y)
                if name == pressed:
                    return self._activate_button(name, context)
            return {'RUNNING_MODAL'}
        if event_type == 'MOUSEMOVE':
            if self._dragging and self._drag_start_mouse is not None:
                try:
                    mx, my = self._event_region_coords(event)
                    sx, sy = self._drag_start_mouse
                    ox, oy = self._drag_start_offset if isinstance(self._drag_start_offset, tuple) else (0, 0)
                    self._popup_offset = (int(ox) + mx - sx, int(oy) + my - sy)
                    self._tag_redraw()
                except (TypeError, ValueError):
                    pass
            else:
                self._update_hover_from_event(event)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        _mark_whats_new_seen(_preferences(context))
        self._cleanup()


class FBP_OT_WhatsNewPrompt(Operator):
    bl_idname = "fbp.whats_new_prompt"
    bl_label = f"Frame By Plane {FBP_PUBLIC_RELEASE} — What’s New"
    bl_description = (
        "See the current Frame By Plane improvements"
    )

    force: BoolProperty(
        name="Show Again",
        description="Open the current release notes even if this version was already viewed",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    centered_invoke: BoolProperty(description='Toggle this option for the current release or support popup. Disabled keeps the data available but prevents this behavior from being applied.', 
        name="Centred Invocation",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    start_tutorial: BoolProperty(
        name="Open Tutorial",
        description="Open the interactive Frame By Plane Live Tutorial instead of the release splash",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    def invoke(self, context, event):
        if bool(getattr(self, "start_tutorial", False)):
            _mark_whats_new_seen(_preferences(context))
            return bpy.ops.fbp.live_tutorial('INVOKE_DEFAULT')
        prefs = _preferences(context)
        if prefs is None:
            return {'CANCELLED'}
        if not bool(self.force) and not _whats_new_is_pending(prefs):
            return {'CANCELLED'}
        # Preferences must use the native dialog directly. Re-invoking through a
        # synthetic View3D context could finish the Preferences button operator
        # without ever presenting the popup on some multi-area layouts.
        native_preferences = str(getattr(getattr(context, 'area', None), 'type', '') or '') == 'PREFERENCES'

        if not native_preferences and not bool(self.centered_invoke):
            force = bool(self.force)
            start_tutorial = bool(getattr(self, "start_tutorial", False))
            if _defer_centered_feedback_invoke(
                context,
                event,
                task_name="fbp_centered_whats_new_prompt",
                callback=lambda: bpy.ops.fbp.whats_new_prompt(
                    'INVOKE_DEFAULT',
                    force=force,
                    start_tutorial=start_tutorial,
                    centered_invoke=True,
                ),
                popup_width=FBP_WHATS_NEW_DIALOG_WIDTH,
                popup_height=FBP_WHATS_NEW_DIALOG_HEIGHT,
            ):
                return {'FINISHED'}

        # Preferred path outside Preferences: a GPU overlay can draw the 16:9
        # cover as a real horizontal texture strip. Preferences always use the
        # native dialog so the click has an immediate, deterministic result.
        view_context = None if native_preferences else _feedback_view3d_context(context)
        if view_context is not None:
            window, screen, area, region = view_context
            try:
                with bpy.context.temp_override(**_feedback_override(window, screen, area, region)):
                    result = bpy.ops.fbp.whats_new_gpu_popup(
                        'INVOKE_DEFAULT',
                        force=bool(self.force),
                        start_tutorial=bool(getattr(self, "start_tutorial", False)),
                    )
                if result and 'CANCELLED' not in result:
                    return result
            except FBP_DATA_ERRORS as exc:
                fbp_warn("GPU What's New overlay unavailable; using native dialog", exc)

        wm = context.window_manager
        try:
            result = wm.invoke_props_dialog(
                self,
                width=FBP_WHATS_NEW_DIALOG_WIDTH,
                title=self.bl_label,
                confirm_text="Got It",
                cancel_default=False,
            )
        except TypeError:
            result = wm.invoke_props_dialog(self, width=FBP_WHATS_NEW_DIALOG_WIDTH)
        # Mark the release as seen only from execute()/cancel(), after Blender
        # has actually presented and dismissed the modal dialog. RUNNING_MODAL
        # alone does not prove that a popup became visible during extension
        # reload inside Preferences.
        return result

    def execute(self, context):
        _mark_whats_new_seen(_preferences(context))
        _release_whats_new_cover_preview()
        return {'FINISHED'}


    def cancel(self, context):
        # Any explicit dismissal counts as viewed. Otherwise Blender reloads,
        # file-load handlers or extension re-enables can schedule the same
        # startup popup again, which feels like a first-run bug.
        _mark_whats_new_seen(_preferences(context))
        _release_whats_new_cover_preview()

    @staticmethod
    def _draw_cards(layout, items, *, columns=2):
        grid = layout.grid_flow(
            row_major=True,
            columns=columns,
            even_columns=True,
            even_rows=False,
            align=False,
        )
        wrap_width = 34 if int(columns or 1) > 1 else 60
        for title, description, icon_key in items:
            card = grid.column(align=False)
            title_row = card.row(align=False)
            title_row.scale_y = 1.08
            title_row.label(text=title, icon=fbp_icon(icon_key))
            for line_text in textwrap.wrap(str(description), width=wrap_width) or (str(description),):
                detail = card.row(align=False)
                detail.enabled = False
                detail.label(text=line_text)
            card.separator(factor=0.25)

    @staticmethod
    def _draw_bullets(layout, items, *, icon_key='DOT'):
        col = layout.column(align=False)
        for text in items:
            row = col.row(align=False)
            row.label(text=str(text), icon=fbp_icon(icon_key))

    def draw(self, context):
        layout = configure_layout(self.layout)

        cover_icon = _whats_new_cover_icon_id()
        if cover_icon:
            cover_row = layout.row(align=True)
            cover_row.alignment = 'CENTER'
            cover_row.template_icon(icon_value=cover_icon, scale=10.0)
            credit_row = layout.row(align=False)
            credit_row.alignment = 'CENTER'
            credit_row.scale_y = 1.08
            credit_row.enabled = False
            credit_row.label(text=FBP_SPLASH_CREDIT_TEXT)
            layout.separator(factor=0.05)

        header = layout.column(align=False)
        title_row = header.row(align=False)
        title_row.alignment = 'CENTER'
        title_row.scale_y = 1.08
        title_row.label(text=f"Frame By Plane {FBP_PUBLIC_RELEASE}", icon=fbp_icon('PRESET'))

        layout.separator(factor=0.20)
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
        feedback = layout.box()
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

        note = layout.row(align=False)
        note.enabled = False
        note.label(
            text="Shown once per installed update. No telemetry or project data is collected.",
            icon=fbp_icon('LOCKED'),
        )


class FBP_OT_TestWhatsNewCover(Operator):
    bl_idname = "fbp.test_whats_new_cover"
    bl_label = "Test What's New Cover"
    bl_description = "Check whether the remaining splash background and button PNG assets can be loaded by the What’s New popup"

    def execute(self, context):
        _release_whats_new_cover_preview()
        splash_dir = FBP_SPLASH_ASSET_DIR
        missing = [
            filename for filename in _configured_splash_asset_filenames()
            if not (splash_dir / filename).exists()
        ]
        if missing:
            self.report({'ERROR'}, "Missing splash assets: " + ", ".join(missing))
            return {'CANCELLED'}
        layout_errors = list(_splash_layout_errors())
        try:
            cover = _load_splash_image_from_disk(splash_dir / Path(FBP_WHATS_NEW_COVER_FILENAME).name)
            cover_size = tuple(int(value) for value in getattr(cover, "size", (0, 0)))
            if cover_size != (int(FBP_SPLASH_ART_WIDTH), int(FBP_SPLASH_ART_HEIGHT)):
                layout_errors.append(f"background is {cover_size[0]} × {cover_size[1]}, expected 903 × 1010")
            for filename, _y, expected_height in FBP_SPLASH_SLICE_FILES:
                image = _load_splash_image_from_disk(splash_dir / filename)
                actual_size = tuple(int(value) for value in getattr(image, "size", (0, 0)))
                if actual_size != (int(FBP_SPLASH_ART_WIDTH), int(expected_height)):
                    layout_errors.append(
                        f"{filename} is {actual_size[0]} × {actual_size[1]}, expected {int(FBP_SPLASH_ART_WIDTH)} × {int(expected_height)}"
                    )
            for name, expected_size in FBP_SPLASH_BUTTON_SIZES.items():
                for filename in FBP_SPLASH_BUTTON_FILES.get(name, {}).values():
                    image = _load_splash_image_from_disk(splash_dir / filename)
                    actual_size = tuple(int(value) for value in getattr(image, "size", (0, 0)))
                    if actual_size != expected_size:
                        layout_errors.append(
                            f"{filename} is {actual_size[0]} × {actual_size[1]}, expected {expected_size[0]} × {expected_size[1]}"
                        )
        except FBP_DATA_ERRORS as exc:
            layout_errors.append(f"could not validate splash dimensions: {exc}")
        if layout_errors:
            self.report({'ERROR'}, "Splash layout error: " + "; ".join(layout_errors))
            return {'CANCELLED'}
        icon_id = _whats_new_cover_icon_id()
        if not icon_id:
            self.report({'ERROR'}, "Splash background exists but Blender could not load it as a preview")
            return {'CANCELLED'}
        self.report({'INFO'}, "Splash OK: background, button assets and native fallback preview are available")
        return {'FINISHED'}


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


class FBP_OT_OpenBaseTutorial(Operator):
    bl_idname = "fbp.open_base_tutorial"
    bl_label = "Tutorial"
    bl_description = "Open the interactive Frame By Plane Live Tutorial"

    def invoke(self, context, event):
        del event
        return bpy.ops.fbp.live_tutorial('INVOKE_DEFAULT')

    def execute(self, context):
        return bpy.ops.fbp.live_tutorial('INVOKE_DEFAULT')


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

        return {'FINISHED'}


class FBP_OT_OpenSupportPage(Operator):
    bl_idname = "fbp.open_support_page"
    bl_label = "Report a Bug"
    bl_description = (
        "Open the public Frame By Plane GitHub issue page. Nothing is submitted "
        "automatically and you can review the report before posting"
    )

    def execute(self, context):
        if not _open_external_url(FBP_SUPPORT_URL):
            self.report({'WARNING'}, "Could not open the bug report page")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    FBP_OT_WhatsNewGpuPopup,
    FBP_OT_WhatsNewPrompt,
    FBP_OT_OpenBaseTutorial,
    FBP_OT_TestWhatsNewCover,
    FBP_OT_OpenWhatsNewPage,
    FBP_OT_OpenReviewPage,
    FBP_OT_OpenSupportPage,
)


def quiesce_feedback_runtime():
    """Retire the active GPU popup before Blender unregisters its RNA class."""
    global _ACTIVE_GPU_POPUP
    active = _ACTIVE_GPU_POPUP
    _ACTIVE_GPU_POPUP = None
    if active is None:
        return False
    try:
        active._cleanup()
        return True
    except FBP_DATA_ERRORS:
        return False


def register():
    if bool(getattr(bpy.app, "background", False)):
        return
    quiesce_feedback_runtime()
    register_classes(classes)
    fbp_schedule_whats_new_prompt(delay=0.80)


def unregister():
    global _FBP_GPU_UNIFORM_SHADER, _FBP_GPU_IMAGE_SHADER
    quiesce_feedback_runtime()
    _release_whats_new_cover_preview()
    _FBP_GPU_UNIFORM_SHADER = None
    _FBP_GPU_IMAGE_SHADER = None
    unregister_classes(classes)
