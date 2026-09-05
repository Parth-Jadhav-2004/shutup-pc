$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "agent_port.ps1")
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Runner = Join-Path $Root "run.py"

function Test-AgentListening {
    [bool](netstat -ano | Select-String -Pattern ":${AgentPort}\s+.*LISTENING")
}

if (-not (Test-Path $Python)) {
    exit 1
}

if (Test-AgentListening) {
    exit 0
}

for ($i = 0; $i -lt 20; $i++) {
    if (Get-Command tailscale -ErrorAction SilentlyContinue) {
        try {
            $status = tailscale status --json 2>$null | ConvertFrom-Json
            if ($status.BackendState -eq "Running") {
                break
            }
        } catch {
        }
    }
    Start-Sleep -Seconds 3
}

try {
    & (Join-Path $PSScriptRoot "ensure_tailscale_serve.ps1") | Out-Null
} catch {
}

if (Test-AgentListening) {
    exit 0
}

$process = Start-Process -FilePath $Python -ArgumentList "`"$Runner`"" -WorkingDirectory $Root -PassThru -WindowStyle Hidden
if (-not $process) {
    exit 1
}
Wait-Process -Id $process.Id
if ($null -ne $process.ExitCode) {
    exit $process.ExitCode
}
exit 0
