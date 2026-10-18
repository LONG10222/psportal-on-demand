@echo off
setlocal
cd /d "%~dp0\.."
py -3 -m portalproxy.desktop %*
if errorlevel 1 (
  echo.
  echo Launch failed. Install Python 3.10 or later with Tcl/Tk from python.org.
  pause
)
