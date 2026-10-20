@echo off
cd /d "%~dp0"
py relay.py || python relay.py
pause
