<#
.SYNOPSIS
Validates and uploads Frame By Plane release packages through the official
Blender Extensions API.

.DESCRIPTION
Finds platform-specific ZIP packages, validates their manifests and contents,
loads the bearer token only from BLENDER_EXTENSIONS_TOKEN, and requires an
explicit typed confirmation before sending any request. Use -WhatIf for a full
local validation without an upload.

.EXAMPLE
.\tools\publish_blender_extensions.ps1 -Version 7.1.18 -PackageDirectory .\dist -WhatIf

.EXAMPLE
.\tools\publish_blender_extensions.ps1 -Version 7.1.18 -PackageDirectory .\dist
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "7.1.18",

    [ValidateSet("all", "linux_x64", "macos_arm64", "windows_arm64", "windows_x64")]
    [string]$Platform = "all",

    [string]$PackageDirectory,

    [string]$ReleaseNotesPath,

    [ValidatePattern("^[a-z0-9_]+$")]
    [string]$ExtensionId = "frame_by_plane",

    [ValidateRange(30, 3600)]
    [int]$TimeoutSeconds = 600
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$IsValidationOnly = [bool]$WhatIfPreference
# Common -WhatIf propagates to nested cmdlets such as Get-FileHash. Preserve
# the caller's intent, then disable propagation so the validation still runs.
$WhatIfPreference = $false

# Official API schema:
# https://extensions.blender.org/api/v1/swagger/
# POST /api/v1/extensions/{extension_id}/versions/upload/
$ApiOrigin = [Uri]"https://extensions.blender.org"
$ExpectedPlatforms = @(
    "linux_x64",
    "macos_arm64",
    "windows_arm64",
    "windows_x64"
)

function Get-UniqueExistingDirectory {
    param([string[]]$Paths)

    $seen = @{}
    foreach ($path in $Paths) {
        if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path -LiteralPath $path -PathType Container)) {
            continue
        }
        $resolved = (Resolve-Path -LiteralPath $path).Path
        $key = $resolved.ToLowerInvariant()
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $resolved
        }
    }
}

function Get-PackageSearchDirectory {
    param(
        [string]$RepositoryRoot,
        [string]$ExplicitDirectory
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitDirectory)) {
        if (-not (Test-Path -LiteralPath $ExplicitDirectory -PathType Container)) {
            throw "Package directory does not exist: $ExplicitDirectory"
        }
        return ,(Resolve-Path -LiteralPath $ExplicitDirectory).Path
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add((Get-Location).Path)
    $ancestor = [IO.DirectoryInfo]$RepositoryRoot
    for ($depth = 0; $depth -lt 4 -and $null -ne $ancestor; $depth++) {
        foreach ($name in @("dist", "outputs", "release", "build")) {
            $candidates.Add((Join-Path $ancestor.FullName $name))
        }
        $ancestor = $ancestor.Parent
    }

    $directories = @(Get-UniqueExistingDirectory -Paths $candidates.ToArray())
    if ($directories.Count -eq 0) {
        throw "No package directories were found. Pass -PackageDirectory explicitly."
    }
    return $directories
}

function Get-TomlStringValue {
    param(
        [string]$Text,
        [string]$Name
    )

    $pattern = '(?m)^\s*' + [regex]::Escape($Name) + '\s*=\s*"(?<value>[^"]+)"\s*$'
    $match = [regex]::Match($Text, $pattern)
    if (-not $match.Success) {
        throw "Manifest field '$Name' was not found."
    }
    return $match.Groups["value"].Value
}

function Get-GeneratedManifestPlatforms {
    param([string]$ManifestText)

    $section = [regex]::Match(
        $ManifestText,
        '(?ms)^\s*\[build\.generated\]\s*(?<body>.*?)(?=^\s*\[|\z)'
    )
    if (-not $section.Success) {
        throw "The package manifest has no [build.generated] section. Use a ZIP built by Blender with --split-platforms."
    }
    $list = [regex]::Match(
        $section.Groups["body"].Value,
        '(?ms)^\s*platforms\s*=\s*\[(?<items>.*?)\]'
    )
    if (-not $list.Success) {
        throw "The generated package manifest does not declare its platform."
    }
    return @(
        [regex]::Matches($list.Groups["items"].Value, '"(?<value>[^"]+)"') |
            ForEach-Object { $_.Groups["value"].Value }
    )
}

