@echo off
chcp 65001 >nul
REM ZigbeeHUB WebUI Launcher
REM Launches backend server (builds frontend if needed)
title ZigbeeHUB WebUI

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    pause
    exit /b 1
)

REM Create virtual environment if not exists
if not exist "%VENV_PYTHON%" (
    python -m venv "%VENV_DIR%"
    echo [OK] Virtual environment created
)

REM Upgrade pip
"%VENV_PYTHON%" -m pip install --upgrade pip >nul

REM Install dependencies from pyproject.toml
cd /d "%SCRIPT_DIR%"
"%VENV_PIP%" install -e ".[dev]"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

REM Check frontend build
if not exist "%SCRIPT_DIR%static\dist\index.html" (
    echo [WARN] Frontend build not found at static\dist\index.html
    npm --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Node.js/npm not found. Please install Node.js or build manually:
        echo   cd frontend
        echo   npm install
        echo   npm run build
        pause
        exit /b 1
    )
    echo [INFO] Building frontend...
    cd /d "%SCRIPT_DIR%frontend"
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed
        pause
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        echo [ERROR] npm run build failed
        pause
        exit /b 1
    )
    echo [OK] Frontend built
    cd /d "%SCRIPT_DIR%"
)

REM Run Alembic migrations
"%VENV_PYTHON%" -m alembic upgrade head
if errorlevel 1 (
    echo [WARN] Alembic migration failed, continuing anyway...
)

REM Launch application
echo [OK] Starting server...
"%VENV_PYTHON%" run.py %*
