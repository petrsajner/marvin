$ErrorActionPreference = 'Stop'
# Stage exactly the files a release publishes, under the names it publishes them
# with, and check them off against one SHA256SUMS. There used to be a ZIP here as
# well; it held the same two installers and the same manuals, compressed by 0.1%
# because they are compressed already, so every release uploaded about a gigabyte
# of what it had just uploaded separately.
$root = Split-Path $PSScriptRoot -Parent
$version = (Get-Content -LiteralPath (Join-Path $root 'installer\version.txt') -Raw).Trim()
$target = Join-Path $root "dist\release-$version"

$assets = [ordered]@{
    'Marvin-Setup-Minimal.exe' = "dist\Marvin-Setup-$version-Minimal.exe"
    'Marvin-Setup-Full.exe'    = "dist\Marvin-Setup-$version-Full.exe"
    'Marvin-Manual-EN.pdf'     = 'output\pdf\Marvin-Manual-EN.pdf'
    'Marvin-Manual-CS.pdf'     = 'output\pdf\Marvin-Manual-CS.pdf'
    'Marvin-Workspace.jpg'     = 'docs\images\Marvin-Workspace.jpg'
}
foreach ($name in $assets.Keys) {
    $source = Join-Path $root $assets[$name]
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing release file: $($assets[$name])" }
}

if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
New-Item -ItemType Directory -Path $target | Out-Null
foreach ($name in $assets.Keys) {
    # Hard links: the Full installer is about a gigabyte and copying it buys nothing.
    New-Item -ItemType HardLink -Path (Join-Path $target $name) `
        -Target (Join-Path $root $assets[$name]) | Out-Null
}

$checksums = Get-ChildItem -LiteralPath $target -File | Sort-Object Name | ForEach-Object {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.Name
}
$checksums | Set-Content -LiteralPath (Join-Path $target 'SHA256SUMS.txt') -Encoding ascii

Write-Output "Release assets staged in $target"
Get-ChildItem -LiteralPath $target -File | Select-Object Name, Length
