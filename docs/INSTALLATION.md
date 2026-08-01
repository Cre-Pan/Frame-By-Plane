# Installation

Frame By Plane 7.1 LTS requires **Blender 5.2.x LTS**. Blender 5.1 and earlier are outside the supported runtime contract.

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
| 64-bit Linux | `linux_x64` |

The universal package contains every supported wheel and is larger. Platform-specific packages are recommended.

Blender's official 5.2.0 release archive and checksum list contain no macOS Intel image. Intel Mac users should remain on a Blender version that still supports their hardware; Frame By Plane 7.1.18 targets Blender 5.2.x and therefore does not ship a `macos_x64` package.

## Updating an existing installation

1. Save the current `.blend` file and close active renders or modal tools.
2. Install the new platform ZIP through **Install from Disk**.
3. Restart Blender if the previous version was enabled during the update.
4. Open **Project Health** when updating an important production file and review the diagnostic result.

Frame By Plane 7.1.18 does not change the project schema and requires no manual data migration.

## Verify the installed version

Open **Edit → Preferences → Get Extensions**, search for **Frame By Plane**, and confirm that the displayed version matches the downloaded release. The add-on supports Blender 5.2.x only.

## Source archives

GitHub automatically adds “Source code (zip)” and “Source code (tar.gz)” to every release. Those archives represent the repository and are not the installable Blender packages.
