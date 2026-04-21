# One-command launcher for the video-to-3D pipeline and Raylib viewer.
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    $projectRoot = (Get-Location).Path
}

$ffmpegBin = "C:\Users\Anchit\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"
$colmapDir = Join-Path $projectRoot "colmap_bin\COLMAP-3.9.1-windows-cuda"
$pythonExe = Join-Path $projectRoot "venv\Scripts\python.exe"
$mainScript = Join-Path $projectRoot "main.py"

if (Test-Path $ffmpegBin) {
    $env:Path = "$ffmpegBin;$env:Path"
}

if (Test-Path $colmapDir) {
    $env:Path = "$colmapDir;$env:Path"
} else {
    throw "COLMAP folder not found: $colmapDir"
}

if (!(Test-Path $mainScript)) {
    throw "main.py not found: $mainScript"
}

if (!(Test-Path $pythonExe)) {
    $pythonExe = "python"
}

Write-Host "--- Starting full video-to-3D pipeline ---" -ForegroundColor Cyan
Write-Host "Project root: $projectRoot"

Push-Location $projectRoot
try {
    & $pythonExe $mainScript @args
    if ($LASTEXITCODE -ne 0) {
        throw "Pipeline failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
