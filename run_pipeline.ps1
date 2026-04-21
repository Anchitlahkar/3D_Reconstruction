Clear-Host
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    $projectRoot = (Get-Location).Path
}

$ffmpegBin = "C:\Users\Anchit\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
$pythonExe = Join-Path $projectRoot "venv\Scripts\python.exe"
$colmapDir = Join-Path $projectRoot "colmap_bin\COLMAP-3.9.1-windows-cuda"
$mainScript = Join-Path $projectRoot "main.py"
$monitorScript = Join-Path $projectRoot "scripts\progress_monitor.py"
$logPath = Join-Path $projectRoot "logs\colmap.log"
$outputPath = Join-Path $projectRoot "data\dense\0\fused.ply"

if (!(Test-Path $pythonExe)) {
    $pythonExe = "python"
}

if (Test-Path $ffmpegBin) {
    $env:Path = "$ffmpegBin;$env:Path"
}

if (!(Test-Path $colmapDir)) {
    throw "COLMAP folder not found: $colmapDir"
}

if (!(Test-Path $mainScript)) {
    throw "Pipeline entry point not found: $mainScript"
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
    $pipelineArgs = @($mainScript) + $args
    $pipelineProcess = Start-Process -FilePath $pythonExe -ArgumentList $pipelineArgs -PassThru
    & $pythonExe $monitorScript --pid $pipelineProcess.Id
    $pipelineProcess.WaitForExit()

    if ($pipelineProcess.ExitCode -ne 0) {
        throw "Pipeline failed with exit code $($pipelineProcess.ExitCode)"
    }

    Write-Host ""
    if (Test-Path $outputPath) {
        Write-Host "Reconstruction Complete" -ForegroundColor Green
        Write-Host "Output: $outputPath" -ForegroundColor Green
    }
    else {
        throw "Pipeline finished without producing fused.ply"
    }
} finally {
    Pop-Location
}
