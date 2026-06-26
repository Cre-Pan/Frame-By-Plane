# Contributing to Frame By Plane

Contributions, reproducible bug reports and focused pull requests are welcome.

## Development requirements

- Blender 5.1.2 or newer.
- Python syntax compatible with Blender’s bundled Python.
- No network dependency at runtime.
- New third-party code or wheels must include their license and attribution.

## Before opening a pull request

1. Keep the change limited to one clear purpose.
2. Run `python tools/verify_repository.py`.
3. Compile the extension sources with `python -m compileall -q frame_by_plane`.
4. Test installation from a freshly built ZIP.
5. Verify save/reopen and Undo/Redo when the change affects scene data.
6. Update `CHANGELOG.md` for user-visible changes.

## Bug reports

Include:

- Frame By Plane version.
- Exact Blender version.
- Operating system and architecture.
- Minimal reproduction steps.
- Expected and actual behavior.
- Relevant screenshots or console traceback.
- Diagnostic report from Frame By Plane when available.

## Code style

- Prefer small, explicit functions.
- Avoid silent broad exception handling.
- Keep UI strings and tooltips clear for non-developers.
- Preserve Blender data safely across Undo/Redo, file reload and handler execution.
- Do not commit generated packages, caches, backups or local test files.
