"""Optional chord played when a render finishes successfully.

The sound is synthesised with Blender's bundled ``aud`` module, so no audio
file ships with the extension. It plays in the interactive Blender that owns
the render: after a normal render (``render_complete``) and when the Frame By
Plane background render reports success. Background processes never play it,
so a background render child does not chime a second time.
"""

from __future__ import annotations

from contextlib import contextmanager

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from .registration import register_classes, unregister_classes
from .runtime import fbp_warn

# A bright major chord (C major with an added 9th on top), played as a quick
# upward roll so it reads as "done, all good" rather than as an alert.
_CHORD_HZ = (523.25, 659.25, 783.99, 1046.50, 1174.66)
_ROLL_SECONDS = 0.055
_NOTE_SECONDS = 1.35
_RATE = 48000

_FBP_ACTIVE_HANDLES: list = []
_FBP_SUPPRESS_DEPTH = [0]


@contextmanager
def fbp_render_sound_suppressed():
    """Silence the chord for internal renders (effect bakes render per frame)."""
    _FBP_SUPPRESS_DEPTH[0] += 1
    try:
        yield
    finally:
        _FBP_SUPPRESS_DEPTH[0] = max(0, _FBP_SUPPRESS_DEPTH[0] - 1)


def _chord_sound():
    import aud

    mix = None
    count = len(_CHORD_HZ)
    for index, frequency in enumerate(_CHORD_HZ):
        # Sine plus a soft octave partial gives a gentle bell-like tone.
        tone = aud.Sound.sine(frequency, _RATE).mix(
            aud.Sound.sine(frequency * 2.0, _RATE).volume(0.18)
        )
        note = (
            tone.limit(0.0, _NOTE_SECONDS)
            .fadein(0.0, 0.012)
            .fadeout(0.18, _NOTE_SECONDS - 0.18)
            .volume(0.8 / count)
            .delay(index * _ROLL_SECONDS)
        )
        mix = note if mix is None else mix.mix(note)
    return mix


def fbp_play_render_finished_sound(*, force=False) -> bool:
    """Play the chord when the preference is on (or ``force``); never raises."""
    if bool(getattr(bpy.app, "background", False)):
        return False
    if not force:
        try:
            from .interface_preferences import fbp_get_addon_preferences

            prefs = fbp_get_addon_preferences(bpy.context)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            prefs = None
        if not bool(getattr(prefs, "render_finish_sound", False)):
            return False
    try:
        import aud

        handle = aud.Device().play(_chord_sound())
    except Exception as exc:  # aud raises its own error types per backend
        fbp_warn("Could not play the render-finished sound", exc)
        return False
    # Keep the handle referenced until the next chord so playback is not cut.
    _FBP_ACTIVE_HANDLES[:] = [handle]
    return True


@persistent
def fbp_render_finished_sound_complete(_scene, _depsgraph=None):
    if _FBP_SUPPRESS_DEPTH[0]:
        return
    fbp_play_render_finished_sound()


class FBP_OT_PreviewRenderFinishedSound(Operator):
    bl_idname = "fbp.preview_render_finished_sound"
    bl_label = "Preview Sound"
    bl_description = "Play the sound used when a render finishes"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        if not fbp_play_render_finished_sound(force=True):
            self.report({'WARNING'}, "No audio device is available to play the sound")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (FBP_OT_PreviewRenderFinishedSound,)


def _remove_handler():
    handlers = bpy.app.handlers.render_complete
    for callback in tuple(handlers):
        if getattr(callback, "__name__", "") == fbp_render_finished_sound_complete.__name__ and str(
            getattr(callback, "__module__", "")
        ).endswith("render_finish_sound"):
            handlers.remove(callback)


def register():
    if bool(getattr(bpy.app, "background", False)):
        return
    register_classes(classes)
    _remove_handler()
    bpy.app.handlers.render_complete.append(fbp_render_finished_sound_complete)


def unregister():
    if bool(getattr(bpy.app, "background", False)):
        return
    _remove_handler()
    _FBP_ACTIVE_HANDLES.clear()
    unregister_classes(classes)
