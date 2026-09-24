@echo off
setlocal enabledelayedexpansion

REM =======================================================
REM 1. Set working directory to the script's folder
REM =======================================================
cd /d "%~dp0"

REM =======================================================
REM 2. Identify or Locate Python Executable
REM =======================================================
set "PYTHON_CMD="

REM Check if 'python' is in PATH
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :PYTHON_FOUND
)

REM Check if Python Launcher 'py' is in PATH
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py"
    goto :PYTHON_FOUND
)

REM Check default local installation directory
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PYTHON_CMD=%%D\python.exe"
        goto :PYTHON_FOUND
    )
)

REM =======================================================
REM 3. Auto-Download & Silent Install Python if Not Found
REM =======================================================
echo [WARN] Python was not found on this system.
echo [INFO] Automatically downloading and installing Python...

set "PYTHON_VERSION=3.12.3"
set "INSTALLER_NAME=python_installer.exe"
set "DOWNLOAD_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"

REM Download using curl (built into Windows 10/11) or PowerShell
where curl >nul 2>&1
if %errorlevel% equ 0 (
    curl -L -o "%INSTALLER_NAME%" "%DOWNLOAD_URL%"
) else (
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%DOWNLOAD_URL%', '%INSTALLER_NAME%')"
)

if not exist "%INSTALLER_NAME%" (
    echo [ERROR] Failed to download Python installer automatically.
    echo Please install Python manually from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [INFO] Installing Python silently (this may take 1-2 minutes)...
REM /quiet = silent install, InstallAllUsers=0 = installs for current user (no admin required), PrependPath=1 = adds to PATH
"%INSTALLER_NAME%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

REM Clean up installer
del "%INSTALLER_NAME%" >nul 2>&1

REM Detect the newly installed python path directly
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PYTHON_CMD=%%D\python.exe"
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python installation completed, but binary could not be located.
    echo Please restart your computer or command prompt.
    pause
    exit /b 1
)

:PYTHON_FOUND
echo [INFO] Using Python: %PYTHON_CMD%

REM =======================================================
REM 4. Install Required Packages
REM =======================================================
echo [INFO] Checking and installing dependencies (pandas, requests, openpyxl)...
"%PYTHON_CMD%" -m pip install --upgrade pip --quiet
"%PYTHON_CMD%" -m pip install pandas requests openpyxl --quiet

REM =======================================================
REM 5. Ensure Data Directory Exists
REM =======================================================
if not exist "data" (
    echo [INFO] Creating 'data' directory...
    mkdir data
)

REM =======================================================
REM 6. Run the EOL Parser
REM =======================================================
echo [INFO] Running EOL parser...
"%PYTHON_CMD%" eol_parser.py

echo.
echo [DONE] Processing complete. Check the 'data' folder for output files.
pause