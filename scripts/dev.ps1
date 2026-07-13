$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Run scripts/setup.ps1 first." }

$Api = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload") -WorkingDirectory $Root -WindowStyle Hidden -PassThru
try {
    Set-Location (Join-Path $Root "frontend")
    npm run dev
} finally {
    if (-not $Api.HasExited) { Stop-Process -Id $Api.Id }
}
