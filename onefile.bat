@echo off
setlocal
cd /d "%~dp0"
where pyinstaller >nul 2>&1
if errorlevel 1 (
  echo PyInstaller not found. Run install_requirements.bat first.
  exit /b 1
)
echo Building one-file executable ...
pyinstaller --noconfirm m_marker_export.spec
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
echo Output: dist\MMarkerExport.exe
pause
