"""Native Blender output-path synchronization and render naming utilities."""

from __future__ import annotations

import os
import re
import shutil
from contextlib import contextmanager

import bpy

from .runtime import FBP_DATA_ERRORS, fbp_obj_runtime_key, fbp_warn


_INVALID_COMPONENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')
_HASH_RUN_RE = re.compile(r"#+")
_TEST_FOLDER_RE = re.compile(r"^TEST\s+(\d+)(?:\s+-\s+(.*))?$", re.IGNORECASE)
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_SEPARATOR_MAP = {
    'DASH': ' - ',
    'UNDERSCORE': '_',
    'HYPHEN': '-',
    'SPACE': ' ',
    'NONE': '',
}

_FBP_RENDER_PATH_SYNC_GUARD: set[object] = set()
_FBP_NATIVE_PATH_CACHE: dict[object, str] = {}


def _scene_key(scene):
    try:
        key = fbp_obj_runtime_key(scene)
        if key is not None:
            return key
    except FBP_DATA_ERRORS:
        pass
    return ("NAME", str(getattr(scene, "name", "") or ""), id(scene))


@contextmanager
def _sync_guard(scene):
    key = _scene_key(scene)
    _FBP_RENDER_PATH_SYNC_GUARD.add(key)
    try:
        yield
    finally:
        _FBP_RENDER_PATH_SYNC_GUARD.discard(key)


def fbp_render_path_sync_guarded(scene) -> bool:
    return bool(scene and _scene_key(scene) in _FBP_RENDER_PATH_SYNC_GUARD)


def fbp_clear_render_output_cache() -> None:
    _FBP_NATIVE_PATH_CACHE.clear()
    _FBP_RENDER_PATH_SYNC_GUARD.clear()


def fbp_sanitize_render_component(value, fallback="") -> str:
    text = _INVALID_COMPONENT_RE.sub('_', str(value or '').strip())
    text = re.sub(r"\s+", " ", text).strip(' ._-')
    if text.upper() in _WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    return text or str(fallback or '')


def _document_name() -> str:
    filepath = str(getattr(bpy.data, "filepath", "") or "")
    stem = os.path.splitext(os.path.basename(filepath))[0]
    return fbp_sanitize_render_component(stem, "Untitled")


def _separator(scene) -> str:
    return _SEPARATOR_MAP.get(
        str(getattr(scene, "fbp_render_separator", "UNDERSCORE") or "UNDERSCORE"),
        '_',
    )


def _join_components(components, separator: str) -> str:
    clean = [fbp_sanitize_render_component(value) for value in components]
    clean = [value for value in clean if value]
    return separator.join(clean)


def fbp_render_advanced_enabled(scene) -> bool:
    """True when Advanced Render drives Blender's native Output path."""
    return bool(scene is not None and getattr(scene, "fbp_render_advanced", False))


_TOKEN_MODES = {'NONE', 'LETTER', 'NUMBER', 'LETTER_NUMBER'}


def fbp_render_section_token(scene, section: str) -> str:
    """Return the token mode of the ``'PREFIX'`` or ``'SUFFIX'`` section.

    Files saved before per-section tokens stored one token with a position
    (before Prefix / after Suffix); it is read as the token of that section
    until the section gets its own value.
    """
    prop = "fbp_render_prefix_token" if section == 'PREFIX' else "fbp_render_suffix_token"
    mode = str(getattr(scene, prop, "NONE") or "NONE")
    if mode != 'NONE':
        return mode if mode in _TOKEN_MODES else 'NONE'
    legacy = str(getattr(scene, "fbp_render_token_mode", "NONE") or "NONE")
    if legacy == 'NONE' or legacy not in _TOKEN_MODES:
        return 'NONE'
    position = str(getattr(scene, "fbp_render_token_position", "BEFORE") or "BEFORE")
    return legacy if (position == 'BEFORE') == (section == 'PREFIX') else 'NONE'


def fbp_render_token_text(scene, mode, *, letter=None, number=None) -> str:
    """Return the letter/number token text, e.g. ``A``, ``01`` or ``A01``."""
    parts = []
    if mode in {'LETTER', 'LETTER_NUMBER'}:
        value = str(getattr(scene, "fbp_render_letter", "") or "") if letter is None else letter
        parts.append(fbp_sanitize_render_component(value))
    if mode in {'NUMBER', 'LETTER_NUMBER'}:
        digits = max(1, min(8, int(getattr(scene, "fbp_render_number_digits", 1) or 1)))
        value = int(getattr(scene, "fbp_render_number", 1) or 0) if number is None else int(number)
        parts.append(str(max(0, value)).zfill(digits))
    return "".join(parts)


