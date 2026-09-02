$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Runner = Join-Path $Root "run.py"

if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found. Run start.bat once before installing auto-start."
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Runner`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "LaptopRemoteAgent" -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Host "Laptop Remote will now start automatically when you sign in to Windows."
