# Camera output and Grease Pencil history audit — 2026-09-03

Local 7.1.19 candidate; no GitHub or Blender Extensions publication performed.

## Findings and changes

1. **Camera pixels disabled by unrelated import option.** The previous camera
   panel required both legacy Aspect=Custom and Source Aspect=false. The new
   Output Format group separates aspect-ratio text from resolution. Custom
   width/height are editable regardless of Source Aspect; that option is now
   explicitly labelled “Use Source Aspect on Import”.
2. **GP material/effect property edits are not stored in Edit Mode history in
   the installed Blender build.** Point colors are stored correctly. A native
   Material change followed by an Edit Mode undo push remained changed after
   Undo. This is corroborated by the exact build's native property-Undo check,
   which skips IDs whose type differs from the edited object data. The add-on
   now displays material/effect controls read-only in Edit Mode, with an
   explicit Object Mode button. Effect add/remove/reset/reorder polls also
   reject Edit Mode. No automatic mode switching or undo_post material rewrite
   was introduced. This is a mitigation, not a patch to Blender's Undo engine.
3. **Camera setting persistence.** New controls read native RenderSettings;
   legacy combined presets are retired only after an explicit new-control edit.
   This prevents later camera generation from resetting a newly chosen Custom
   size. There is no file-load migration and no timer that reapplies resolution.

Native source for the installed build:
[ed_undo.cc at fbe6228777e7](https://github.com/blender/blender/blob/fbe6228777e7/source/blender/editors/undo/ed_undo.cc#L394).
The newer main branch has different Undo behavior; it was not used as evidence
for the installed 5.2 executable.

## Resolution semantics

Presets specify the longest raster side: SD=720, HD=1920, 2K=2048, 4K=3840,
8K=7680. At 16:9 these give 720×405, 1920×1080, 2048×1152, 3840×2160 and
7680×4320. Vertical formats swap orientation, squares use the same side twice.
4K/8K are UHD-size presets, not DCI. Custom exposes width and height freely.
Display aspect accounts for non-square pixels. Render percentage is unchanged
unless the user edits Scale. Invalid/zero/out-of-range ratios show an error and
leave existing pixel dimensions untouched.

## Verification

Executable: Blender 5.2.0 LTS, Windows x64, hash `fbe6228777e7`, built 2026-07-14.
Isolated profiles; no user startup file/preferences/project modified.

- General background suite at this stage: 37 PASS, 1 SKIP. Correction: the skip was the Generic Mesh Preview fixture with its feature flag disabled, not interactive-only Undo. See `PRERELEASE_AUDIT_2026-09-04.md` for the repaired fixture and current results.
- General interactive suite: 8 PASS, including 20 Undo/Redo cycles and UI lifecycle tests.
- Targeted timer-paced history audit: 10 PASS. Camera preset Undo/Redo; all five
  resolution presets; portrait/square/non-square pixels; seven invalid ratios;
  Custom with Source Aspect enabled; point-color Undo/Redo in GP Edit Mode;
  20 rapid point-color Undo/Redo pairs; 20 material Undo/Redo pairs in Object
  Mode; stroke/fill RGBA and random HSV; native Hue/Saturation effect;
  active-material-slot removal; guarded effect actions in Edit Mode.
- Material tests explicitly use Object Mode after verifying the Edit Mode guard.
  They do **not** claim material Undo now works inside Edit Mode.

Reports: `work/camera-gp-final-regression_background.json`,
`work/camera-gp-final-regression_interactive.json`,
`work/camera-gp-history-final.json`.
Reusable focused test: `tools/audit_camera_gp_history.py`.

Additional package checks: all five ZIPs pass Blender's extension validator.
The Windows x64 ZIP was installed and enabled in a fresh isolated extension
repository. The installed smoke test passed create/save/reopen/revert/new-file
checks; the installed release contract passed including camera output, GP Edit
Mode guard, dependencies, bookmarks, timeline and native GP effect contracts.
Literal UI contract check: 1,042 icons, 71 enum icons, no invalid identifiers.
Operator-name checks are supplementary static checks, not execution coverage.

Candidate archives are in `work/camera-gp-release-7.1.19/`. Downloads was not
overwritten. SHA-256:

| Platform | SHA-256 |
| --- | --- |
| Windows x64 | B327A488BAD91F1225593B326F1991E986EC89572A32BF36001AC20992E4B3B0 |
| Windows ARM64 | B6797D8244B691DC625AF64920C8B723CAE0FE0CAED5897A1CF312F330CFB449 |
| macOS x64 | 6F84C62FC80A591C4D766998C35BB3A53306AAF15C46D05FC9F7A2FD2AA4A806 |
| macOS ARM64 | F835A125AB9398C432E9D469E778708B1B96EE77A31817F2ED3EB0CBA0673574 |
| Linux x64 | 7662DA11CD03F89A7444973BD5B13E5978E2045151E1D8CD63FE75891DDAE7D7 |

## Remaining validation

Desktop control returned an outdated Blender window, then
“foreground window did not report a process id”. A unique current QA window
could not be selected after recovery; input was stopped under the computer-use
skill's safety rule. Therefore mouse/keyboard visual acceptance of the actual
camera panel and sliders is **not** marked complete. Scripted interactive
tests are separate evidence, not a replacement for this visual check.

No native macOS, Linux or Windows ARM64 execution was performed.
