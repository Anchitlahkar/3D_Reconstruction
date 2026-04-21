Clear-Host
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    $projectRoot = (Get-Location).Path
}

$pythonExe = Join-Path $projectRoot "venv\Scripts\python.exe"
$colmapDir = Join-Path $projectRoot "colmap_bin\COLMAP-3.9.1-windows-cuda"
$runScript = Join-Path $projectRoot "scripts\run_colmap.py"
$monitorScript = Join-Path $projectRoot "scripts\progress_monitor.py"
$logPath = Join-Path $projectRoot "logs\colmap.log"

if (!(Test-Path $pythonExe)) {
    $pythonExe = "python"
}

if (!(Test-Path $colmapDir)) {
    throw "COLMAP folder not found: $colmapDir"
}

if (!(Test-Path $runScript)) {
    throw "Pipeline script not found: $runScript"
}

if (!(Test-Path $monitorScript)) {
    throw "Progress monitor not found: $monitorScript"
}

$env:Path = "$colmapDir;$env:Path"

Write-Host "==============================" -ForegroundColor Cyan
Write-Host "   3D Reconstruction Pipeline" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

New-Item -ItemType Directory -Path (Split-Path $logPath -Parent) -Force | Out-Null
if (Test-Path $logPath) {
    Remove-Item -LiteralPath $logPath -Force
}

Push-Location $projectRoot
try {
    $pipelineProcess = Start-Process -FilePath $pythonExe -ArgumentList "scripts/run_colmap.py" -PassThru
    & $pythonExe $monitorScript --pid $pipelineProcess.Id
    $pipelineProcess.WaitForExit()

    if ($pipelineProcess.ExitCode -ne 0) {
        throw "Pipeline failed with exit code $($pipelineProcess.ExitCode)"
    }

    Write-Host ""
    Write-Host "Reconstruction Complete" -ForegroundColor Green
} finally {
    Pop-Location
}
