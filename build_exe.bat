@echo off
setlocal enabledelayedexpansion

REM Always operate from the folder this script lives in, regardless of how/where
REM it was launched from (a desktop shortcut, a different cmd working directory,
REM etc.) — otherwise relative paths like requirements.txt below can't be found
REM even though the file is right there next to this script.
cd /d "%~dp0"

echo ================================================
echo   EVE-NG Lab Automation - One-Click EXE Build
echo ================================================
echo   Working folder: %cd%
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.10+ from https://python.org ^(check "Add to PATH" during install^) and try again.
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found in: %cd%
    echo Make sure build_exe.bat is sitting in the same folder as main_app.py,
    echo requirements.txt, eve_ng_lab_automation.spec, and icon.ico ^(i.e. you have
    echo the full project folder, not just this one script^), then try again.
    pause
    exit /b 1
)

echo [1/5] Installing/upgrading required packages...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install app dependencies. Check your internet connection and try again.
    pause
    exit /b 1
)

python -m pip install "pyinstaller>=6.0"
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo [2/5] Closing any running copy of the app so its .exe isn't locked...
REM If EVE-NG-Lab-Automation.exe is still running from a previous build, PyInstaller
REM can't overwrite it (Windows locks running executables) and the build fails with
REM "PermissionError: [WinError 5] Access is denied". Close it here so that can't happen.
taskkill /f /im "EVE-NG-Lab-Automation.exe" >nul 2>nul
timeout /t 2 /nobreak >nul

echo.
echo [3/5] Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist (
    REM Retry a few times in case Explorer, an antivirus scan, or the OS itself
    REM still briefly holds a handle on the old .exe right after it was closed.
    for /l %%i in (1,1,5) do (
        if exist dist (
            rmdir /s /q dist >nul 2>nul
            timeout /t 1 /nobreak >nul
        )
    )
)
if exist dist (
    echo.
    echo [ERROR] Could not remove the old "dist" folder ^(it may still be open in
    echo Explorer, or a security tool has it locked^). Close any windows showing
    echo dist\EVE-NG-Lab-Automation.exe, make sure the app itself isn't running,
    echo then run this script again.
    pause
    exit /b 1
)

echo.
echo [4/5] Building EVE-NG-Lab-Automation.exe with PyInstaller...
if not exist "eve_ng_lab_automation.spec" (
    echo [ERROR] eve_ng_lab_automation.spec not found in: %cd%
    echo It should be in the same folder as this script. Re-download the full
    echo project folder and try again.
    pause
    exit /b 1
)
echo       ^(this can take a few minutes the first time^)
python -m PyInstaller eve_ng_lab_automation.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Scroll up for details.
    echo If you saw a "PermissionError" / "Access is denied" mentioning the .exe:
    echo   - Make sure EVE-NG-Lab-Automation.exe is not running ^(check Task Manager^)
    echo   - Close any Explorer window or antivirus scan that might have it open
    echo   - Try running this script as Administrator
    pause
    exit /b 1
)

echo.
echo [5/5] Done!
echo.
echo Your standalone executable is at:
echo     dist\EVE-NG-Lab-Automation.exe
echo.
echo You can copy just that one file anywhere (a USB stick, another PC, a
echo shared folder) and run it directly - no Python install needed on the
echo target machine.
echo.
pause
