@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  pause
  exit /b 1
)
python app.py
if not "%ERRORLEVEL%"=="0" pause
exit /b %ERRORLEVEL%
