@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0START_WINDOWS.ps1"
if errorlevel 1 pause
endlocal
