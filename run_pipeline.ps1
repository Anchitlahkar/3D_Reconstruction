Clear-Host
$ErrorActionPreference = "Stop"

# 1. Entry Script Validation - Resolve project root
$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    $projectRoot = (Get-Location).Path
}
Set-Location -Path $projectRoot

# 2. Environment Validation - Setup Paths
$ffmpegBin = "C:\Users\Anchit\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
$pythonExe = Join-Path $projectRoot "venv\Scripts\python.exe"
$colmapDir = Join-Path $projectRoot "colmap_bin\COLMAP-3.9.1-windows-cuda"
$mainScript = Join-Path $projectRoot "main.py"
$monitorScript = Join-Path $projectRoot "scripts\progress_monitor.py"

# Use venv if exists, otherwise system python
if (!(Test-Path $pythonExe)) {
    Write-Host "[WARN] Virtual environment not found at $pythonExe, trying system 'python'" -ForegroundColor Yellow
    $pythonExe = "python"
}

# Add local FFmpeg and COLMAP to Path
if (Test-Path $ffmpegBin) {
    $env:Path = "$ffmpegBin;$env:Path"
}
if (Test-Path $colmapDir) {
    $env:Path = "$colmapDir;$env:Path"
} else {
    throw "COLMAP folder not found: $colmapDir"
}

if (!(Test-Path $mainScript)) {
    throw "Pipeline entry point not found: $mainScript"
}

# 3. Mode Support & Argument Propagation
$pipelineArgs = @($mainScript) + $args

Write-Host "==============================" -ForegroundColor Cyan
Write-Host "   3D Reconstruction Pipeline" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[INFO] Root: $projectRoot"
Write-Host "[INFO] Exec: $pythonExe"
Write-Host "[INFO] Args: $pipelineArgs"
Write-Host ""

try {
    # 8. Failure Handling - Run pipeline
    # We start main.py in the background first so we can attach the terminal monitor to it
    $pipelineProcess = Start-Process -FilePath $pythonExe -ArgumentList $pipelineArgs -PassThru -NoNewWindow
    
    # 6. Monitor Integration
    # Run the tqdm monitor in the current terminal, attached to the pipeline PID
    if (Test-Path $monitorScript) {
        & $pythonExe $monitorScript --pid $pipelineProcess.Id
    }

    # Wait for the main process to fully finish
    $pipelineProcess.WaitForExit()
    
    if ($pipelineProcess.ExitCode -ne 0) {
        throw "Pipeline failed with exit code $($pipelineProcess.ExitCode). Check logs/colmap.log"
    }

    # 9. Output Verification
    $outputPath = Join-Path $projectRoot "data\dense\0\fused.ply"
    if (Test-Path $outputPath) {
        Write-Host ""
        Write-Host "==============================" -ForegroundColor Green
        Write-Host "Reconstruction Complete" -ForegroundColor Green
        Write-Host "Output: $outputPath" -ForegroundColor Green
        Write-Host "==============================" -ForegroundColor Green
    } else {
        if ($args -contains "--dry-run") {
             Write-Host "[INFO] Dry run finished. Check tmp_dry_run for outputs." -ForegroundColor Cyan
        } else {
             Write-Host "[WARN] Pipeline finished but fused.ply was not found at expected location." -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
