param(
    [string]$BlenderExecutable = "blender"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$SourceDirectory = Join-Path $RepositoryRoot "frame_by_plane"
$OutputDirectory = Join-Path $RepositoryRoot "dist"

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

& $BlenderExecutable --factory-startup --command extension build `
    --source-dir $SourceDirectory `
    --output-dir $OutputDirectory `
    --split-platforms

if ($LASTEXITCODE -ne 0) {
    throw "Blender extension build failed with exit code $LASTEXITCODE"
}

& $BlenderExecutable --background --factory-startup `
    --python (Join-Path $PSScriptRoot "normalize_release_archives.py") `
    -- $OutputDirectory --manifest (Join-Path $SourceDirectory "blender_manifest.toml")

if ($LASTEXITCODE -ne 0) {
    throw "Release archive normalization failed with exit code $LASTEXITCODE"
}

Write-Host "Deterministic platform packages created in: $OutputDirectory"

& $BlenderExecutable --background --factory-startup --python-exit-code 1 `
    --python (Join-Path $PSScriptRoot "audit_release_packages.py") -- $OutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Release package content audit failed with exit code $LASTEXITCODE"
}
