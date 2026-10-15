@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" goto setup
if not exist "frontend\dist\index.html" goto setup
if not exist "assets\frames\default-blue\background.png" goto setup
goto run
:setup
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup_windows.ps1"
if errorlevel 1 exit /b 1
:run
echo STEM 4CUT starting at http://localhost:8000/admin
".venv\Scripts\python.exe" -m backend.app.run
exit /b %errorlevel%
