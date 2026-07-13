$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Run scripts/setup.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $Root "frontend\dist\index.html"))) {
    Push-Location frontend
    try { npm run build } finally { Pop-Location }
}

$Url = "http://127.0.0.1:8000"
$BrowserJob = Start-Job -ScriptBlock {
    param($Target)
    for ($i = 0; $i -lt 40; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$Target/api/v1/health" -TimeoutSec 1 | Out-Null
            Start-Process $Target
            return
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
} -ArgumentList $Url

try {
    & $Python -m backend.app
} finally {
    Remove-Job -Job $BrowserJob -Force -ErrorAction SilentlyContinue
}
