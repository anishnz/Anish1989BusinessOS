@echo off
REM Double-click this file to start Anish1989 Business OS with Docker.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
echo.
pause
