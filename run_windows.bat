@echo off
:: ====================================================================
:: Nobitex Trading Pro - Windows 1-Click Launcher
:: ====================================================================
chcp 65001 > nul
title Nobitex Trading Pro Dashboard (Windows)
color 0A

echo.
echo  ====================================================================
echo    🚀 Nobitex Trading Pro - Windows Dashboard Launcher
echo  ====================================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on your system!
    echo Please download and install Python 3.8+ from https://www.python.org/
    pause
    exit /b
)

:: Check or create virtual environment
if not exist "venv" (
    echo [INFO] Creating Python virtual environment (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b
    )
)

:: Activate Virtual Environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

:: Install required packages if missing
echo [INFO] Checking dependencies (requests, pandas, numpy, plotly)...
python -c "import requests, pandas, numpy, plotly" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing required packages...
    python -m pip install --upgrade pip
    pip install requests pandas numpy plotly
)

:: Launch the Web Dashboard Backend Server
echo.
echo [SUCCESS] Starting Nobitex Trading Dashboard Server...
echo [INFO] Your browser will open automatically at: http://localhost:8000
echo.

python app.py --port 8000

pause
