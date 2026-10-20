@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0dashboard_gui.py"
    exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0dashboard_gui.py"
    exit /b 0
)
echo Could not find pyw.exe or pythonw.exe. Install Python from python.org with the Python Launcher enabled.
pause
