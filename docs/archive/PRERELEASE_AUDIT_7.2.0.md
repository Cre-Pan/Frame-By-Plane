# Frame By Plane 7.2.0 — pre-release audit

Audit date: 2026-09-04
Runtime: Blender 5.2.0 LTS, Windows x64

## Outcome

**GO for GitHub pre-release.** The candidate combines the complete 7.1.19 stability branch with the final 7.1.29 Grease Pencil dual-color work. Regressions present in the older branch snapshot were not reintroduced: stale import Scene wrappers, current camera output controls, adaptive bookmark colors, centered Scrub Bar behavior and Generic Mesh ownership remain on their newer implementations.

Blender Extensions publication is a separate action and is not part of this GitHub pre-release audit.

## Merge coverage

- Independent Stroke and Fill colors in Grease Pencil Draw, Vertex Paint and Edit modes.
- Stroke, Fill and Both behavior; X swap; continuous Stroke-only Shift+X sampling.
- Mixed Edit selections, point-color and curve-fill writes, Close Gap and Draw-only G.
- Undo ordering for color changes, newly drawn strokes and cyclic state.
- Pin Mode and Close Gap placement in Blender's native Tool Header.
- Explicit compositor render opt-in with artist graph/state preservation.
- Object Data Properties image panel and shared Tool/N-Panel roots.
- All 7.1.19 camera, effect, import, Scrub Bar, timeline and runtime-stability changes.

## Blender 5.2 evidence

| Gate | Result |
|---|---:|
| Background regression suite | 39 PASS, 0 FAIL, 0 SKIP |
| Interactive UI suite | 8 PASS, 0 FAIL |
| Focused 7.2 source feature scripts | 6 PASS |
| Focused installed-package feature scripts | 5 PASS |
| Camera/GP timer-paced history | 14 PASS |
| Generic Mesh effects/history | 15 effects, 4 contract stages PASS |
| Image/Base/Shader/Geometry effects | 106 PASS |
| Native Grease Pencil effects | 27 PASS |
| Animation/Storyboard/General template cycles | 5 PASS |
| Template imports (PNG/JPEG/GIF) | 15 PASS |
| Isolated install, enable, save/reopen, Open/Revert/New | PASS |
| Official Blender extension validator | 5/5 PASS |
| Repeated-build SHA-256 reproducibility | 5/5 PASS |

The conservative orphan-code audit scanned 111 Python files and reported zero unused imports and zero orphan-module candidates. Its 26 symbol candidates are public compatibility, diagnostics or integration entry points and were retained deliberately.

## Platform packages

| Package | Bytes | SHA-256 |
|---|---:|---|
| `frame_by_plane-7.2.0-linux_x64.zip` | 11,308,608 | `6A0E7E412FAFDF4B8554CDD4CB1F3ABEB0A75380247BE16E47A3C4C68B5DD260` |
| `frame_by_plane-7.2.0-macos_arm64.zip` | 8,578,240 | `22ED579B811B507238EDC2147CDCF2E06ABBF869E15F79B04FE92AE207AD0C73` |
| `frame_by_plane-7.2.0-macos_x64.zip` | 9,191,808 | `974CA47FE2FFAF41610A9AC56805A576B49C90A3227B2E44D7F1D4489D75D6C1` |
| `frame_by_plane-7.2.0-windows_arm64.zip` | 6,700,871 | `B718FE9078C6C92213F5159493B617BAC6E76109120A7561B103106D345AB9CD` |
| `frame_by_plane-7.2.0-windows_x64.zip` | 11,154,008 | `46E3CDA2EACFA85C8E40CEC297F35854BC0057B960F504E24040F5253BB81793` |

macOS, Linux and Windows ARM64 packages are validated structurally on this Windows host. The GitHub Actions native matrix repeats build, validation and package checks on its matching runners.
