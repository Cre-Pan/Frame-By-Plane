# Frame By Plane troubleshooting for Blender 5.2

## The add-on does not install

Confirm that Blender reports version **5.2.x** and that the downloaded asset matches the computer architecture. Install the ZIP directly through **Edit → Preferences → Get Extensions → Install from Disk**; do not extract it first.

Do not use GitHub's automatically generated **Source code (zip)** file. A valid release asset contains `blender_manifest.toml` at the root and has a platform suffix such as `windows_x64`.

## PSD or Procreate import is unavailable

Use the platform-specific Frame By Plane package. It contains compatible Pillow and psd-tools wheels for the target operating system and CPU. Reinstalling a source archive does not add those native dependencies.

## A Grease Pencil effect appears more than once

Frame By Plane 7.1.18 prevents new unmanaged duplicates on Blender 5.2. If a project was edited with 7.1.17, open the Grease Pencil Effect Stack and use **Repair Duplicates** when the warning appears. The repair removes only effects carrying Frame By Plane ownership metadata and preserves artist-authored effects.

## Grease Pencil effect controls do not stay open or closed

Update to 7.1.18 or later. Blender 5.2 rejects custom-property writes on some native Shader Effect and modifier items; Frame By Plane now persists UI state on the owning Grease Pencil object. Use the stack-header arrows to expand or collapse all active effects.

## Compositor Safe Repair cancels

Safe Repair intentionally stops before changing the graph when it cannot create a complete primitive snapshot of artist nodes, socket values and links. In 7.1.18, Blender 5.2 color, vector and rotation values are supported. If cancellation continues:

1. Save a copy of the `.blend` file.
2. Open **Project Health** and run the compositor checks.
3. Copy the diagnostic report.
4. Open a GitHub issue with Blender version, operating system and reproduction steps.

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
