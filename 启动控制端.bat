@echo off
chcp 65001 >nul
cd /d "%~dp0tools"
python ogd77_server.py
pause