def _section_text(scene, section: str) -> str:
    """Prefix or Suffix text with its token appended (``Shot A1``)."""
    text_prop = "fbp_render_prefix" if section == 'PREFIX' else "fbp_render_suffix"
    use_prop = "fbp_render_use_prefix" if section == 'PREFIX' else "fbp_render_use_suffix"
    if not bool(getattr(scene, use_prop, True)):
        return ""
    text = fbp_sanitize_render_component(getattr(scene, text_prop, ""))
    token = fbp_render_token_text(scene, fbp_render_section_token(scene, section))
    return " ".join(value for value in (text, token) if value)


def fbp_render_filename_pattern(scene) -> str:
    """Return the Camera-Raw-style filename pattern used by Blender."""
    render = getattr(scene, "render", None)
    is_movie = bool(getattr(render, "is_movie_format", False)) if render else False

    separator = _separator(scene)
    # Empty is an intentional live fallback to the .blend project name.  This
    # keeps new and renamed projects synchronized without writing from UI draw.
    base_name = ""
    if bool(getattr(scene, "fbp_render_use_name", True)):
        base_name = str(getattr(scene, "fbp_render_custom_name", "") or "").strip()
        if not base_name:
            base_name = _document_name()

    components = [
        _section_text(scene, 'PREFIX'),
        base_name,
        _section_text(scene, 'SUFFIX'),
    ]
    leading = _join_components(components, separator)
    if not leading:
        leading = "frame"

    if is_movie:
        return leading or "render"

    frame_digits = max(1, min(8, int(getattr(scene, "fbp_render_frame_digits", 4) or 4)))
    frame_token = '#' * frame_digits
    return _join_components((leading, frame_token), separator)


def fbp_render_root_directory(scene) -> str:
    builder_mode = str(
        getattr(scene, "fbp_render_folder_builder_mode", "GENERATE") or "GENERATE"
    )
    if builder_mode == 'SELECT':
        configured = str(getattr(scene, "fbp_render_output_dir", "") or "").strip()
        if configured:
            return os.path.normpath(bpy.path.abspath(configured))

    project_root = str(getattr(scene, "fbp_project_path", "") or "").strip()
    if project_root:
        return os.path.normpath(bpy.path.abspath(project_root))

    if builder_mode == 'SELECT':
        native = str(getattr(getattr(scene, "render", None), "filepath", "") or "")
        if native:
            absolute = bpy.path.abspath(native)
            if native.endswith(("/", "\\")):
                return os.path.normpath(absolute)
            dirname = os.path.dirname(os.path.normpath(absolute))
            if dirname:
                return dirname

    blend_path = str(getattr(bpy.data, "filepath", "") or "")
    base = os.path.dirname(blend_path) if blend_path else os.path.expanduser("~")
    return os.path.normpath(os.path.join(base, "FBP_Render_Frames"))


def fbp_render_folder_name(scene, *, test_number=None) -> str:
    del test_number
    mode = str(
        getattr(scene, "fbp_render_folder_builder_mode", "GENERATE") or "GENERATE"
    )
    if mode == 'SELECT':
        return ""
    prefix = getattr(scene, "fbp_render_folder_prefix", "")
    name = str(getattr(scene, "fbp_render_folder_name", "") or "").strip()
    name = name or _document_name()
    tag = str(getattr(scene, "fbp_render_folder_tag", "TEST") or "TEST")
    suffix = getattr(scene, "fbp_render_folder_builder_suffix", "")
    tag_value = "" if tag == 'NONE' else tag
    return _join_components((prefix, name, tag_value, suffix), " ") or "Render"


