$ErrorActionPreference = "SilentlyContinue"
Unregister-ScheduledTask -TaskName "LaptopRemoteAgent" -Confirm:$false
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "Laptop Remote.lnk"
if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
}
Write-Host "Laptop Remote auto-start has been removed."
