# Linked camera pixels and format presets — 2026-09-04

Local Frame By Plane 7.1.19 candidate. Supersedes the pixel-field visibility
described in `CAMERA_ASPECT_UI_2026-09-04.md`; ten aspect shapes and the existing
landscape-default/swap semantics remain unchanged. No online publication.

## Behavior

- Resolution and editable `Width (px)` / `Height (px)` are always visible,
  including SD/HD/2K/4K/8K, not only Custom. Editing pixels sets Resolution to
  Custom. The `LINKED` / `UNLINKED` icon-only toggle sits between the fields.
- Linking defaults to on. At 1:1, typing height 1000 sets width 1000; either
  side can drive the other. Landscape, portrait, custom ratios and non-square
  pixel aspect are supported. An invalid linked pair is rejected before either
  native dimension is written, avoiding Blender's silent per-side clamping.
- Unlinked edits leave the other dimension unchanged and label Aspect Ratio
  Custom. Toggling the link alone never resizes the output. Re-linking preserves
  the current custom ratio; choosing an aspect shape restores its named label.
- The swap button row and resolution/pixel rows use `align=False`. At logical
  region widths below 540 px, the resolution dropdown and pixel fields occupy
  separate rows. The 360 px camera dialog explicitly uses the narrow layout.
- A `PRESET` icon opens Camera Format Presets, with Save Current Format, named
  apply buttons and remove buttons. Presets store raster dimensions, pixel
  aspect, aspect label/custom state, resolution choice and link state in the
  current scene of the blend file, following the existing effect-preset scope.
  They are not an external/global user library. Duplicate names get a suffix;
  saving never silently overwrites an existing preset.
- Save/apply/remove operators support Undo. Render percentage is not saved or
  modified; projection, lens and clipping are outside these format presets.
  Render scale and pixel-aspect editing remain in native Output Properties.
- No new timers or draw-time writes. Camera format UI/operators are disabled
  for non-editable scenes and in Edit Mode, consistent with the existing
  Blender 5.2 history safety policy. GP behavior is unchanged in this revision.

## Verification

Blender 5.2.0 LTS Windows x64, hash `fbe6228777e7`. Isolated profiles; no changes
to the user's active project, installed extension or saved preferences.

- General background at this stage: **38 PASS, 1 SKIP**. Correction: the skip was the Generic Mesh Preview fixture with its feature flag disabled, not interactive-only Undo. See `PRERELEASE_AUDIT_2026-09-04.md` for the repaired fixture and current results.
- General interactive scripted tests: **8 PASS**.
- Timer-paced camera/GP history: **14 PASS**. Added linked-pixel Undo/Redo,
  unlinked/Custom/link-state Undo/Redo and preset save/apply/remove Undo/Redo.
- New focused regression covers both input axes, both orientations, re-link
  without resizing, custom ratios, non-square pixels, atomic limit rejection,
  preset duplicate naming, save/apply/remove, stale indexes and blend-library
  write/reload persistence.
- UI layout recorder covers HD and Custom, linked and unlinked, 320 and 800 px
  widths, field order, English labels, native icons and unaligned rows.
- Repository verification and `git diff --check` pass. Existing unrelated
  line-ending warning for the PowerShell publisher is unchanged.
- Native UI reference check: 1,049 literal icons and 71 enum icons valid;
  572 operator references resolve. Reference checks are not execution coverage
  of every operator.
- Five ZIPs pass Blender's extension validator. The installed Windows x64 ZIP
  passes smoke create/save/reopen/revert/new-file lifecycle checks, bundled
  dependencies and the installed release contract including linked pixels
  and camera format presets.

Evidence in `work/`: `camera-linked-regression_background.json`,
`camera-linked-regression_interactive.json`, `camera-linked-history.json`,
`camera-linked-ui-contract.json`, `camera-linked-installed-smoke.json`,
`camera-linked-installed-contract.json`.

### Visual acceptance limitation

An isolated preview opened wide/narrow Properties editors and saved
`camera-linked-visual-profile/FBP_Camera_Linked_QA.blend`. The computer-use helper
returned only an unrelated unsaved Blender window, not the named QA window,
including after refresh and JavaScript reinitialization. Per the computer-use
skill's unique-target requirement, no desktop input was sent. The isolated
preview was then closed via its own shutdown timer. Visual mouse/keyboard
acceptance is not complete; scripted/layout evidence is reported separately.
No native execution on macOS, Linux or Windows ARM64 is claimed.

## Local packages

Folder: `work/camera-linked-release-7.1.19/`. Previous candidates and Downloads
were not overwritten. Normalized ZIPs, SHA-256:

| Platform | SHA-256 |
| --- | --- |
| Windows x64 | 6C2617451D50462C56C648396EB3F66CEC08E2F7558EE40018855C78176493CF |
| Windows ARM64 | E764938309A893926935BBDC3DB3E61BA3238921EE0FD566F73FD8B1A53AFA64 |
| macOS x64 | FE9DB1F6B5330BD6BA429AF7DC6A286E635944E0E76BD0BDF356B6C55EA9D711 |
| macOS ARM64 | 4696E19C5689A2CF412BF314F53F58C8A7DE95474D1417DB86A7BF67D4D291A2 |
| Linux x64 | 4C4504BFD7B3F29D70F7321964F5BB32A7AC18538D57E87D2F32915C9B9AFCB2 |
