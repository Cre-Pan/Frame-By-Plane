# Installation

Frame By Plane 7.2 requires **Blender 5.2.x LTS**. Blender 5.1 and earlier are outside the supported runtime contract. Version 7.2.0 is initially distributed as a GitHub pre-release for production validation.

## Recommended installation

Download the package matching the computer architecture from the GitHub **Releases** page or install Frame By Plane from Blender Extensions.

In Blender:

1. Open **Edit → Preferences → Get Extensions**.
2. Open the top-right menu.
3. Choose **Install from Disk**.
4. Select the downloaded ZIP without extracting it.
5. Enable Frame By Plane if Blender does not enable it automatically.

## Choosing the correct package

| Platform | Package suffix |
|---|---|
| Standard Windows PC | `windows_x64` |
| Windows ARM device | `windows_arm64` |
| Apple Silicon Mac | `macos_arm64` |
| Intel Mac | `macos_x64` |
| 64-bit Linux | `linux_x64` |

The universal package contains every supported wheel and is larger. Platform-specific packages are recommended.

The Intel package remains available for compatible Blender 5.2 x64 installations. Blender's official 5.2.0 checksum list currently contains only a macOS ARM64 image, so `macos_x64` is structurally validated but cannot be smoke-tested against an official 5.2.0 Intel distribution in the release gate.

## Updating an existing installation

1. Save the current `.blend` file and close active renders or modal tools.
2. Install the new platform ZIP through **Install from Disk**.
3. Restart Blender if the previous version was enabled during the update.
4. Open **Project Health** when updating an important production file and review the diagnostic result.

Frame By Plane 7.2.0 does not change the project schema and requires no manual migration. Legacy White Scrub Bar bookmarks become adaptive None tags, while legacy Blue tags become Cyan automatically. Grease Pencil dual Stroke/Fill state is runtime-managed and does not rewrite old drawings when the add-on is enabled.

## Verify the installed version

Open **Edit → Preferences → Get Extensions**, search for **Frame By Plane**, and confirm that the displayed version matches the downloaded release. The add-on supports Blender 5.2.x only.

## Source archives

GitHub automatically adds “Source code (zip)” and “Source code (tar.gz)” to every release. Those archives represent the repository and are not the installable Blender packages.
