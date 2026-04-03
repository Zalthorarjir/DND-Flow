@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Offline Backup Web Server

for %%I in ("%~dp0.") do set "SCRIPT_DIR=%%~fI"
cd /d "%SCRIPT_DIR%"

if not exist "%SCRIPT_DIR%\.env" if exist "%SCRIPT_DIR%\.env.example" (
    copy /Y "%SCRIPT_DIR%\.env.example" "%SCRIPT_DIR%\.env" >nul
)

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
    echo ERROR: Python executable not found.
    pause
    exit /b 1
)

:restart_loop
call :stop_offline_processes >nul 2>&1

cls
echo ========================================
echo   Offline Backup Web Server
echo ========================================
echo.
echo [OK] Starting in OFFLINE mode at http://127.0.0.1:5002
echo [OK] Localhost-only backup workflow
echo.
echo Press Ctrl+C to stop the server.
echo After it stops, press Enter to restart or Q to quit.
echo.

"%PYTHON_CMD%" app.py
set "APP_EXIT=!ERRORLEVEL!"

echo.
echo Offline server exited with code !APP_EXIT!.

echo.
set "RESTART_CHOICE="
set /p "RESTART_CHOICE=Press Enter to restart, or type Q then Enter to quit: "
if /I "!RESTART_CHOICE!"=="Q" exit /b 0
goto restart_loop

:stop_offline_processes
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*Offline_Backup_Web_Server*app.py*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
exit /b 0
