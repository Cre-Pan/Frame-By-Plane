# Frame By Plane 7.1.19 — GO / NO-GO

## Decision

**Conditional GO for release preparation; public upload remains pending final acceptance.**

The current candidate and authoritative hashes are in
[the 4 September pre-release audit](docs/PRERELEASE_AUDIT_2026-09-04.md).
It repairs scene caches, same-batch scheduler guards and Generic Mesh 5.2
compatibility; the formerly skipped regression now runs. Windows automation is
green, but the updated native CI matrix and manual acceptance of the newly added
camera layout remain outstanding. No online publication was performed in this audit.

The source, five platform ZIPs, release notes and automated gates are aligned. The Bookmark Color Tag regression is migrated safely, the clipboard/hex workflows remain available, the GP effects interface matches the plane-effects list/group rhythm, and Single Plane import was reverified from the installed Windows x64 ZIP after Animation/Storyboard template cycles.

## Required gates

The table below records earlier baseline checks. It is not fresh multi-platform
runtime or manual camera-layout evidence for the September 4 candidate.

| Gate | Status |
|---|---|
| Version and release-file consistency | PASS |
| Background Blender 5.2 suite | PASS |
| Interactive Blender 5.2 suite | PASS |
| 133-effect isolated matrix | PASS |
| Orphan module and unused-import scan | PASS |
| Felt Fuzz source and installed contract | PASS |
| Native GP visual controls and Glow defaults | PASS |
| Native GP list and seven grouped icon menus | PASS |
| Compact Timeline and five-editor synchronization | PASS |
| Bidirectional Scene Strip frame mapping | PASS |
| Five platform archives validate | PASS |
| Two-build reproducibility | PASS |
| Windows x64 installed-package smoke | PASS |
| Packaged Single Plane import and file-browser invoke | PASS |
| Legacy Blue and new Cyan contract | PASS |
| Clipboard-folder and Hex Color Plane compatibility | PASS |
| Blender Extensions publisher `-WhatIf` | PASS |
| Official Blender Extensions OpenAPI endpoint/schema check | PASS |

## Publication boundaries

- The macOS Intel archive remains package-only evidence because Blender 5.2.0 has no official macOS x64 runtime in its checksum listing.
- Publishing to Blender Extensions remains a separate API action and requires `BLENDER_EXTENSIONS_TOKEN` plus the script's typed `UPLOAD 7.1.19` confirmation.
- Upload only the current hashes in `docs/PRERELEASE_AUDIT_2026-09-04.md`; rebuilds must be revalidated and redocumented.
