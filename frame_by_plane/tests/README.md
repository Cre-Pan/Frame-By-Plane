# Frame By Plane — Blender 5.2 LTS regression runner

Use an official Blender **5.2.x Stable** executable. The launcher rejects other major/minor versions.

```bash
python tests/run_blender_lts.py --blender /path/to/blender --all
```

On Windows:

```powershell
py tests\run_blender_lts.py `
  --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
  --all
```

Suites:

- `background`: complete register/unregister and in-place reload cycles, scheduler teardown, managed collection/Layer Tree lifecycle, Undo/Redo, native GP effect creation/removal, Generic Mesh ownership, compositor artist-node/link preservation, save/reopen and a tiny Workbench render.
- `interactive`: 300 View3D sidebar redraws with nested collections and a GP canvas, then update/reload while Preferences is open and automatic What’s New scheduling.

The focused 7.2 gate runs the dual Stroke/Fill, Close Gap, paint/edit Undo,
compositor opt-in, Object Data Properties and lifecycle regressions as separate
Blender processes:

```bash
python tests/run_7_2_feature_gate.py --blender /path/to/blender
```

## Result handling

The launcher does **not** trust Blender's process exit code alone. Blender can exit with code `0` even when one or more Python tests failed. The generated JSON report is parsed and the launcher returns failure unless both conditions are true:

1. Blender exited normally;
2. the suite report contains `"passed": true`.

Each run preserves:

- `stdout.log`;
- `stderr.log`;
- the temporary Blender user directory;
- test `.blend` files and renders;
- the suite JSON report.

Default timeouts are 15 minutes for background and 20 minutes for interactive tests. Override them with `--background-timeout` and `--interactive-timeout`.

On headless Linux, the interactive suite automatically uses `xvfb-run` when available. Without a display server or `xvfb-run`, it fails explicitly instead of hanging.

## Native release gate

The repository-level `Blender 5.2 native release gate` workflow runs the real Blender executable on Linux x64, macOS ARM64 and Windows ARM64/x64. It builds, validates, installs and smoke-tests the package matching each runner. Linux also runs this interactive suite through Xvfb and performs the package-only validation for the fifth macOS x64 ZIP, for which Blender's official 5.2.0 checksum list currently contains no Intel runtime image.

See `docs/BLENDER_5_2_RELEASE_GATE.md` for triggers, runner labels, checksum verification and the publication rule.

## Official `bpy 5.2` module

The background suite can also run without the Blender desktop executable when
the official Blender Foundation `bpy==5.2.0` wheel is installed in Python 3.13:

```bash
python tests/run_bpy_lts.py
```

This mode covers RNA registration, data operations, Grease Pencil backends,
Generic Mesh validation, Compositor contracts, save/reopen and background
rendering. It cannot replace the interactive suite for View3D redraw, detached
Preferences windows, splash focus or GPU/UI behavior.
