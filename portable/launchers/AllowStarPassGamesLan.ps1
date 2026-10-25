param([switch]$Remove, [string]$SettingsPath = (Join-Path $env:LOCALAPPDATA 'StarPassXianniuPreview\lan-access.json'))
$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path (Split-Path -Parent $SettingsPath) 'lan-rule-result.json'
$created = @()
try {
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this helper as administrator. It only manages the two named StarPass preview rules.' }
$ruleNames = @('StarPassGamesPreview-TCP','StarPassGamesPreview-UDP')
if ($Remove) {
    foreach ($ruleName in $ruleNames) { Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
    Write-Output 'Removed only the two StarPass Xianniu preview rules.'
    exit 0
}
$programPath = Join-Path $PSScriptRoot 'PSPortalProxy.exe'
if (-not (Test-Path -LiteralPath $programPath)) { throw 'Run this helper from the complete installed preview folder.' }
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$localIP = [Net.IPAddress]::Parse($settings.listen_host)
if ($localIP.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or $localIP.ToString() -eq '127.0.0.1') { throw 'Select the real LAN IPv4 in preview settings first.' }
if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $localIP.ToString() -ErrorAction SilentlyContinue)) { throw 'The saved LAN IPv4 is no longer on this computer.' }
$remoteIPs = @($settings.devices | ForEach-Object {
    $address = [Net.IPAddress]::Parse($_)
    $bytes = $address.GetAddressBytes()
    if ($address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or -not ($bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or ($bytes[0] -eq 192 -and $bytes[1] -eq 168))) { throw 'Only explicitly selected private IPv4 clients are allowed.' }
    $address.ToString()
})
if ($remoteIPs.Count -lt 1 -or $remoteIPs.Count -gt 32) { throw 'Select 1 to 32 LAN devices in the preview first.' }
$ports = @([int]$settings.http_port,[int]$settings.socks_port)
if ($ports[0] -lt 1024 -or $ports[0] -gt 65535 -or $ports[1] -lt 1024 -or $ports[1] -gt 65535 -or $ports[0] -eq $ports[1]) { throw 'Invalid listener ports.' }
# Public profile is deliberately excluded. UDP uses dynamic association ports,
# restricted to this exact program, local IP and explicitly selected source IPs.
foreach ($ruleName in $ruleNames) {
    if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) { throw 'Existing preview rules found. Remove them with -Remove before changing scope.' }
}
    New-NetFirewallRule -Name $ruleNames[0] -DisplayName 'StarPass Xianniu Preview TCP (selected LAN clients)' -Direction Inbound -Action Allow -Profile Private -Program $programPath -LocalAddress $localIP.ToString() -RemoteAddress $remoteIPs -Protocol TCP -LocalPort $ports | Out-Null
    $created += $ruleNames[0]
    New-NetFirewallRule -Name $ruleNames[1] -DisplayName 'StarPass Xianniu Preview UDP (selected LAN clients)' -Direction Inbound -Action Allow -Profile Private -Program $programPath -LocalAddress $localIP.ToString() -RemoteAddress $remoteIPs -Protocol UDP | Out-Null
    $created += $ruleNames[1]
    @{ success = $true; rules = $created; profile = 'Private' } | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Write-Output 'Enabled only this preview program for the selected clients on Private networks.'
} catch {
    foreach ($ruleName in $created) { Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
    @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    throw
}
