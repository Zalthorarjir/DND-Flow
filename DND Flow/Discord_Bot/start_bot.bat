@echo off
setlocal enableextensions enabledelayedexpansion

rem Ensure we run from the script directory
cd /d "%~dp0"

echo ========================================
echo Starting DND Flow Bot with NPC System
echo ========================================
echo.

rem Prefer project venv python if present, else fall back to system python
set "PYEXE=.\.venv\Scripts\python.exe"
if not exist .\.venv\Scripts\python.exe (
  set "PYEXE=python"
)

rem Check if .env exists
if not exist .env (
    echo ERROR: .env file not found!
    echo Please copy .env.example to .env and configure it.
    echo.
    pause
    exit /b 1
)

rem Check if Python is available
"%PYEXE%" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.11 and/or create the venv: py -3.11 -m venv .venv
    echo.
    pause
    exit /b 1
)

echo Checking Python packages...
"%PYEXE%" -c "import discord" >nul 2>&1
if errorlevel 1 (
    echo discord.py not detected. Installing requirements...
    "%PYEXE%" -m pip install -r requirements.txt || goto :pipfail
)

"%PYEXE%" -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
    echo aiohttp not detected. Installing requirements...
    "%PYEXE%" -m pip install -r requirements.txt || goto :pipfail
)

echo.
echo Starting bot with %PYEXE% ...
echo Watch for [NPC] logs to see NPC system activity.
echo Press Ctrl+C to stop the bot.
echo.
echo ========================================
echo.

"%PYEXE%" main.py
goto :eof

:pipfail
echo.
echo ERROR: Failed to install Python packages in the selected interpreter.
echo Checked interpreter: %PYEXE%
echo Please ensure internet access and try again.
echo.
pause
exit /b 1
