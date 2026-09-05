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
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\install_autostart.ps1" -Quiet
if errorlevel 1 (
  echo Auto-start could not be registered. The agent will still run in this window.
) else (
  echo Auto-start is on: the agent comes back after restart or when you sign in.
)
set AGENT_PORT=28471
for /f "usebackq delims=" %%P in ("config\agent_port.txt") do set AGENT_PORT=%%P
netstat -ano | findstr /R /C:":%AGENT_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo Laptop Remote is already running.
  echo Remote HTTPS is https://devil-1.tail1ed514.ts.net/laptop-remote
  start "" "http://127.0.0.1:%AGENT_PORT%/setup"
  exit /b 0
)
".venv\Scripts\python.exe" run.py --open-setup
