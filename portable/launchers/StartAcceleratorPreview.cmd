@echo off
setlocal
set "STARPREVIEWROOT=%LOCALAPPDATA%\StarPassAcceleratorPreview"
if not exist "%STARPREVIEWROOT%" mkdir "%STARPREVIEWROOT%"
if not exist "%STARPREVIEWROOT%\config.json" (
  >"%STARPREVIEWROOT%\config.json" echo {"product_mode":"accelerator","host_relay":"steam","engine_mode":"external","listen_host":"","listen_port":10081,"backend_port":10082,"api_port":10090,"allowed_clients":[],"product_lan_automatic":true,"subscription_url":"","core_path":""}
)
if not exist "%STARPREVIEWROOT%\config.json.ui.json" (
  >"%STARPREVIEWROOT%\config.json.ui.json" echo {"language":"zh","theme":"dark"}
)
start "" "%~dp0PSPortalProxy.exe" --config "%STARPREVIEWROOT%\config.json"
exit /b
