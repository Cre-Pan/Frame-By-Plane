# Frame By Plane troubleshooting for Blender 5.2

## The add-on does not install

Confirm that Blender reports version **5.2.x** and that the downloaded asset matches the computer architecture. Install the ZIP directly through **Edit → Preferences → Get Extensions → Install from Disk**; do not extract it first.

Do not use GitHub's automatically generated **Source code (zip)** file. A valid release asset contains `blender_manifest.toml` at the root and has a platform suffix such as `windows_x64`.

## PSD or Procreate import is unavailable

Use the platform-specific Frame By Plane package. It contains compatible Pillow and psd-tools wheels for the target operating system and CPU. Reinstalling a source archive does not add those native dependencies.

## A Grease Pencil effect appears more than once

Frame By Plane 7.1.18 and later prevent new unmanaged duplicates on Blender 5.2. If a project was edited with 7.1.17, open the Grease Pencil Effect Stack and use **Repair Duplicates** when the warning appears. The repair removes only effects carrying Frame By Plane ownership metadata and preserves artist-authored effects.

## I cannot find a Grease Pencil effect

In Frame By Plane 7.1.19, use the **+** button beside the Grease Pencil Effect Stack. Effects are grouped into Stylize, Light & Edge, Warp, Stroke, Motion & Build, Utility and Surface. Select an effect in the list to show only its settings below the stack.

## Stroke and Fill show the same Grease Pencil color

Use Frame By Plane 7.2.0 or later with Blender 5.2. In Draw Mode choose Color Attribute, then select Stroke, Fill or Both. The two Tool Header swatches are independent: `X` swaps them and `Shift+X` samples only Stroke. In Edit Mode, select points or strokes before changing colors; compact chips indicate a mixed selection.

## G moves points instead of toggling Close Gap

That is intentional in Grease Pencil Edit Mode, where `G` remains Blender's native Grab command. The `G` shortcut toggles Close Gap only in Draw Mode. In Edit Mode use the Close Gap icon in the Tool Header.

## Enabling compositor tools changed no rendered output

Frame By Plane 7.2 separates node editing from render activation. Enable **Use Compositor in Render** in the Frame By Plane compositor panel when the managed graph should affect F12 output. Leaving it off preserves the previous render state.

## Timeline jump buttons are missing

Open the jump popover beside the compact playback controls and enable **Jump to Endpoints**, **Jump to Keyframes** or **Jump by Delta**. The same time-synchronization popover is available in Timeline, Dope Sheet, Graph Editor, NLA and Sequencer headers.

## Compositor Safe Repair cancels

Safe Repair intentionally stops before changing the graph when it cannot create a complete primitive snapshot of artist nodes, socket values and links. In 7.1.18 and later, Blender 5.2 color, vector and rotation values are supported. If cancellation continues:

1. Save a copy of the `.blend` file.
2. Open **Project Health** and run the compositor checks.
3. Copy the diagnostic report.
4. Open a GitHub issue with Blender version, operating system and reproduction steps.

## A legacy Blue or White bookmark changes tag after updating

This is intentional in the streamlined 7.1.19 palette. Legacy `BLUE` tags migrate to Cyan; legacy `WHITE` tags migrate to adaptive None, which uses white or black according to the Viewport background. No manual project migration is required.

## The first frame flashes when opening the Scrub Bar

Use Frame By Plane 7.1.17 or later. The Scrub Bar now waits for a deliberate mouse movement before changing the frame, including at Preview Range boundaries.

## Reporting a reproducible bug

Include:

- Frame By Plane version
- Blender version from **Help → About Blender**
- Operating system and CPU architecture
- Exact steps from a factory-startup file when possible
- The Frame By Plane diagnostic report
- A minimal `.blend` file or media sample when it can be shared safely

Use the [GitHub issue tracker](https://github.com/Cre-Pan/Frame-By-Plane/issues) for bug reports and feature requests.
