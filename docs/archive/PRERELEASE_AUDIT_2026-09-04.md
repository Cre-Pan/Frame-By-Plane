# Frame By Plane 7.1.19 — pre-release stability and performance audit

Date: 4 September 2026. Native runtime: Windows x64, Blender 5.2.0 LTS,
build `fbe6228777e7`. Functional suites and installed-package tests used isolated
profiles and disposable scenes. No publication, upload, user-preference replacement or user-project
modification was performed.

## Decision

**Local candidate passes the automated Windows checks. Public release remains
conditional on the current native CI matrix and manual acceptance of the new
camera layout.** This report supersedes earlier 7.1.19 package hashes and the
incorrect explanations of the background test skip.

This is a broad code/runtime audit, not a guarantee that every possible scene,
driver, render engine, GPU or artistic effect combination is bug-free.

## Confirmed problems corrected

1. **Partial scene caches prevented recovery.** A cached mirror-only result could
   suppress a requested full lookup; unlisted rigs/planes stayed invisible to
   recovery callers. Cache entries now distinguish partial from complete results,
   and plane recovery merges missing tagged scene objects. An interrupted scan
   cannot mark a partial result complete.
2. **Repeated scans after an empty result.** Validated empty indexes now reuse the
   existing short cache lifetime instead of rescanning every unrelated object.
   Existing invalidation and bounded, name-only caches remain in place.
3. **Repeated aspect-label parsing during redraw.** The ten immutable shape labels
   are normalized once, not reparsed as fractions on each lookup.
4. **Same-batch scheduler races.** A callback could enable a render/history guard,
   postpone another task, or invalidate its history epoch after the due-task list
   had been collected. The dispatcher now rechecks all three immediately before
   running each callback. Guarded/postponed work resumes later; expired work does
   not run. All three probes failed before the fix and pass afterwards.
5. **Generic Mesh Preview still used removed modifier ID properties.** Native
   Blender 5.2 rejected application with `id properties not supported for this
   type`. Inputs and transaction snapshots now use generated modifier RNA.
   Snapshots restore values, input modes, attribute names, visibility and metadata.
6. **Ownership must not depend on recycled modifier IDs.** Blender reused a
   removed modifier's persistent UID during the preservation regression. Ownership
   now uses an unused hidden string input with an empty default, backed by a
   compact Object registry. A new artist modifier sharing the same node group
   remains unowned, even after deletion, renaming, save/reopen or Undo/Redo.
   Object duplication retains ownership and duplicate repair preserves artist work.
7. **Generic Mesh compatibility and value conversion.** Camera-dependent effects
   are excluded using the registry's current camera contracts. Infinite Rotation's
   direction is converted consistently for planes and generic meshes. Generic
   application checks that requested socket values were actually retained and
   rolls back on failure instead of accepting a partial update.
8. **A skipped test concealed these failures.** The artist-preservation fixture
   did not enable Generic Mesh Preview and misreported any rejected application
   as a missing asset. It now enables/restores the flag and fails on a genuine
   problem. RNA preservation assertions compare Blender data identity rather than
   Python wrapper identity. The final suite has no skips.
9. **Installed-package CI could report false success.** Blender returned exit 0
   for a deliberately raised Python exception without `--python-exit-code`.
   Installed smoke/contract gates now request a nonzero Python error code. Native
   scheduler/index probes are included, and the release-contract reader requires
   the new aspect-dropdown and linked-pixel/preset checks. Workflow changes are
   prepared locally; GitHub Actions has not run on this candidate yet.
10. **Extension release notes exceeded the uploader's limit.** The accumulated
    short notes no longer passed the publisher's 1,024-character check. They are
    condensed to 981 characters in the local PowerShell dry run; full GitHub notes
    remain separate. Repository verification now checks this boundary as well.

Generic Mesh remains opt-in **Preview**. These repairs do not promote it into the
7.1 LTS support promise or enable it by default. No blanket removal of backward
compatibility data or public diagnostic APIs was made.

## Measured performance

Same local Blender binary; 30 warm samples per measurement. Scene-index tests
contain no FBP rigs and either 1,000 or 10,000 unrelated objects. Values are median
wall-clock milliseconds, not whole-frame/render timings.

| Measured operation | Before | After | Change |
|---|---:|---:|---:|
| Empty-index lookup, 1,000 objects | 0.1890 ms | 0.0246 ms | about 87% less time |
| Empty-index lookup, 10,000 objects | 2.6871 ms | 0.3738 ms | about 86% less time |
| 100 camera aspect-label reads | 8.8988 ms | 1.5083 ms | about 83% less time |

The instrumented rig-predicate visits across ten warm 10,000-object lookups fell
from 100,000 to zero. Other lookup bookkeeping remains, so the measured cost is
not zero. No comparable startup improvement or overall FPS uplift is claimed.
Raw baseline: `work/prerelease-2026-09-04/baseline.json`; comparable post-fix
measurement: `final-runtime.json`. Latest strict functional rerun: `release-runtime.json`.

## Final test evidence

Paths below are under `work/prerelease-2026-09-04/` unless otherwise stated.

