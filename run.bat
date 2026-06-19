@echo off
setlocal

cd /d "%~dp0"
echo.
echo ============================================================
echo   PolyPDF - Run (Development)
echo ============================================================
echo.
echo This script will:
echo   1) Create a Python virtual environment (.venv)
echo   2) Install PyQt6 and PyMuPDF (~100 MB on first run)
echo   3) Launch the viewer
echo.
echo First run takes 3-10 minutes for the package download.
echo Subsequent runs start immediately.
echo.
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo [ERROR] venv creation failed. & pause & exit /b 1 )
) else (
    echo [1/3] Using existing .venv
)

call .venv\Scripts\activate.bat

echo.
echo [2/3] Installing dependencies (PyQt6, PyMuPDF)...
echo       (watch progress bars - first time only)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] pip install failed. & pause & exit /b 1 )

echo.
echo [3/3] Launching PolyPDF...
echo.
python main.py
echo.
echo (Application closed.)
pause
endlocal
