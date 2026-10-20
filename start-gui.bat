@echo off
cd /d "%~dp0"
py dashboard_gui.py
if errorlevel 1 python dashboard_gui.py
