@echo off
if not exist "%LOCALAPPDATA%\LaptopRemote\agent.log" (
  echo The agent log does not exist yet. Start Laptop Remote first.
  pause
  exit /b 1
)
start "" notepad.exe "%LOCALAPPDATA%\LaptopRemote\agent.log"
