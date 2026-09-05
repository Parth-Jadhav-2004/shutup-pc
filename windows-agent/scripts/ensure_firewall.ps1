param([switch]$Elevated)

$ErrorActionPreference = "Stop"
$RuleName = "Laptop Remote (TCP 8765)"
$ScriptPath = $MyInvocation.MyCommand.Path

if (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue) {
    Write-Host "Windows Firewall is ready for Laptop Remote."
    exit 0
}

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdministrator = $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $IsAdministrator) {
    Write-Host "Laptop Remote needs permission to accept connections from your phone."
    $Arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$ScriptPath`"",
        "-Elevated"
    )
    $Process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList $Arguments
    exit $Process.ExitCode
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8765 `
    -RemoteAddress LocalSubnet,100.64.0.0/10 `
    -Profile Any `
    -Description "Allows authenticated Laptop Remote traffic from the local network and Tailscale."

Write-Host "Allowed Laptop Remote on TCP port 8765 for local and Tailscale devices."
