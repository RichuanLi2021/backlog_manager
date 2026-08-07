# One-time setup. Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name was not found. $hint"
    }
}

Require-Command "py" "Install Python 3.11 or newer from https://www.python.org/downloads/windows/"
Require-Command "npm" "Install Node.js 20 or newer from https://nodejs.org/"

Write-Host "Installing Python packages..." -ForegroundColor Cyan
py -m pip install --disable-pip-version-check -r "$root\backend\requirements.txt"

Write-Host "Installing and building the web UI..." -ForegroundColor Cyan
Push-Location "$root\frontend"
npm install
npm run build
Pop-Location

$envFile = "$root\backend\.env"
if (-not (Test-Path $envFile)) {
    Copy-Item "$root\backend\.env.example" $envFile
    # A random passphrase so group management is protected out of the box.
    $key = -join ((1..20) | ForEach-Object { "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray() | Get-Random })
    (Get-Content $envFile) -replace "^ADMIN_KEY=.*$", "ADMIN_KEY=$key" | Set-Content $envFile
    Write-Host ""
    Write-Host "Created backend\.env with a new admin passphrase: $key" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next: put your Jira token in backend\.env (JIRA_PAT), then run scripts\start.ps1"