function Test-ReleasePackage {
    param(
        [IO.FileInfo]$Package,
        [string]$ExpectedExtensionId,
        [string]$ExpectedVersion,
        [string]$ExpectedPlatform
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = $null
    try {
        $archive = [IO.Compression.ZipFile]::OpenRead($Package.FullName)
        $manifestEntry = $archive.Entries |
            Where-Object { $_.FullName -eq "blender_manifest.toml" } |
            Select-Object -First 1
        if ($null -eq $manifestEntry) {
            throw "Archive does not contain blender_manifest.toml at its root."
        }

        # Fully read every entry so corrupt ZIP data is rejected before upload.
        foreach ($entry in $archive.Entries) {
            if ([string]::IsNullOrEmpty($entry.Name)) {
                continue
            }
            $entryStream = $null
            try {
                $entryStream = $entry.Open()
                $entryStream.CopyTo([IO.Stream]::Null)
            }
            finally {
                if ($null -ne $entryStream) {
                    $entryStream.Dispose()
                }
            }
        }

        $reader = $null
        try {
            $reader = New-Object IO.StreamReader($manifestEntry.Open(), [Text.Encoding]::UTF8, $true)
            $manifest = $reader.ReadToEnd()
        }
        finally {
            if ($null -ne $reader) {
                $reader.Dispose()
            }
        }

        $manifestId = Get-TomlStringValue -Text $manifest -Name "id"
        $manifestVersion = Get-TomlStringValue -Text $manifest -Name "version"
        $generatedPlatforms = @(Get-GeneratedManifestPlatforms -ManifestText $manifest)
        $expectedManifestPlatform = $ExpectedPlatform.Replace("_", "-")

        if ($manifestId -cne $ExpectedExtensionId) {
            throw "Manifest id '$manifestId' does not match '$ExpectedExtensionId'."
        }
        if ($manifestVersion -cne $ExpectedVersion) {
            throw "Manifest version '$manifestVersion' does not match '$ExpectedVersion'."
        }
        if ($generatedPlatforms.Count -ne 1 -or $generatedPlatforms[0] -cne $expectedManifestPlatform) {
            throw "Generated platform '$($generatedPlatforms -join ', ')' does not match '$expectedManifestPlatform'."
        }
    }
    catch {
        throw "Invalid release package '$($Package.FullName)': $($_.Exception.Message)"
    }
    finally {
        if ($null -ne $archive) {
            $archive.Dispose()
        }
    }
}

function Find-ReleasePackage {
    param(
        [string[]]$SearchDirectories,
        [string]$ExpectedExtensionId,
        [string]$ExpectedVersion,
        [string]$ExpectedPlatform
    )

    $fileName = "$ExpectedExtensionId-$ExpectedVersion-$ExpectedPlatform.zip"
    $matches = New-Object System.Collections.Generic.List[IO.FileInfo]
    $seen = @{}
    foreach ($directory in $SearchDirectories) {
        $candidate = Join-Path $directory $fileName
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $item = Get-Item -LiteralPath $candidate
        $key = $item.FullName.ToLowerInvariant()
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $matches.Add($item)
        }
    }

    if ($matches.Count -eq 0) {
        throw "Package '$fileName' was not found in: $($SearchDirectories -join '; ')"
    }

    if ($matches.Count -gt 1) {
        $hashes = @($matches | ForEach-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash })
        if (@($hashes | Sort-Object -Unique).Count -ne 1) {
            throw "Multiple different copies of '$fileName' were found. Pass -PackageDirectory to select one explicitly."
        }
        Write-Host "Found identical copies of $fileName; using $($matches[0].DirectoryName)"
    }

    $package = $matches[0]
    Test-ReleasePackage `
        -Package $package `
        -ExpectedExtensionId $ExpectedExtensionId `
        -ExpectedVersion $ExpectedVersion `
        -ExpectedPlatform $ExpectedPlatform
    return $package
}

