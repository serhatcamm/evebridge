@echo off
title EveBridge
cd /d "%~dp0"

echo Starting EveBridge...
"C:\Python314\python.exe" main_app.py
if errorlevel 1 (
    echo.
    echo EveBridge exited with an error. Press any key to close...
    pause >nul
)
