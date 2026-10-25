@echo off
set "STARPASS_GAMES_PREVIEW_CONFIG=%LOCALAPPDATA%\StarPassGamesPreview\config.json"
start "" "%~dp0PSPortalProxy.exe" --config "%STARPASS_GAMES_PREVIEW_CONFIG%" --page games
