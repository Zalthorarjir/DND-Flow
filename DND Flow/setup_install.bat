@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title DND Flow Setup Installer
echo ==========================================
echo   DND Flow - Setup and Install
echo ==========================================
echo.

set "BOOTSTRAP_PY="
where py >nul 2>&1
if not errorlevel 1 (
    set "BOOTSTRAP_PY=py -3"
) else (
    where python >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PY=python"
)

if not defined BOOTSTRAP_PY (
    echo [ERROR] Python 3.11+ was not found.
    echo Install Python and ensure either "py" or "python" is available in PATH.
    goto :fail
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating root virtual environment...
    call %BOOTSTRAP_PY% -m venv ".venv"
    if errorlevel 1 goto :fail
) else (
    echo [1/5] Reusing existing root virtual environment...
)

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

echo [2/5] Upgrading pip, setuptools, and wheel...
call "%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :fail

call :install_requirements "Discord_Bot\requirements.txt" "Discord Bot"
call :install_requirements "Online_Web_Server\requirements.txt" "Online Web Server"
call :install_requirements "Offline_Backup_Web_Server\requirements.txt" "Offline Backup Web Server"

echo [4/5] Preparing local environment files...
call :copy_example "Discord_Bot\.env.example" "Discord_Bot\.env"
call :copy_example "Online_Web_Server\.env.example" "Online_Web_Server\.env"
call :copy_example "Offline_Backup_Web_Server\.env.example" "Offline_Backup_Web_Server\.env"

echo [5/5] Ensuring runtime folders exist...
for %%D in (
    "Online_Web_Server\logs"
    "Offline_Backup_Web_Server\logs"
    "Online_Web_Server\static\server_icons"
    "Offline_Backup_Web_Server\static\server_icons"
    "Online_Web_Server\uploads\items"
    "Discord_Bot\databases\Items"
    "Discord_Bot\databases\Users"
) do (
    if not exist "%%~D" mkdir "%%~D"
)

echo.
echo Setup complete.
echo Next steps:
echo   1. Open the generated .env files and add your own local secrets.
echo   2. Start the bot with Discord_Bot\start_bot.bat
echo   3. Start the online dashboard with Online_Web_Server\start.bat
echo   4. Start the offline dashboard with Offline_Backup_Web_Server\start.bat
echo.
echo Keep .env, *.db, *.log, caches, and uploaded assets out of shared exports.
goto :eof

:install_requirements
echo [3/5] Installing %~2 dependencies...
if not exist "%~1" (
    echo [WARN] Missing requirements file: %~1
    goto :eof
)
call "%PYTHON_EXE%" -m pip install -r "%~1"
if errorlevel 1 goto :fail
goto :eof

:copy_example
if exist "%~2" (
    echo    Found existing %~2
    goto :eof
)
if exist "%~1" (
    copy /Y "%~1" "%~2" >nul
    echo    Created %~2 from %~1
) else (
    echo    Skipped missing template %~1
)
goto :eof

:fail
echo.
echo Setup failed. Review the messages above, then rerun after fixing the problem.
exit /b 1
