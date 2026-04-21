# Open an already-generated point cloud in the Raylib viewer.
param(
    [string]$ModelPath = "data\dense\0\fused.ply",
    [switch]$SkipViewerBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    $projectRoot = (Get-Location).Path
}

$viewerDir = Join-Path $projectRoot "viewer"
$viewerSource = Join-Path $viewerDir "main.cpp"
$viewerExe = Join-Path $viewerDir "viewer.exe"
$raylibRoot = Join-Path $projectRoot "raylib\raylib-5.5_win64_mingw-w64"
$raylibInclude = Join-Path $raylibRoot "include"
$raylibLib = Join-Path $raylibRoot "lib"
$raylibDll = Join-Path $raylibLib "raylib.dll"
$viewerDll = Join-Path $viewerDir "raylib.dll"

$resolvedModelPath = if ([System.IO.Path]::IsPathRooted($ModelPath)) {
    $ModelPath
} else {
    Join-Path $projectRoot $ModelPath
}

if (!(Test-Path $resolvedModelPath)) {
    throw "Point cloud not found: $resolvedModelPath"
}

if (!(Test-Path $viewerSource)) {
    throw "Viewer source not found: $viewerSource"
}

Push-Location $projectRoot
try {
    if (!(Test-Path $viewerExe) -and $SkipViewerBuild) {
        throw "viewer.exe is missing and -SkipViewerBuild was passed."
    }

    if (!(Test-Path $viewerExe) -or !$SkipViewerBuild) {
        Write-Host "[viewer] Compiling Raylib point cloud viewer" -ForegroundColor Cyan
        & g++ $viewerSource -o $viewerExe -std=c++17 "-I$raylibInclude" "-L$raylibLib" -lraylib -lopengl32 -lgdi32 -lwinmm
        if ($LASTEXITCODE -ne 0) {
            throw "Viewer build failed with exit code $LASTEXITCODE"
        }

        if (Test-Path $raylibDll) {
            Copy-Item -LiteralPath $raylibDll -Destination $viewerDll -Force
        }
    }

    Write-Host "[viewer] Launching existing model" -ForegroundColor Cyan
    Write-Host "$viewerExe $resolvedModelPath"
    Start-Process -FilePath $viewerExe -ArgumentList $resolvedModelPath -WorkingDirectory $viewerDir | Out-Null
} finally {
    Pop-Location
}
