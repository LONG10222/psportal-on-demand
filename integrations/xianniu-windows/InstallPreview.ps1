param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$sourceDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$installRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\StarPassXianniuPreview'))
$installDirectory = [IO.Path]::GetFullPath((Join-Path $installRoot '0.1.0'))
if (-not $installDirectory.StartsWith($installRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid installation directory' }
if (Test-Path -LiteralPath $installDirectory) { throw 'Preview version already installed. Use the existing shortcut; no files were overwritten.' }
if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory 'StarPassXianniuPreview.exe'))) { throw 'Extract the entire preview archive first.' }
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $sourceDirectory | Copy-Item -Destination $installDirectory -Recurse
$shortcutRoot = [Environment]::GetFolderPath('Programs')
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut((Join-Path $shortcutRoot 'StarPass Xianniu Preview.lnk'))
$shortcut.TargetPath = Join-Path $installDirectory 'StarPassXianniuPreview.exe'
$shortcut.WorkingDirectory = $installDirectory
$shortcut.Description = 'StarPass Xianniu independent Windows preview'
$shortcut.Save()
Write-Output ('Installed independent preview: ' + $installDirectory)
if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $installDirectory 'StarPassXianniuPreview.exe') -WindowStyle Hidden }
