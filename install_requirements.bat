@echo off
setlocal
cd /d "%~dp0"
echo Installing Python dependencies from requirements.txt ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed.
  exit /b 1
)
echo.
echo Optional: PyInstaller (for onefile build)
python -m pip install pyinstaller
echo Done.
pause
