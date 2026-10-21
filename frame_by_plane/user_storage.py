"""Where Frame By Plane writes files.

Two kinds of locations are used:

* User data (effect presets and fallback caches) lives in the extension's own
  user folder from ``bpy.utils.extension_path_user``. Blender Extensions asks
  add-ons to keep their writable files there so that uninstalling the
  extension can remove them.
* Media generated for a project (extracted PSD/Procreate layers, converted
  animated images, native sequence proxies, clipboard images) goes into an
  ``assets`` folder beside the saved ``.blend``, so the project folder can be
  moved or shared as a whole. Unsaved files keep the previous behaviour of
  writing beside the source media.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import bpy


FBP_PROJECT_ASSETS_DIRNAME = "assets"
FBP_LEGACY_USER_FOLDER = "frame_by_plane"


def _package_name():
    return __package__ or FBP_LEGACY_USER_FOLDER


def fbp_user_data_dir(*parts, create=True):
    """Return the extension user folder (or a sub-folder), or ``""``.

    Falls back to Blender's legacy user DATAFILES folder only when the add-on
    was installed outside the extension system, where
    ``extension_path_user`` is unavailable.
    """
    sub_path = os.path.join(*parts) if parts else ""
    try:
        return str(bpy.utils.extension_path_user(_package_name(), path=sub_path, create=create) or "")
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError, OSError):
        pass
    try:
        return str(
            bpy.utils.user_resource(
                "DATAFILES",
                path=os.path.join(FBP_LEGACY_USER_FOLDER, sub_path),
                create=create,
            )
            or ""
        )
    except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
        return ""


def fbp_legacy_config_file(name):
    """Return a file in the pre-7.6 CONFIG folder without creating it."""
    try:
        root = bpy.utils.user_resource("CONFIG", path=FBP_LEGACY_USER_FOLDER, create=False)
    except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
        return None
    return Path(root) / name if root else None


def fbp_migrate_legacy_user_file(target, legacy):
    """Copy a legacy file into the extension folder once; never delete it."""
    try:
        if legacy is None or target.exists() or not legacy.is_file():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        return True
    except OSError:
        return False


def fbp_project_assets_dir(*parts):
    """Return ``<blend folder>/assets/<parts>`` for a saved file, else ``""``.

    The folder is not created here; callers create it when they write.
    """
    try:
        blend_path = str(getattr(bpy.data, "filepath", "") or "")
    except (AttributeError, ReferenceError, RuntimeError):
        blend_path = ""
    if not blend_path:
        return ""
    root = os.path.join(os.path.dirname(os.path.abspath(blend_path)), FBP_PROJECT_ASSETS_DIRNAME)
    return os.path.join(root, *parts) if parts else root


def fbp_media_cache_roots(kind, beside_source):
    """Return candidate cache folders for generated media, best first.

    ``kind`` names the ``assets`` sub-folder (``layers``, ``media``,
    ``sequences``, ``clipboard``). ``beside_source`` is the pre-7.6 folder next
    to the source file, used when the ``.blend`` has not been saved yet.
    """
    roots = []
    project = fbp_project_assets_dir(kind)
    if project:
        roots.append(project)
    elif beside_source:
        roots.append(str(beside_source))
    user = fbp_user_data_dir(kind, create=False)
    if user:
        roots.append(user)
    return roots


__all__ = (
    "FBP_PROJECT_ASSETS_DIRNAME",
    "fbp_legacy_config_file",
    "fbp_media_cache_roots",
    "fbp_migrate_legacy_user_file",
    "fbp_project_assets_dir",
    "fbp_user_data_dir",
)
