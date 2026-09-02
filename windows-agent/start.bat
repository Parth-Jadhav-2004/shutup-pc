@echo off
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\ensure_tailscale_serve.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\ensure_firewall.ps1"
if errorlevel 1 (
  echo.
  echo Windows Firewall setup was cancelled or failed.
  echo Remote access may not work until permission is granted.
  pause
  exit /b 1
)
netstat -ano | findstr /R /C:":8765 .*LISTENING" >nul
if not errorlevel 1 (
  echo Laptop Remote is already running.
  echo Remote HTTPS is https://devil-1.tail1ed514.ts.net/laptop-remote
  start "" "http://127.0.0.1:8765/setup"
  exit /b 0
)
".venv\Scripts\python.exe" run.py --open-setup
