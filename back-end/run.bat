@echo off
REM =======================================================
REM Automated setup and run script for Windows
REM =======================================================

REM 1. Check if Python is installed and accessible in PATH
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH.
    echo Please download and install Python from https://www.python.org/downloads/
    echo Make sure to check the box: "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

echo [INFO] Python detected. Checking and installing required packages...

REM 2. Install required dependencies
python -m pip install --upgrade pip
python -m pip install pandas requests openpyxl

REM 3. Create the data directory if it does not exist
if not exist "data" (
    echo [INFO] Creating 'data' directory. Place your input files inside it.
    mkdir data
)

REM 4. Run the Python parser
echo [INFO] Running EOL parser...
python eol_parser.py

echo.
echo [DONE] Processing complete. Check the 'data' folder for output files ending in '-parsed.csv'.
pause