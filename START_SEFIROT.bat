@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 run_sefirot.py demo
echo.
echo This is a synthetic shadow-mode demonstration. No betting permission.
pause
