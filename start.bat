@echo off
chcp 65001 >nul
REM ZigbeeHUB WebUI Launcher
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
"%VENV_PYTHON%" -m pip install --upgrade pip

REM Install dependencies from pyproject.toml
cd /d "%SCRIPT_DIR%"
"%VENV_PIP%" install -e ".[dev]"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

REM Launch application
"%VENV_PYTHON%" run.py %*
