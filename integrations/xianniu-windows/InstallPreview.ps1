param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$sourceDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$installRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\StarPassXianniuPreview'))
$installDirectory = [IO.Path]::GetFullPath((Join-Path $installRoot '0.1.0'))
if (-not $installDirectory.StartsWith($installRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid installation directory' }
if (Test-Path -LiteralPath $installDirectory) {
    $manifestPath = Join-Path $installDirectory 'build-info.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Existing directory is not a recognized independent preview. Nothing was changed.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if (-not $manifest.local_unsigned_preview -or $manifest.contains_account_data) { throw 'Existing installation manifest is not a matching preview.' }
    $running = @(Get-Process StarPassXianniuPreview -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installDirectory 'StarPassXianniuPreview.exe') })
    if ($running.Count -gt 0) { throw 'Close the StarPass Xianniu preview before updating. Private settings and existing firewall scope are preserved.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory 'StarPassXianniuPreview.exe'))) { throw 'Extract the entire preview archive first.' }
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $sourceDirectory | Copy-Item -Destination $installDirectory -Recurse -Force
$shortcutRoot = [Environment]::GetFolderPath('Programs')
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut((Join-Path $shortcutRoot 'StarPass Xianniu Preview.lnk'))
$shortcut.TargetPath = Join-Path $installDirectory 'StarPassXianniuPreview.exe'
$shortcut.WorkingDirectory = $installDirectory
$shortcut.Description = 'StarPass Xianniu independent Windows preview'
$shortcut.Save()
Write-Output ('Installed independent preview: ' + $installDirectory)
if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $installDirectory 'StarPassXianniuPreview.exe') -WindowStyle Hidden }
