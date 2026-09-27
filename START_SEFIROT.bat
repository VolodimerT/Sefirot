@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python sefirot.py demo
) else (
  py -3 sefirot.py demo
)
set "SEFIROT_EXIT=%ERRORLEVEL%"
echo.
if not "%SEFIROT_EXIT%"=="0" echo SEFIROT failed. See error above.
pause
exit /b %SEFIROT_EXIT%