def fbp_find_ffmpeg_executable(scene=None) -> str:
    """Return a configured or auto-detected FFmpeg executable."""
    configured = str(
        getattr(scene, "fbp_render_ffmpeg_executable", "") or ""
    ).strip() if scene is not None else ""
    if configured:
        candidate = os.path.normpath(bpy.path.abspath(configured))
        if os.path.isfile(candidate):
            return candidate
    detected = shutil.which("ffmpeg")
    if detected and os.path.isfile(detected):
        return os.path.normpath(detected)
    env = os.environ
    candidates = (
        os.path.join(env.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        os.path.join(env.get("ProgramFiles", ""), "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(env.get("ChocolateyInstall", ""), "bin", "ffmpeg.exe"),
    )
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.normpath(candidate)
    return ""


def fbp_next_render_test_number(scene, root_dir=None) -> int:
    root = os.path.normpath(root_dir or fbp_render_root_directory(scene))
    highest = 0
    try:
        names = os.listdir(root) if os.path.isdir(root) else ()
    except OSError:
        names = ()
    for name in names:
        try:
            if not os.path.isdir(os.path.join(root, name)):
                continue
        except OSError:
            continue
        match = _TEST_FOLDER_RE.match(str(name).strip())
        if match:
            try:
                highest = max(highest, int(match.group(1)))
            except (TypeError, ValueError):
                pass
    return highest + 1


def fbp_resolve_render_output(
    scene,
    *,
    advance_test=False,
    create=False,
    update_native=False,
):
    """Resolve output directory and native Blender filepath for one render job."""
    root = fbp_render_root_directory(scene)
    folder_mode = str(
        getattr(scene, "fbp_render_folder_builder_mode", "GENERATE") or "GENERATE"
    )
    test_number = int(getattr(scene, "fbp_render_test_number", 1) or 1)
    if (
        advance_test
        and folder_mode == 'TEST'
        and bool(getattr(scene, "fbp_render_auto_increment_test", True))
    ):
        test_number = fbp_next_render_test_number(scene, root)
        with _sync_guard(scene):
            try:
                if int(getattr(scene, "fbp_render_test_number", 1) or 1) != test_number:
                    scene.fbp_render_test_number = test_number
            except FBP_DATA_ERRORS:
                pass

    folder_name = fbp_render_folder_name(scene, test_number=test_number)
    output_dir = os.path.normpath(os.path.join(root, folder_name)) if folder_name else root
    pattern = fbp_render_filename_pattern(scene)
    filepath = os.path.normpath(os.path.join(output_dir, pattern))
    auto_video = bool(
        str(getattr(scene, "fbp_render_output_kind", "IMAGES") or "IMAGES") == 'VIDEO'
        and not bool(getattr(getattr(scene, "render", None), "is_movie_format", False))
    )
    static_name = fbp_render_static_prefix(scene).rstrip(" ._-") or "render"
    video_path = os.path.normpath(os.path.join(output_dir, static_name + ".mp4"))

    if create:
        os.makedirs(output_dir, exist_ok=True)
    if update_native:
        fbp_sync_native_render_path(scene, filepath=filepath)

    return {
        "root_dir": root,
        "folder_name": folder_name,
        "output_dir": output_dir,
        "pattern": pattern,
        "filepath": filepath,
        "test_number": test_number,
        "auto_video": auto_video,
        "video_path": video_path,
        "ffmpeg_executable": fbp_find_ffmpeg_executable(scene) if auto_video else "",
    }


def _fbp_native_output_representation(scene, absolute_path: str) -> str:
    """Preserve Blender's ``//`` project-relative convention when requested."""
    builder_mode = str(
        getattr(scene, "fbp_render_folder_builder_mode", "GENERATE") or "GENERATE"
    )
    configured = str(
        getattr(
            scene,
            "fbp_render_output_dir" if builder_mode == 'SELECT' else "fbp_project_path",
            "",
        ) or ""
    ).strip()
    if configured.startswith("//") and str(getattr(bpy.data, "filepath", "") or ""):
        try:
            return str(bpy.path.relpath(absolute_path))
        except FBP_DATA_ERRORS:
            pass
    return str(absolute_path)


def fbp_sync_native_render_path(scene, *, filepath=None) -> bool:
    """Push the FBP builder path to ``Scene.render.filepath`` without loops."""
    if not fbp_render_advanced_enabled(scene) or fbp_render_path_sync_guarded(scene):
        return False
    try:
        render = scene.render
    except FBP_DATA_ERRORS:
        return False
    try:
        absolute_target = str(filepath or fbp_resolve_render_output(scene)["filepath"])
        target = _fbp_native_output_representation(scene, absolute_target)
        current = str(getattr(render, "filepath", "") or "")
        key = _scene_key(scene)
        extension_changed = bool(
            hasattr(render, "use_file_extension") and not bool(render.use_file_extension)
        )
        if current and os.path.normcase(os.path.normpath(bpy.path.abspath(current))) == os.path.normcase(os.path.normpath(absolute_target)):
            if extension_changed:
                with _sync_guard(scene):
                    render.use_file_extension = True
            _FBP_NATIVE_PATH_CACHE[key] = current
            return extension_changed
        with _sync_guard(scene):
            if hasattr(render, "use_file_extension") and not bool(render.use_file_extension):
                render.use_file_extension = True
            render.filepath = target
        _FBP_NATIVE_PATH_CACHE[key] = str(getattr(render, "filepath", target) or target)
        return True
    except (AttributeError, OSError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not synchronize Frame By Plane output to Blender", exc)
        return False


def fbp_sync_render_output_from_native(scene, *, force=False) -> bool:
    """Read an externally edited native path into the single FBP builder."""
    if not fbp_render_advanced_enabled(scene) or fbp_render_path_sync_guarded(scene):
        return False
    try:
        raw_path = str(getattr(scene.render, "filepath", "") or "")
    except FBP_DATA_ERRORS:
        return False
    key = _scene_key(scene)
    if not force and _FBP_NATIVE_PATH_CACHE.get(key) == raw_path:
        return False
    # An empty native path has no destination or naming information to import.
    # Keep the FBP builder authoritative and initialize Blender from it.
    if not raw_path:
        _FBP_NATIVE_PATH_CACHE.pop(key, None)
        return fbp_sync_native_render_path(scene)

    # A saved Generate Folder project already stores the exact native path that
    # the builder produced. Loading that file must not reinterpret the generated
    # subfolder as a manually selected folder.
    if not force:
        try:
            builder_path = str(fbp_resolve_render_output(scene)["filepath"] or "")
            if (
                builder_path
                and os.path.normcase(os.path.normpath(bpy.path.abspath(raw_path)))
                == os.path.normcase(os.path.normpath(builder_path))
            ):
                _FBP_NATIVE_PATH_CACHE[key] = raw_path
                return False
        except (AttributeError, OSError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    try:
        absolute = bpy.path.abspath(raw_path)
        directory_only = bool(raw_path.endswith(("/", "\\")))
        normalized = os.path.normpath(absolute)
        output_dir = normalized if directory_only else os.path.dirname(normalized)
        pattern = "" if directory_only else os.path.basename(normalized)
        stored_output_dir = output_dir
        if raw_path.startswith("//") and str(getattr(bpy.data, "filepath", "") or ""):
            try:
                stored_output_dir = str(bpy.path.relpath(output_dir))
            except FBP_DATA_ERRORS:
                pass

        # Convert the native basename into a clean Name value. Frame hashes and
        # the current extension are structural and therefore not copied into the
        # user-editable text box.
        stem = os.path.splitext(pattern)[0]
        stem = _HASH_RUN_RE.sub("", stem).strip(" ._-")
        imported_name = fbp_sanitize_render_component(stem)
        with _sync_guard(scene):
            scene.fbp_render_folder_builder_mode = 'SELECT'
            scene.fbp_render_output_dir = stored_output_dir
            scene.fbp_render_filename_mode = 'COMPOSE'
            scene.fbp_render_name_source = 'CUSTOM'
            if imported_name:
                scene.fbp_render_custom_name = imported_name
                scene.fbp_render_prefix = ""
                scene.fbp_render_suffix = ""
                scene.fbp_render_token_mode = 'NONE'
                scene.fbp_render_prefix_token = 'NONE'
                scene.fbp_render_suffix_token = 'NONE'
                scene.fbp_render_use_name = True
        _FBP_NATIVE_PATH_CACHE[key] = raw_path
        return True
    except (AttributeError, OSError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not read Blender output path into Frame By Plane", exc)
        return False


def fbp_sync_all_render_outputs_from_native(*, force=False) -> int:
    changed = 0
    try:
        scenes = tuple(getattr(bpy.data, "scenes", ()) or ())
    except FBP_DATA_ERRORS:
        return 0
    for scene in scenes:
        changed += int(fbp_sync_render_output_from_native(scene, force=force))
    return changed


def fbp_render_filename_preview(scene) -> str:
    """Return only the current output filename, including its extension."""
    try:
        frame_path = str(scene.render.frame_path(frame=int(scene.frame_current)) or "")
        return os.path.basename(os.path.normpath(frame_path)) if frame_path else ""
    except (AttributeError, OSError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def fbp_render_static_prefix(scene) -> str:
    pattern = fbp_render_filename_pattern(scene)
    match = _HASH_RUN_RE.search(pattern)
    value = pattern[:match.start()] if match else os.path.splitext(pattern)[0]
    return value.rstrip(" ._-")
