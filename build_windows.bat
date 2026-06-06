@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo PDFjsNormalizerGUI - Windows EXE Builder
echo ========================================
echo.

rem Select Python launcher if available. Prefer Python 3.12, then 3.13, then default python.
set "PY_CMD="

where py >nul 2>nul
if %errorlevel%==0 (
    py -3.12 --version >nul 2>nul
    if %errorlevel%==0 set "PY_CMD=py -3.12"

    if not defined PY_CMD (
        py -3.13 --version >nul 2>nul
        if %errorlevel%==0 set "PY_CMD=py -3.13"
    )

    if not defined PY_CMD (
        py -3 --version >nul 2>nul
        if %errorlevel%==0 set "PY_CMD=py -3"
    )
)

if not defined PY_CMD (
    python --version >nul 2>nul
    if %errorlevel%==0 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo ERROR: Python was not found.
    echo Install Python 3.12 or 3.13, then run this file again.
    pause
    exit /b 1
)

echo Using Python:
%PY_CMD% --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if %errorlevel% neq 0 (
    echo ERROR: Failed to activate virtual environment.
    pause
    exit /b 1
)

echo Upgrading pip...
python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo ERROR: Failed to upgrade pip.
    pause
    exit /b 1
)

echo Installing dependencies...
python -m pip install --no-cache-dir -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo Building EXE...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PDFjsNormalizerGUI app.py
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

if exist "dist\PDFjsNormalizerGUI.exe" (
    echo.
    echo Build complete:
    echo %CD%\dist\PDFjsNormalizerGUI.exe
) else (
    echo.
    echo ERROR: Build finished, but EXE was not found.
)

pause