| Check | Result | Evidence |
|---|---|---|
| General background suite | 39 PASS, 0 FAIL, 0 SKIP | `final4-regression_background.json` |
| Interactive suite | 8 PASS | `final4-regression_interactive.json`; includes two windows, 20 Undo/Redo pairs and 300 redraws |
| Scheduler guards, rescheduling, epochs and scene recovery | PASS | `release-runtime.json` |
| Individual effects in the final installed ZIP | 6 Base + 79 Shader + 21 Geometry + 27 GP = 133 PASS | `final-installed-effects-*.json` |
| Generic Mesh Preview | All 15 supported effects; ownership, save/reopen and remove/Undo/Redo PASS | `final-installed-mesh-history.json`; atomic rollback and artist-preservation assertions also run in the background suite |
| Camera and GP history | 14 PASS on the final installed ZIP | `final-installed-camera-gp-history.json`: linked/unlinked pixels, presets, swaps, GP Edit point colors, Object material/effect history and rapid Undo/Redo |
| Installed ZIP lifecycle | PASS | `final-installed-smoke.json`: enable, canvas, save/reopen, File Open/Revert/New transaction retirement |
| Installed release contracts | PASS | `final-installed-contract.json`: camera/link/presets, palette migration, GP guards, timeline, import and bundled wheels |
| Template/import regression | 5 cycles, 15 imports PASS | `final-installed-templates.json`: Animation, Storyboard, General, Animation, Storyboard; PNG/JPG/GIF each |
| Viewport headers after template changes | PASS, positive width and 32 px height throughout | `final-installed-templates.json`; scripted geometry check, not manual visual acceptance |
| UI identifiers | 1,049 literal icons + 71 enum icons + 572 operators, no invalid references | `ui-contract.json`; identifier validity is not execution or visual coverage |
| Static orphan scan | 103 Python files; 0 orphan modules, 0 unused imports | `tools/audit_orphan_code.py`; 26 lexical candidates retained as public/diagnostic helpers, not automatically treated as dead code |
| Repository consistency and whitespace | PASS | `tools/verify_repository.py`, `git diff --check` |
| Five ZIPs | Native extension validation PASS; two normalized builds identical | `final-packages/`, `final-reproducibility/` |
| Archive integrity | All five CRC checks pass, correct manifest version and no unsafe paths | `tools/package_release.py::validate_zip` |
| Source/package alignment | 490 packaged Python-file comparisons, zero mismatches | Every Python member across the five final ZIPs compared byte-for-byte with the current source |
| Blender Extensions preparation | Five packages and condensed notes pass `-WhatIf` | No token read and no API request sent |

Expected warnings from deliberate invalid camera inputs and injected transaction
failures are test evidence, not unhandled application errors. Earlier `baseline`,
`before-scheduler`, `mesh52`, `final2` and `final3` reports are retained as diagnostic
history; they are not the final release verdict.

## Current candidate packages

Use these files, not the earlier September 2 or camera-only builds.

| Package | Bytes | SHA-256 |
|---|---:|---|
| [Windows x64](../work/prerelease-2026-09-04/final-packages/frame_by_plane-7.1.19-windows_x64.zip) | 11,136,944 | `835F66E72C422E0BA8C848D345958D99B29BFAEF93E4E6A3FF0581E46CF87E86` |
| [Windows ARM64](../work/prerelease-2026-09-04/final-packages/frame_by_plane-7.1.19-windows_arm64.zip) | 6,683,807 | `7BE619734E461116784A37A8EFA885E9E008CB9C5E89640EECBB865044D4C7BF` |
| [Linux x64](../work/prerelease-2026-09-04/final-packages/frame_by_plane-7.1.19-linux_x64.zip) | 11,291,545 | `1C827ADC51B4304EB112C3B106CB52B0850B9586DC185C08F71A00988BB0939D` |
| [macOS ARM64](../work/prerelease-2026-09-04/final-packages/frame_by_plane-7.1.19-macos_arm64.zip) | 8,561,176 | `86D5109174537F99277FCA700717672A5284D71B1BAEA00A5BF74F195E6097D6` |
| [macOS x64](../work/prerelease-2026-09-04/final-packages/frame_by_plane-7.1.19-macos_x64.zip) | 9,174,744 | `D79C8142056FE8E8321ED901573C0E380C6B42FBAE27125A8AA3F813E163CCD2` |

Only Windows x64 was executed natively during this audit. Structural validation
and deterministic wheel selection do not establish runtime support on the other
four architectures. In particular, retain the documented package-only boundary
for macOS Intel unless a supported native Blender runtime is available and tested.

## Remaining release acceptance

- Run the updated native GitHub Actions matrix on the exact candidate source.
- Manually inspect the new Camera Resolution/Width/Link/Height controls at narrow
  and wide panel widths, including UI scaling, presets and orientation changes.
  Programmatic assertions do not certify clipping, readability or click targets.
- Review a representative production scene during long playback/render and
  artistic effect combinations; the microbenchmarks do not replace that check.
- Publish only after reconciling those results with these exact ZIP hashes.
  Blender Extensions upload remains a separate, explicitly confirmed API action.
