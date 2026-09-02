$ErrorActionPreference = "Stop"

if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Write-Warning "Tailscale is not installed. Remote HTTPS is unavailable."
    exit 0
}

$Status = tailscale status --json | ConvertFrom-Json
if ($Status.BackendState -ne "Running") {
    Write-Warning "Tailscale is not connected. Open Tailscale before using the phone web app."
    exit 0
}

& tailscale serve --bg --yes --set-path /laptop-remote 8765 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not configure Tailscale Serve."
}

$DnsName = $Status.Self.DNSName.TrimEnd(".")
Write-Host "Tailscale HTTPS: https://$DnsName/laptop-remote"
