# Contributing to Frame By Plane

Thank you for helping improve Frame By Plane.

## Bug reports

Please include:

- Blender version;
- Frame By Plane version;
- operating system;
- exact steps to reproduce the issue;
- expected and actual behavior;
- screenshots, console output or a minimal `.blend` file when possible.

Do not include private media or project files unless you have permission to share them.

## Feature requests

Describe the workflow problem first, then the proposed solution. Examples, mockups and references to existing Blender tools are welcome.

## Code contributions

1. Create a branch from the current development branch.
2. Keep changes focused and avoid unrelated formatting rewrites.
3. Preserve Blender 5.1.2 compatibility unless a version change has been agreed.
4. Run:

```bash
python -m compileall -q frame_by_plane
python scripts/build_release.py --check
```

5. Explain user-facing changes and possible migration risks in the pull request.

## Style notes

- Prefer explicit, readable Blender API code.
- Avoid silent `except Exception: pass` blocks.
- Keep UI groups `align=False` by default; use `align=True` only for tightly related controls.
- Preserve meaningful separators and visual grouping.
- Avoid deleting image files from disk during cleanup operations.
