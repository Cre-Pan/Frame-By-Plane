param(
    [string]$BlenderExecutable = "blender"
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$SourceDirectory = Join-Path $RepositoryRoot "frame_by_plane"
$OutputDirectory = Join-Path $RepositoryRoot "dist"

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

& $BlenderExecutable --command extension build `
    --source-dir $SourceDirectory `
    --output-dir $OutputDirectory `
    --split-platforms

if ($LASTEXITCODE -ne 0) {
    throw "Blender extension build failed with exit code $LASTEXITCODE"
}

Write-Host "Platform packages created in: $OutputDirectory"
