# Release process

## 1. Update the source

- Update `frame_by_plane/blender_manifest.toml`.
- Update `frame_by_plane/constants.py`.
- Update `CHANGELOG.md` and the release notes.
- Run `python tools/verify_repository.py`.

## 2. Build platform packages

Use Blender 5.1.2 or newer:

```bash
blender --command extension build \
  --source-dir ./frame_by_plane \
  --output-dir ./dist \
  --split-platforms
```

Expected packages:

```text
frame_by_plane-X.Y.Z-windows_x64.zip
frame_by_plane-X.Y.Z-windows_arm64.zip
frame_by_plane-X.Y.Z-macos_x64.zip
frame_by_plane-X.Y.Z-macos_arm64.zip
frame_by_plane-X.Y.Z-linux_x64.zip
```

A universal package can be built without `--split-platforms`, but it is optional for GitHub distribution.

## 3. Test

- Install each package on its matching platform when possible.
- Run the in-addon developer tests and release gate.
- Verify a clean install, import, save/reopen and uninstall.
- Generate SHA-256 checksums for the final unchanged files.

## 4. Publish on GitHub

1. Commit the source and documentation to the default branch.
2. Open **Releases → Draft a new release**.
3. Create a semantic tag such as `v6.1.0`.
4. Set the release title to `Frame By Plane 6.1.0 LTS`.
5. Paste the prepared release notes.
6. Attach every platform-specific ZIP and the checksum file.
7. Save as draft, verify the asset list, then publish.

Do not commit generated release ZIP files into the normal repository history. Attach them to the GitHub Release instead.