function Protect-SecretInText {
    param(
        [AllowEmptyString()][string]$Text,
        [string]$Secret
    )

    if ([string]::IsNullOrEmpty($Text)) {
        return ""
    }
    if (-not [string]::IsNullOrEmpty($Secret)) {
        return $Text.Replace($Secret, "[REDACTED]")
    }
    return $Text
}

function Format-ApiError {
    param(
        [AllowEmptyString()][string]$Body,
        [string]$Secret
    )

    $safeBody = Protect-SecretInText -Text $Body -Secret $Secret
    if ([string]::IsNullOrWhiteSpace($safeBody)) {
        return "The API returned an empty response body."
    }
    try {
        $json = $safeBody | ConvertFrom-Json
        return ($json | ConvertTo-Json -Depth 12 -Compress)
    }
    catch {
        if ($safeBody.Length -gt 4096) {
            return $safeBody.Substring(0, 4096) + "..."
        }
        return $safeBody
    }
}

function Invoke-OfficialBlenderUpload {
    param(
        [IO.FileInfo]$Package,
        [string]$Notes,
        [string]$Token,
        [Uri]$UploadUri,
        [int]$RequestTimeoutSeconds
    )

    Add-Type -AssemblyName System.Net.Http
    $client = $null
    $multipart = $null
    $response = $null
    try {
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromSeconds($RequestTimeoutSeconds)
        $client.DefaultRequestHeaders.Authorization =
            [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)

        $multipart = [System.Net.Http.MultipartFormDataContent]::new()
        $fileStream = [IO.File]::OpenRead($Package.FullName)
        $fileContent = [System.Net.Http.StreamContent]::new($fileStream)
        $fileContent.Headers.ContentType =
            [System.Net.Http.Headers.MediaTypeHeaderValue]::new("application/zip")
        $multipart.Add($fileContent, "version_file", $Package.Name)

        $notesContent = [System.Net.Http.StringContent]::new($Notes, [Text.Encoding]::UTF8)
        $multipart.Add($notesContent, "release_notes")

        $response = $client.PostAsync($UploadUri, $multipart).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Reason = [string]$response.ReasonPhrase
            Body = [string]$body
        }
    }
    catch {
        $safeMessage = Protect-SecretInText -Text $_.Exception.Message -Secret $Token
        throw "Official Blender Extensions API request failed: $safeMessage"
    }
    finally {
        if ($null -ne $response) {
            $response.Dispose()
        }
        if ($null -ne $multipart) {
            # Disposes the file content and its underlying file stream as well.
            $multipart.Dispose()
        }
        if ($null -ne $client) {
            $client.Dispose()
        }
    }
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$searchDirectories = @(
    Get-PackageSearchDirectory `
        -RepositoryRoot $repositoryRoot `
        -ExplicitDirectory $PackageDirectory
)

if ([string]::IsNullOrWhiteSpace($ReleaseNotesPath)) {
    $blenderReleaseNotesPath = Join-Path $repositoryRoot "release-notes\$Version-blender-extensions.md"
    $canonicalReleaseNotesPath = Join-Path $repositoryRoot "release-notes\$Version.md"
    $ReleaseNotesPath = if (Test-Path -LiteralPath $blenderReleaseNotesPath -PathType Leaf) {
        $blenderReleaseNotesPath
    }
    else {
        $canonicalReleaseNotesPath
    }
}
if (-not (Test-Path -LiteralPath $ReleaseNotesPath -PathType Leaf)) {
    throw "Release notes file does not exist: $ReleaseNotesPath"
}
$resolvedReleaseNotesPath = (Resolve-Path -LiteralPath $ReleaseNotesPath).Path
$releaseNotes = [IO.File]::ReadAllText($resolvedReleaseNotesPath, [Text.Encoding]::UTF8).Trim()
if ([string]::IsNullOrWhiteSpace($releaseNotes)) {
    throw "Release notes are empty: $resolvedReleaseNotesPath"
}
if ($releaseNotes.Length -gt 1024) {
    throw "Release notes contain $($releaseNotes.Length) characters; the official API limit is 1024."
}

