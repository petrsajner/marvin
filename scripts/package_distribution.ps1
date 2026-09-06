$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$version = (Get-Content -LiteralPath (Join-Path $root 'installer\version.txt') -Raw).Trim()
$name = "Marvin-$version-Windows-x64"
$target = Join-Path $root "dist\$name"
$zip = "$target.zip"
if ((Test-Path -LiteralPath $target) -or (Test-Path -LiteralPath $zip)) {
    throw "Distribution already exists: $target. Use a fresh release version or archive the existing package first."
}
$sources = @(
    "dist\Marvin-Setup-$version-Minimal.exe",
    "dist\Marvin-Setup-$version-Full.exe",
    'output\pdf\Marvin-Manual-EN.pdf',
    'output\pdf\Marvin-Manual-CS.pdf',
    'docs\distribution\INSTALL-EN.md',
    'docs\distribution\INSTALL-CS.md'
)
foreach ($source in $sources) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $source))) { throw "Missing distribution file: $source" }
}
New-Item -ItemType Directory -Path $target | Out-Null
foreach ($source in $sources) { Copy-Item -LiteralPath (Join-Path $root $source) -Destination $target }
$checksums = Get-ChildItem -LiteralPath $target -File | Sort-Object Name | ForEach-Object {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.Name
}
$checksums | Set-Content -LiteralPath (Join-Path $target 'SHA256SUMS.txt') -Encoding ascii
Compress-Archive -Path (Join-Path $target '*') -DestinationPath $zip -CompressionLevel Optimal
Get-Item -LiteralPath $zip | Select-Object FullName, Length
Get-FileHash -LiteralPath $zip -Algorithm SHA256
