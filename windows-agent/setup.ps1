$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
& (Join-Path $Root "scripts\ensure_tailscale_serve.ps1")
& (Join-Path $Root "scripts\ensure_firewall.ps1")

Write-Host ""
Write-Host "Windows agent is ready."
Write-Host "Start it with start.bat"
Write-Host "Optional auto-start: powershell -ExecutionPolicy Bypass -File .\scripts\install_autostart.ps1"
