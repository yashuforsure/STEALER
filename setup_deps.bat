@echo off
setlocal
title setup - python deps
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [x] python PATH me nahi hai - python.org se install karo
    echo     install karte waqt "Add python.exe to PATH" tick karna.
    pause
    exit /b 1
)

echo.
python -c "import sys;print('[*] python',sys.version.split()[0]);print('[*] exe  ',sys.executable)"
echo.
echo [*] installing: pyinstaller
echo.
python -m pip install --upgrade --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo [x] install fail - net / proxy check karo
    pause
    exit /b 1
)

echo.
python -c "import PyInstaller;print('[ok] PyInstaller',PyInstaller.__version__)"
if errorlevel 1 (
    echo [x] install hua par import nahi ho raha - dusra python PATH me ho sakta hai
    pause
    exit /b 1
)

echo.
echo [ok] ho gaya. ab START_HERE.bat kholo.
echo.
pause
exit /b 0