$platformsToUpload = if ($Platform -eq "all") { $ExpectedPlatforms } else { @($Platform) }
$packages = @(
    foreach ($platformName in $platformsToUpload) {
        Find-ReleasePackage `
            -SearchDirectories $searchDirectories `
            -ExpectedExtensionId $ExtensionId `
            -ExpectedVersion $Version `
            -ExpectedPlatform $platformName
    }
)

$token = [Environment]::GetEnvironmentVariable("BLENDER_EXTENSIONS_TOKEN", "Process")
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "BLENDER_EXTENSIONS_TOKEN is not set in the current process environment."
}

try {
    $escapedExtensionId = [Uri]::EscapeDataString($ExtensionId)
    $uploadUri = [Uri]::new($ApiOrigin, "/api/v1/extensions/$escapedExtensionId/versions/upload/")

    Write-Host "Blender Extensions upload plan"
    Write-Host "  Official endpoint: $uploadUri"
    Write-Host "  Extension id:     $ExtensionId"
    Write-Host "  Version:          $Version"
    Write-Host "  Release notes:    $resolvedReleaseNotesPath ($($releaseNotes.Length)/1024 characters)"
    Write-Host "  Packages:"
    foreach ($package in $packages) {
        $hash = (Get-FileHash -LiteralPath $package.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $sizeMiB = [Math]::Round($package.Length / 1MB, 2)
        Write-Host "    - $($package.Name) ($sizeMiB MiB, SHA-256 $hash)"
    }

    if ($IsValidationOnly) {
        Write-Host "WhatIf: validation completed; no API request was sent."
        return
    }

    $requiredConfirmation = "UPLOAD $Version"
    $confirmation = Read-Host "Type '$requiredConfirmation' to upload $($packages.Count) package(s); anything else cancels"
    if ($confirmation -cne $requiredConfirmation) {
        Write-Warning "Upload cancelled. No API request was sent."
        return
    }

    if (-not $PSCmdlet.ShouldProcess(
        "$ExtensionId $Version on extensions.blender.org",
        "Upload $($packages.Count) validated platform package(s)"
    )) {
        Write-Warning "Upload cancelled by PowerShell confirmation handling."
        return
    }

    $uploaded = New-Object System.Collections.Generic.List[string]
    foreach ($package in $packages) {
        Write-Host "Uploading $($package.Name)..."
        $result = Invoke-OfficialBlenderUpload `
            -Package $package `
            -Notes $releaseNotes `
            -Token $token `
            -UploadUri $uploadUri `
            -RequestTimeoutSeconds $TimeoutSeconds

        if ($result.StatusCode -ne 201) {
            $details = Format-ApiError -Body $result.Body -Secret $token
            $completed = if ($uploaded.Count -gt 0) { $uploaded -join ", " } else { "none" }
            throw "Upload rejected for '$($package.Name)' with HTTP $($result.StatusCode) $($result.Reason). API response: $details. Packages uploaded before this error: $completed"
        }

        try {
            $responseJson = $result.Body | ConvertFrom-Json
        }
        catch {
            throw "Upload returned HTTP 201 for '$($package.Name)' but the response was not valid JSON."
        }

        $messageProperty = $responseJson.PSObject.Properties["message"]
        $extensionProperty = $responseJson.PSObject.Properties["extension_id"]
        $fileProperty = $responseJson.PSObject.Properties["version_file"]
        if (
            $null -eq $messageProperty -or
            $null -eq $extensionProperty -or
            $null -eq $fileProperty -or
            [string]$messageProperty.Value -cne "Extension version uploaded successfully!" -or
            [string]$extensionProperty.Value -cne $ExtensionId -or
            [string]$fileProperty.Value -cne $package.Name
        ) {
            $safeResponse = Format-ApiError -Body $result.Body -Secret $token
            throw "Upload returned HTTP 201 but an unexpected response for '$($package.Name)': $safeResponse"
        }

        $uploaded.Add($package.Name)
        Write-Host "Uploaded successfully: $($package.Name)"
    }

    Write-Host "Blender Extensions upload completed successfully for $ExtensionId $Version."
    Write-Host "Uploaded packages: $($uploaded -join ', ')"
}
finally {
    # Do not persist the token in files, logs, command-line arguments or output.
    $token = $null
    Remove-Variable token -ErrorAction SilentlyContinue
}
