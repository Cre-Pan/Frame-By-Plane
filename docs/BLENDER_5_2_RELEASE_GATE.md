# Blender 5.2 native release gate

The `Blender 5.2 native release gate` workflow turns the residual platform risk from the 7.1.18 audit into an explicit pre-publication check.

## When it runs

- manually through **Actions → Blender 5.2 native release gate → Run workflow**;
- on a `v*` tag;
- on a pull request only when the `release-gate` label is present; adding the label or pushing another commit triggers the matrix.

The workflow is intentionally not run for every commit because each native job downloads a complete Blender distribution and builds all split-platform archives.

## Native matrix

| Package platform | GitHub runner | Blender archive |
| --- | --- | --- |
| Linux x64 | `ubuntu-24.04` | `blender-5.2.0-linux-x64.tar.xz` |
| macOS ARM64 | `macos-15` | `blender-5.2.0-macos-arm64.dmg` |
| Windows ARM64 | `windows-11-arm` | `blender-5.2.0-windows-arm64.zip` |
| Windows x64 | `windows-2025` | `blender-5.2.0-windows-x64.zip` |

`windows-11-arm` is a GitHub public-preview runner. Runner availability and billing depend on repository visibility and account plan; an unavailable runner is a failed/incomplete release gate, not an implicit pass. Current labels are documented in the [GitHub-hosted runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

The official Blender 5.2.0 checksum listing contains a macOS ARM64 image but no macOS x64 image. The release surface therefore excludes `macos_x64` instead of claiming runtime coverage that cannot be reproduced with an official Blender build. The source of truth is Blender's [official SHA-256 listing](https://download.blender.org/release/Blender5.2/blender-5.2.0.sha256).

## Checks per platform

Each job:

1. downloads Blender only from `download.blender.org`;
2. downloads Blender's official `blender-5.2.0.sha256` listing;
3. requires an exact filename match and SHA-256 match before extraction;
4. runs the static repository verifier;
5. builds deterministic split-platform packages with Blender;
6. validates the package matching the native runner;
7. runs the complete native background regression suite;
8. installs and enables that package in an isolated Blender user profile;
9. creates an FBP scene and verifies save/reopen;
10. starts a transaction before real File Open, File Revert and New File and verifies no orphan owner or partial data;
11. uploads the JSON/log/Blend evidence and native ZIP for 14 days.

Test reports use an absolute directory below `runner.temp`. This keeps Windows transaction-manifest paths below legacy path-length limits and prevents Blender's changed working directory from separating a report from the launcher that verifies it.

Linux x64 additionally runs the interactive suite under Xvfb, including two-window contention, 20 Undo/Redo cycles and 300 Layer Tree/Grease Pencil redraws.

## Release rule

A public release should require all four matrix jobs to pass. `extension validate` alone is insufficient: it checks package structure, while the matrix exercises the package on its declared OS/architecture.

The workflow never uploads to GitHub Releases or Blender Extensions. Publication remains a separate manual action with its own confirmation and token handling.
