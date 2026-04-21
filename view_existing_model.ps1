$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    $projectRoot = (Get-Location).Path
}

$modelPath = Join-Path $projectRoot "data\dense\0\fused.ply"
$viewerExe = Join-Path $projectRoot "viewer\viewer.exe"

if (!(Test-Path $modelPath)) {
    Write-Host "No reconstruction found" -ForegroundColor Red
    exit 1
}

if (!(Test-Path $viewerExe)) {
    Write-Host "Error: viewer\viewer.exe was not found." -ForegroundColor Red
    exit 1
}

Write-Host "Opening existing model..." -ForegroundColor Cyan
Start-Process -FilePath $viewerExe -ArgumentList $modelPath -WorkingDirectory (Split-Path $viewerExe -Parent) | Out-Null
