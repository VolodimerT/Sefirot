@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "tests\" (
    echo ERROR: tests folder is missing. Extract the entire project archive first.
    pause
    exit /b 1
)
py -3 "%~dp0test_sefirot.py"
set "SEFIROT_TEST_EXIT=%ERRORLEVEL%"
echo.
if %SEFIROT_TEST_EXIT% EQU 0 (echo Tests passed.) else (echo Tests failed. Exit code: %SEFIROT_TEST_EXIT%)
pause
exit /b %SEFIROT_TEST_EXIT%
