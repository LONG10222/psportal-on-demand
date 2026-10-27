@echo off
set "STARPASS_PREVIEW_LAN_HELPER=%~dp0AllowStarPassGamesLan.ps1"
powershell.exe -NoProfile -Command "Start-Process -FilePath powershell.exe -Verb RunAs -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + $env:STARPASS_PREVIEW_LAN_HELPER + [char]34)"
