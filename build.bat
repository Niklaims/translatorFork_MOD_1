@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if exist "%cd%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%cd%\.venv\Scripts\python.exe"
) else if exist "%cd%\venv\Scripts\python.exe" (
    set "PYTHON_CMD=%cd%\venv\Scripts\python.exe"
) else (
    set "PYTHON_CMD=python"
)

"%PYTHON_CMD%" -m pip install --upgrade -r requirements.txt pyinstaller pyinstaller-hooks-contrib
if errorlevel 1 goto :error

"%PYTHON_CMD%" -m PyInstaller --clean --noconfirm translatorFork.spec
if errorlevel 1 goto :error

echo.
echo [OK] Build finished: dist\translatorFork\translatorFork.exe
exit /b 0

:error
echo.
echo [ERROR] Build failed.
exit /b 1
