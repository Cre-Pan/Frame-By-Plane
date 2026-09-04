# Frame By Plane 7.1.19 — test report

## Current evidence — 4 September 2026

The authoritative current results and five ZIP hashes are in
[the pre-release audit](docs/PRERELEASE_AUDIT_2026-09-04.md): 39 background tests
and 8 interactive tests pass without skips; the installed effect matrix and
template/import checks also pass. Publication is conditional on the remaining
manual and native CI checks listed there.

The rest of this document is the **historical September 2 baseline**. Its ZIP
hashes are superseded and must not be used for this candidate.

## Historical baseline

Release candidate reverified on 2 September 2026 with Blender 5.2.0 LTS for Windows x64 (`fbe6228777e7`).

## Outcome

| Gate | Result | Evidence |
|---|---|---|
| Repository and version consistency | PASS | Manifest, constants, support policy, builder, publisher, notes and GitHub release gate agree on 7.1.19 |
| Background regression suite | PASS | 36 PASS, 0 FAIL, 1 documented SKIP |
| Interactive UI suite | PASS | 8 PASS, including two windows, 20 Undo/Redo and 300 redraws |
| Individual effect audit | PASS | 6 Base + 79 Shader + 21 Geometry Nodes + 27 native Grease Pencil = 133 PASS |
| GP effect-list UX | PASS | UIList selection, seven icon groups, add/remove/reorder/reset and duplicate repair; direct Blender screenshot checked |
| Timeline PR 162412 backport | PASS | Compact jumps, five time editors, bidirectional Scene Strip mapping and Follow Scene separation |
| Orphan-code audit | PASS | 0 orphan modules, 0 unused imports; 40 dead definitions/constants removed |
| Felt Fuzz contract | PASS | Canonical Seed/Alpha Mask sockets, saved Base Seed alias and installed-package check |
| GP visual-control contract | PASS | Rim/Shadow quality, Blur DOF, Glow RNA/defaults and Outline advanced controls |
| Blender 5.2 UI reference contract | PASS | 1,037 literal icons, 71 enum icons and 565 operator references; 0 mismatches |
| Blender extension validation | PASS | Linux x64, macOS ARM64/x64, Windows ARM64/x64 |
| Windows x64 isolated install | PASS | Enable, Grease Pencil canvas, save/reopen and operator persistence |
| Main replacement transaction cleanup | PASS | File Open, File Revert and New File leave no active owner or partial data |
| Bookmark upgrade contract | PASS | Legacy Blue migrates to Cyan; White migrates to adaptive None |
| Single Plane import regression | PASS | PNG import after 2D Animation/Storyboard cycles; incomplete registration and stale Scene wrappers cancel without a traceback |
| Preserved workflows | PASS | Clipboard folder import and hexadecimal Color Plane operators registered |
| Bundled Python wheels | PASS | Pillow 12.2.0, psd-tools 1.17.3, attrs 26.1.0 and typing-extensions import |
| Reproducible packaging | PASS | Two independent normalized builds produced identical SHA-256 hashes |
| Official Blender Extensions API schema | PASS | Bearer auth, multipart `version_file`/`release_notes`, HTTP 201 and 1024-character notes limit confirmed |

Correction: the historical background `SKIP` was caused by the artist-preservation
fixture leaving Generic Mesh Preview disabled and misreporting any rejected
application as an unavailable asset. Camera Scale Lock was also incorrectly
classified as generic-mesh compatible. The September 4 audit corrects both and
executes the preservation/rollback test with no skip.

## Historical platform packages — superseded

| Package | Bytes | SHA-256 |
|---|---:|---|
| `frame_by_plane-7.1.19-linux_x64.zip` | 11,283,881 | `3E4441982C45CE43B7002D4C4CD6F91C42DAE7F675FA66E4E0818237A7734D30` |
| `frame_by_plane-7.1.19-macos_arm64.zip` | 8,553,512 | `E90CAA6D43B49C55B5FC475D9215639E8F75A04D43CCFFC32E113D5368686A21` |
| `frame_by_plane-7.1.19-macos_x64.zip` | 9,167,080 | `2ABC1958E3A2116D80ABC03813691EF69CB338459EDDD49DC2421A9DAD046284` |
| `frame_by_plane-7.1.19-windows_arm64.zip` | 6,676,143 | `D101D94FFFA43F53C062C1CF0783B0F964DBE9BAE40EB619477F5B2313E91C84` |
| `frame_by_plane-7.1.19-windows_x64.zip` | 11,129,280 | `DF0389C0BA54E6C1C2AC96A053D90E6F84D720D65025DD40F52A0F9ABE480964` |

The official Blender 5.2.0 checksum list was checked again on 8 August 2026 and still provides macOS ARM64 but no macOS x64 runtime. The Intel package therefore has structural validation and deterministic-wheel coverage, not a native Intel runtime result.

## Local evidence

- `effect-audit-7.1.19/base-final2.json`
- `effect-audit-7.1.19/shader-final2.json`
- `effect-audit-7.1.19/geometry-final2.json`
- `effect-audit-7.1.19/gp-native-final2.json`
- `effect-audit-7.1.19/deep-orphan-audit-7.1.19-final3.json`
- `release-7.1.19-tests-gp-ux/lts_report_background.json`
- `release-7.1.19-tests-gp-ux/interactive_report_interactive.json`
- `release-7.1.19-tests-gp-ux/installed-package-smoke.json`
- `release-7.1.19-tests-gp-ux/installed-release-contract.json`
- `release-7.1.19-tests/bookmark-palette-final.png`
- `work/test-results/effect-audit-all.json`
- `work/test-results/effect-audit-gp-native.json`
- `work/visual-qa/gp_effect_stack.png`
- `work/visual-qa/gp_effect_group_menu.png`
- `work/visual-qa/timeline_compact_header.png`
- `release-7.1.19-final-r5/FRAME_BY_PLANE_7.1.19_BUILD_REPORT.md`
- `release-7.1.19-final-r5/PACKAGE_VALIDATION_7.1.19.json`
- `release-7.1.19-final-r5/SHA256SUMS.txt`
- `work/import-fix-lts_background.json`
- `work/import-fix-lts_interactive.json`
- `work/import-package-smoke.json`
- `work/import-installed-contract.json`
- `work/visual-import-installed-qa/report.json`
- `work/visual-import-installed-qa/imported-plane.png`
- `work/stability-ui-contract-final.json`
- `work/stability-effects-all.json`
- `work/stability-effects-gp-native.json`
- `work/stability-final-background_background.json`
- `work/stability-final-interactive_interactive.json`
- `work/stability-installed-results/installed-smoke.json`
- `work/stability-installed-results/installed-contract-final.json`
- `work/stability-release-7.1.19-build/`
- `work/stability-release-7.1.19-repro/`
