# One-shot local runner for Windows PowerShell.
#   .\run.ps1          -> set up venv, run the smoke test, then start the API
#   .\run.ps1 -SmokeOnly
#   .\run.ps1 -ServeOnly
param(
    [switch]$SmokeOnly,
    [switch]$ServeOnly
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"
Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $py -m pip install --disable-pip-version-check -q -r requirements.txt

if (-not $ServeOnly) {
    Write-Host "`nRunning end-to-end smoke test..." -ForegroundColor Cyan
    & $py smoke_test.py
    if ($LASTEXITCODE -ne 0) { throw "Smoke test failed." }
}
if ($SmokeOnly) { return }

Write-Host "`nStarting API on http://127.0.0.1:8000  (docs at /docs)`n" -ForegroundColor Green
& $py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
