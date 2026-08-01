# Release process

## 1. Update source and public metadata

- Update `frame_by_plane/blender_manifest.toml`.
- Update `frame_by_plane/constants.py` and `frame_by_plane/support_policy.py`.
- Update `CHANGELOG.md`, `README.md`, user documentation and release notes.
- Confirm that the repository description and GitHub topics describe the current Blender 5.2 image-sequence, Grease Pencil and 2.5D animation scope.
- Run `python tools/verify_repository.py`.

## 2. Run Blender 5.2 regression tests

Use an official Blender **5.2.x LTS** executable:

```bash
python frame_by_plane/tests/run_blender_lts.py \
  --blender /path/to/blender \
  --all
```

The release is not ready unless the generated combined report says `"passed": true`. Preserve the report and logs for the release audit.

## 3. Build platform packages

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

Windows users can run `tools/build_release.ps1`; macOS and Linux users can run `tools/build_release.sh`.
Both scripts normalize ZIP metadata after Blender's build so identical source produces identical SHA-256 hashes.

## 4. Validate unchanged artifacts

- Run Blender's extension validator on every installable ZIP.
- Install the native package on its matching platform when possible.
- Verify clean enable, import, native Grease Pencil effects, save/reopen, render and uninstall.
- Generate SHA-256 checksums after the final files stop changing.
- Do not commit generated ZIP files to normal repository history.

## 5. Publish on GitHub

1. Commit source and documentation to a release branch.
2. Open a pull request and let repository validation complete.
3. Create a semantic tag such as `v7.1.18` after the release commit is merged.
4. Set the release title to `Frame By Plane 7.1.18 LTS`.
5. Paste `release-notes/7.1.18.md` into the GitHub Release.
6. Attach all platform-specific ZIP files and `SHA256SUMS.txt`.
7. Verify the latest-release link, README asset names, repository description, topics and Wiki navigation.
8. Publish the release.

GitHub automatically adds **Source code (zip)** and **Source code (tar.gz)**. Those repository snapshots are not installable Blender extension packages.

## 6. Upload to Blender Extensions with the official API

Create an API token from the Blender Extensions account settings and expose it only to the current PowerShell process:

```powershell
$secureToken = Read-Host "Blender Extensions token" -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $env:BLENDER_EXTENSIONS_TOKEN =
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    Remove-Variable -Name secureToken, tokenPointer
}
```

Run a validation-only pass first. The script locates the five platform-specific ZIPs, verifies their CRC data and generated manifests, validates the 1024-character release-note limit, and sends no request under `-WhatIf`. When present, `release-notes/X.Y.Z-blender-extensions.md` is selected automatically so the complete GitHub notes can remain unchanged; otherwise the script uses `release-notes/X.Y.Z.md`:

```powershell
.\tools\publish_blender_extensions.ps1 `
    -Version 7.1.18 `
    -PackageDirectory .\dist `
    -WhatIf
```

Perform the real upload with the same inputs:

```powershell
.\tools\publish_blender_extensions.ps1 `
    -Version 7.1.18 `
    -PackageDirectory .\dist
```

The command always requires typing `UPLOAD 7.1.18` before it sends the first request. It uses only the official `https://extensions.blender.org/api/v1/extensions/frame_by_plane/versions/upload/` endpoint, never writes or prints the token, requires HTTP 201 plus the documented JSON fields, and stops with a clear error if any platform upload is rejected. Remove the process variable afterwards:

```powershell
Remove-Item Env:BLENDER_EXTENSIONS_TOKEN
```
