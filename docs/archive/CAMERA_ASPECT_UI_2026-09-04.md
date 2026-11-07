# Camera aspect dropdown — 2026-09-04

Local Frame By Plane 7.1.19 candidate. No publication or user-profile update.
This UI revision supersedes the camera text/Custom pixel UI described in the
2026-09-03 audit; the GP history mitigation is unchanged.

## Behavior

- Exactly ten shapes in increasing landscape aspect: 1:1, 4:5, 4:3, 3:2,
  16:10, 16:9, 2:1, 21:9, 2.39:1 and 32:9.
- Choosing a shape explicitly starts landscape. The requested 4:5 label means
  the shape independent of orientation: at HD it starts as 1920×1536 (5:4).
- The icon-only `RENDER_SWAP_DIMENSIONS` button switches to 1536×1920 (4:5).
  Resolution changes then retain portrait orientation. Selecting a shape again
  explicitly chooses landscape again.
- Aspect Ratio uses `IMAGE_BACKGROUND`. Both the camera panel and camera dialog
  share this drawing helper. Render percentage, Custom width/height and pixel
  aspect fields are absent from this camera UI; edit them in Output Properties.
- Resolution retains SD/HD/2K/4K/8K/Custom. Presets still refer to the longest
  raster side (720/1920/2048/3840/7680 pixels). Custom keeps native dimensions.
- Swap also swaps pixel-aspect X/Y, giving the reciprocal display format for
  non-square pixels. Two swaps restore the exact original values. Square output
  with square pixels is a no-op. Render percentage is never changed.
- Changes are synchronous and operator actions support Undo. No deferred timer
  reapplies camera dimensions. The new format operators reject Edit Mode and
  non-editable scenes. Legacy string/pixel APIs remain for saved-file compatibility;
  native/custom dimensions are not coerced merely by drawing or loading the UI.

## Verification

Blender 5.2.0 LTS, Windows x64, build `fbe6228777e7`. Isolated test profiles;
the user's running Blender, project and saved preferences were not modified.

- Background regression at this stage: **37 PASS, 1 SKIP**. Correction: the skip was the Generic Mesh Preview fixture with its feature flag disabled, not interactive-only Undo. See `PRERELEASE_AUDIT_2026-09-04.md` for the repaired fixture and current results.
- Interactive scripted regression: **8 PASS**.
- Timer-paced camera/GP history: **11 PASS**, including aspect selection,
  swap Undo/Redo, portrait resolution changes, GP point-color Edit Mode history,
  GP material Object Mode history and the existing Edit Mode safety guard.
- All ten shapes, ascending aspect, landscape defaults, double swaps, square
  no-op, non-square pixel swap, unchanged scale, Custom/native Output edits,
  requested native icons and absence of render fields in the draw helper pass.
- Static repository verification passes.
- UI reference check: 1,044 literal icons, 71 enum icons, no invalid identifiers.
  569 operator references have no missing identifiers; this is supplementary
  static reference checking, not execution coverage for every operator.
- All five platform archives pass Blender's extension validator.
- The Windows ZIP installs/enables in a fresh isolated extension repository.
  Installed smoke checks pass create/save/reopen/revert/new-file lifecycle.
  Installed release contract passes camera dropdown/operator behavior and
  existing GP, bookmark, timeline, dependency and import contracts.

Reports in `work/`:

- `camera-aspect-dropdown-regression_background.json`
- `camera-aspect-dropdown-regression_interactive.json`
- `camera-aspect-dropdown-history.json`
- `camera-aspect-dropdown-ui-contract.json`
- `camera-aspect-dropdown-installed-smoke.json`
- `camera-aspect-dropdown-installed-contract.json`

No new manual mouse/keyboard visual acceptance was performed for this revision.
No native execution on Windows ARM64, macOS or Linux is claimed.

## Candidate packages

Directory: `work/camera-aspect-dropdown-release-7.1.19/`.
Previous candidates and Downloads ZIPs were not overwritten. ZIP metadata was
normalized; SHA-256 values below identify this exact local build.

| Platform | SHA-256 |
| --- | --- |
| Windows x64 | E9B42BBC77D818565AD3D7C788AFB4D30916D67C3C4BD3F2A0CB73E23FA4B5CB |
| Windows ARM64 | 74C55CB017C69A5EA1FE6AFD93006A995F72E2215ED3409516AD89DF0A43B502 |
| macOS x64 | F34C6FD31FCCB34C251562B29D1166F00ECF7F6F962FDE667672F37B548A3368 |
| macOS ARM64 | 815E7A68268A1BC5E74AE7F51FB833865763E2C2893A84D062AACECA77A12642 |
| Linux x64 | 0DAF0F8F5B0B425EF85A786CB2E9FAD01EADAA8AB626450927947D4201B1388C |
