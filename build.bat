@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found. Install Python 3.11+ and add it to PATH.
  exit /b 1
)

python "%~dp0scripts\build_nuitka.py"
exit /b %ERRORLEVEL%
