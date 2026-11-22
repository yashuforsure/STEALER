@echo off
setlocal enabledelayedexpansion
title push - STEALER
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
    echo [x] git not found in PATH
    pause
    exit /b 1
)

set "BRANCH=main"
set "MSG=%~1"
if "%MSG%"=="" set "MSG=update %DATE% %TIME%"

echo [*] repo: %CD%
echo [*] staging...
git add -A
if errorlevel 1 goto :fail

git diff --cached --quiet
if errorlevel 1 (
    echo [*] commit: %MSG%
    git commit -m "%MSG%"
    if errorlevel 1 goto :fail
) else (
    echo [=] nothing new to commit
)

echo [*] syncing with origin/%BRANCH%...
git fetch origin %BRANCH% >nul 2>&1
git rev-parse --verify origin/%BRANCH% >nul 2>&1
if errorlevel 1 (
    echo [*] no remote branch yet - first push
) else (
    git pull --rebase --autostash origin %BRANCH%
    if errorlevel 1 (
        echo [x] rebase hit a conflict - resolve by hand, then run this again
        git rebase --abort 2>nul
        goto :fail
    )
)

echo [*] pushing...
git push -u origin %BRANCH%
if errorlevel 1 goto :fail

echo.
echo [ok] pushed to origin/%BRANCH%
git log -1 --oneline
echo.
pause
exit /b 0

:fail
echo.
echo [x] push failed - read the output above
pause
exit /b 1
