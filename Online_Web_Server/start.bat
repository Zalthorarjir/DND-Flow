@echo off
setlocal EnableExtensions
title Online Web Server

for %%I in ("%~dp0.") do set "SCRIPT_DIR=%%~fI"
cd /d "%SCRIPT_DIR%"

set "LOG_DIR=%SCRIPT_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "CADDY_LOG=%LOG_DIR%\caddy.log"
set "CADDY_ERR=%TEMP%\online_web_server_caddy.err"
set "CADDY_PID_FILE=%TEMP%\online_web_server_caddy.pid"

set "PYTHON_CMD="
if exist "%SCRIPT_DIR%\..\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%SCRIPT_DIR%\..\.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%\venv\Scripts\python.exe" (
    set "PYTHON_CMD=%SCRIPT_DIR%\venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if "%PYTHON_CMD%"=="" (
    echo ERROR: Python not found. Install Python or create a virtual environment.
    pause
    exit /b 1
)

set "CADDY_CMD="
if exist "%SCRIPT_DIR%\tools\caddy\caddy.exe" (
    set "CADDY_CMD=%SCRIPT_DIR%\tools\caddy\caddy.exe"
) else (
    where caddy >nul 2>&1
    if not errorlevel 1 set "CADDY_CMD=caddy"
)

set "USE_CADDY=0"
if defined CADDY_CMD set "USE_CADDY=1"

if "%USE_CADDY%"=="1" if not exist "%SCRIPT_DIR%\Caddyfile" (
    echo ERROR: Caddyfile not found.
    pause
    exit /b 1
)

:restart_loop
call :stop_online_processes >nul 2>&1
cls
echo ========================================
echo   Online Web Server
echo ========================================
echo.
set "CADDY_PID="
if "%USE_CADDY%"=="1" (
    echo Starting Caddy...

    del /q "%CADDY_PID_FILE%" "%CADDY_ERR%" >nul 2>&1
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%CADDY_CMD%' -ArgumentList @('run','--config','%SCRIPT_DIR%\Caddyfile') -WorkingDirectory '%SCRIPT_DIR%' -WindowStyle Hidden -PassThru; [Console]::Out.Write($p.Id)" 1>"%CADDY_PID_FILE%" 2>"%CADDY_ERR%"

    if exist "%CADDY_PID_FILE%" set /p "CADDY_PID="<"%CADDY_PID_FILE%"
    echo %CADDY_PID%| findstr /R "^[0-9][0-9]*$" >nul 2>&1
    if errorlevel 1 set "CADDY_PID="

    if "%CADDY_PID%"=="" (
        echo ERROR: Caddy failed to start.
        if exist "%CADDY_ERR%" type "%CADDY_ERR%"
        goto prompt_restart
    )

    timeout /t 2 /nobreak >nul
    tasklist /FI "PID eq %CADDY_PID%" | find "%CADDY_PID%" >nul
    if errorlevel 1 (
        echo ERROR: Caddy exited immediately. Check %CADDY_LOG%.
        goto prompt_restart
    )

    echo Caddy running (PID %CADDY_PID%).
) else (
    echo WARNING: Caddy was not found in tools\caddy or on PATH.
    echo WARNING: Starting Flask without the reverse proxy / HTTPS layer.
    echo WARNING: Download Caddy locally from https://github.com/caddyserver/caddy/releases if you need HTTPS.
)
echo Starting Flask in this terminal...
echo.
echo Press Ctrl+C to stop the server.
echo After stopping, press Enter to restart or Q to quit.
echo.

"%PYTHON_CMD%" app.py
set "APP_EXIT=%ERRORLEVEL%"

echo.
echo Flask exited with code %APP_EXIT%.
if "%USE_CADDY%"=="1" (
    echo Stopping Caddy...
    call :stop_caddy %CADDY_PID% >nul 2>&1
)

:prompt_restart
echo.
set "CHOICE="
set /p "CHOICE=Press Enter to restart, or type Q then Enter to quit: "
if /I "%CHOICE%"=="Q" exit /b 0
goto restart_loop

:stop_caddy
set "TARGET_PID=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:2019/stop' -Method Post -UseBasicParsing -TimeoutSec 2 | Out-Null } catch {}"
if not "%TARGET_PID%"=="" (
    timeout /t 1 /nobreak >nul
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Stop-Process -Id %TARGET_PID% -Force -ErrorAction Stop } catch {}"
)
taskkill /F /IM caddy.exe >nul 2>&1
exit /b 0

:stop_online_processes
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*Online_Web_Server*app.py*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
call :stop_caddy
exit /b 0
