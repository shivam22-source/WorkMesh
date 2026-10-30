# PowerShell helper to run fixture ingestion locally
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$ragDir = Join-Path $projectRoot "rag-python"
$pyExe = Join-Path $ragDir ".venv\Scripts\python.exe"

if (-not (Test-Path $pyExe)) {
    Write-Error "Virtual environment python not found at $pyExe. Run 'python -m venv .venv' inside rag-python."
    exit 1
}

Write-Host "Running GitHub fixture ingestion..." -ForegroundColor Cyan
Push-Location $ragDir
try {
    & $pyExe -m app.cli.ingest --source github --fixture --in-memory
} finally {
    Pop-Location
}
