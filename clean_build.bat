@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ================================================
echo   EVE-NG Lab Automation - Cleanup Utility
echo ================================================
echo   Working folder: %cd%
echo.
echo Use this if you can't delete/move dist\EVE-NG-Lab-Automation.exe
echo and Windows says "permission denied" or "access is denied".
echo.
echo That almost always means one of:
echo   1. The app is still running (check Task Manager)
echo   2. Windows Defender / your antivirus is still scanning the freshly
echo      built .exe (very common right after PyInstaller creates a large
echo      new executable - the lock usually releases itself within a
echo      few seconds to about a minute)
echo   3. The dist folder is open in a File Explorer window
echo.

echo [1/3] Closing any running copy of the app...
taskkill /f /im "EVE-NG-Lab-Automation.exe" >nul 2>nul
timeout /t 2 /nobreak >nul

echo [2/3] Waiting a moment in case antivirus still has the file open...
timeout /t 5 /nobreak >nul

echo [3/3] Attempting to remove build artifacts...
set REMOVED_OK=1
if exist build (
    rmdir /s /q build >nul 2>nul
    if exist build set REMOVED_OK=0
)
if exist dist (
    for /l %%i in (1,1,8) do (
        if exist dist (
            rmdir /s /q dist >nul 2>nul
            timeout /t 2 /nobreak >nul
        )
    )
    if exist dist set REMOVED_OK=0
)

echo.
if "%REMOVED_OK%"=="1" (
    echo Done - build\ and dist\ removed successfully.
) else (
    echo Could not fully remove build\ and/or dist\ yet.
    echo.
    echo Things to try:
    echo   - Open Task Manager and confirm no "EVE-NG-Lab-Automation.exe" or
    echo     "python.exe" process is still running, then run this script again
    echo   - Temporarily add the dist\ folder to your antivirus's exclusion
    echo     list if this happens on every build
    echo   - Close any Explorer window, preview pane, or terminal with a path
    echo     inside dist\ open
    echo   - As a last resort, restart your PC ^(releases any stuck file lock^)
)
echo.
pause
