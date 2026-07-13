$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Python = Get-Command python -ErrorAction Stop
$Version = & $Python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$Version -lt [version]"3.11") {
    throw "Python 3.11 or newer is required. Found $Version."
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 22 or newer is required."
}

if (-not (Test-Path -LiteralPath ".venv")) {
    & $Python.Source -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"
& ".\.venv\Scripts\python.exe" -m playwright install chromium

Push-Location frontend
try {
    npm ci
    npm run build
} finally {
    Pop-Location
}

& ".\.venv\Scripts\alembic.exe" upgrade head
Write-Host "Setup complete." -ForegroundColor Green
