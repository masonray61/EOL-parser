#!/usr/bin/env bash
# =======================================================
# Automated setup and run script for macOS and Linux
# =======================================================

# Exit immediately if a command exits with a non-zero status
set -e

# 1. Check if python3 is available
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed."
    echo "Please install Python 3 from https://www.python.org/downloads/ or via your package manager."
    exit 1
fi

echo "[INFO] Python 3 detected."

# 2. Create and activate a virtual environment if not already present
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

echo "[INFO] Activating virtual environment..."
source .venv/bin/activate

# 3. Install required packages
echo "[INFO] Installing required dependencies..."
pip install --upgrade pip
pip install pandas requests openpyxl

# 4. Ensure data directory exists
mkdir -p data

# 5. Execute the script
echo "[INFO] Running EOL parser..."
python3 eol_parser.py

echo "[DONE] Processing complete. Check the 'data' folder for output files ending in '-parsed.csv'."