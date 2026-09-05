Unregister-ScheduledTask -TaskName "LaptopRemoteAgent" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Laptop Remote auto-start has been removed."
