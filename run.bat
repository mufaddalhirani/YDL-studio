@echo off
title YDL Studio
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo Starting YDL Studio...
"%PY%" -m ydl_studio
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo YDL Studio stopped with an error.
    echo Install the dependencies first:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
)
