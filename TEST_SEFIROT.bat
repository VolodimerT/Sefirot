@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python test_sefirot.py
) else (
  py -3 test_sefirot.py
)
set "SEFIROT_EXIT=%ERRORLEVEL%"
pause
exit /b %SEFIROT_EXIT%
