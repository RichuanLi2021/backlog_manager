# Start the app:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# Add -Port 9000 to use another port, or -Share to let others on your network in.
param(
    [int]$Port = 8000,
    [switch]$Share
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\frontend\dist\index.html")) {
    throw "The web UI has not been built yet. Run scripts\setup.ps1 first."
}
if (-not (Test-Path "$root\backend\.env")) {
    throw "backend\.env is missing. Run scripts\setup.ps1 first."
}
if (-not (Select-String -Path "$root\backend\.env" -Pattern "^JIRA_PAT=.+" -Quiet)) {
    Write-Host "Warning: JIRA_PAT is empty in backend\.env, so Update from Jira will fail." -ForegroundColor Yellow
}

$listen = if ($Share) { "0.0.0.0" } else { "127.0.0.1" }
$url = "http://127.0.0.1:$Port/"

Write-Host "Backlog Report Platform -> $url" -ForegroundColor Green
if ($Share) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
    Write-Host "Others on your network: http://${ip}:$Port/  (a firewall prompt may appear)" -ForegroundColor Green
}
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray

Start-Process $url
Push-Location "$root\backend"
try {
    py -m uvicorn app.main:app --host $listen --port $Port
} finally {
    Pop-Location
}
