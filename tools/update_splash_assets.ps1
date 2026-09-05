param(
    [Parameter(Mandatory = $true)]
    [string]$Artwork
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$source = (Resolve-Path -LiteralPath $Artwork).Path
$assetDirectory = Join-Path $PSScriptRoot '..\frame_by_plane\assets\splash'
$assetDirectory = (Resolve-Path -LiteralPath $assetDirectory).Path
$destination = Join-Path $assetDirectory 'splash_bg_NORMAL.png'
$buttonHashes = @{}
Get-ChildItem -LiteralPath $assetDirectory -Filter 'splash_button_*.png' | ForEach-Object {
    $buttonHashes[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
}

$image = [System.Drawing.Bitmap]::FromFile($source)
try {
    if ($image.Width -ne 903 -or $image.Height -ne 1010) {
        throw "Expected 903x1010 artwork; got $($image.Width)x$($image.Height). Button positions require the original dimensions."
    }
    # These are storage slices for the fallback texture path, not artwork edits.
    # Clone copies the exact pixel rectangle without resampling or compositing.
    $slices = @(
        @{ Name = 'top'; Y = 0; Height = 88 },
        @{ Name = 'upper'; Y = 88; Height = 360 },
        @{ Name = 'lower'; Y = 448; Height = 480 },
        @{ Name = 'footer'; Y = 928; Height = 82 }
    )
    foreach ($slice in $slices) {
        $rect = [System.Drawing.Rectangle]::new(0, $slice.Y, 903, $slice.Height)
        $crop = $image.Clone($rect, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        try {
            $path = Join-Path $assetDirectory "splash_bg_slice_$($slice.Name).png"
            $crop.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally { $crop.Dispose() }
    }
}
finally { $image.Dispose() }

if (-not [string]::Equals($source, $destination, [StringComparison]::OrdinalIgnoreCase)) {
    Copy-Item -LiteralPath $source -Destination $destination -Force
}
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $sourceHash) {
    throw 'The installed splash does not match the supplied PNG.'
}
foreach ($name in $buttonHashes.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $assetDirectory $name) -Algorithm SHA256).Hash -ne $buttonHashes[$name]) {
        throw "Button asset unexpectedly changed: $name"
    }
}
Write-Output "Installed original 903x1010 splash: $sourceHash"
Write-Output 'Regenerated four fallback slices; all button assets unchanged.'
