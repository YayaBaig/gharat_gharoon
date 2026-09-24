@echo off
title Nobitex Trading Pro Dashboard (Windows)
color 0A

echo ====================================================================
echo   Nobitex Trading Pro - Windows Dashboard Launcher
echo ====================================================================

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on your system!
    echo Please install Python 3.8+ from https://www.python.org/
    pause
    exit /b 1
)

if not exist venv (
    echo [INFO] Creating Python virtual environment...
    python -m venv venv
)

echo [INFO] Activating virtual environment...
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

echo [INFO] Checking dependencies...
python -c "import requests, pandas, numpy, plotly" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing required packages...
    python -m pip install --upgrade pip
    pip install requests pandas numpy plotly
)

echo.
echo [SUCCESS] Starting Nobitex Trading Dashboard Server
echo [INFO] Open in your browser: http://localhost:8000
echo.

python app.py --port 8000
pause
