@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "VERSION_FILE=%~dp0version.txt"
if not exist "%VERSION_FILE%" (
    echo 1.0.0>"%VERSION_FILE%"
)
set /p "VERSION="<"%VERSION_FILE%"
if not defined VERSION set "VERSION=1.0.0"

echo Current Skua Nexus Manager version: !VERSION!
choice /C YN /N /M "Updating version? [Y] Yes - increment patch version  [N] No - keep same version: "
if errorlevel 2 goto build
if errorlevel 1 goto increment

:increment
for /f "tokens=1-3 delims=." %%A in ("!VERSION!") do (
    set /a PATCH=%%C+1
    set "VERSION=%%A.%%B.!PATCH!"
)
> "%VERSION_FILE%" echo !VERSION!
echo Version updated to !VERSION!
goto build

:build
echo Building Skua Nexus Manager version !VERSION!...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-velopack.ps1" -Version "!VERSION!"
if errorlevel 1 (
    echo.
    echo BUILD FAILED. Check the errors above.
) else (
    echo.
    echo BUILD COMPLETED.
)
pause
endlocal
