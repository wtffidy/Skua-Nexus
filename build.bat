@echo off
setlocal
cd /d "%~dp0"

set "VERSION=1.0.0"
set /p "VERSION=Enter Skua Nexus Manager version [%VERSION%]: "
if not defined VERSION set "VERSION=1.0.0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-velopack.ps1" -Version "%VERSION%"
if errorlevel 1 (
    echo.
    echo BUILD FAILED. Check the errors above.
) else (
    echo.
    echo BUILD COMPLETED.
)
pause
endlocal
