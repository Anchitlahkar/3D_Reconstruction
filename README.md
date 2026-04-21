# 3D Reconstruction

Windows-first photogrammetry pipeline that turns a video into a dense COLMAP point cloud and opens it in a custom Raylib viewer.

The current flow is:

```text
video -> frame extraction -> frame selection -> geometric verification -> COLMAP -> fused.ply -> viewer
```

## Features

- extracts frames from a source video with `ffmpeg`
- reduces redundant frames before reconstruction
- runs sparse and dense reconstruction with COLMAP
- logs progress to `logs/colmap.log`
- shows a live terminal progress monitor
- opens the final `.ply` in a native C++ viewer

## Project Structure

```text
3D_Reconstruction/
|-- main.py
|-- run_pipeline.ps1
|-- view_existing_model.ps1
|-- config.json
|-- requirements.txt
|-- working.md
|-- scripts/
|   |-- extract_frames.py
|   |-- auto_select_frames.py
|   |-- geometric_filter.py
|   |-- run_colmap.py
|   `-- progress_monitor.py
|-- viewer/
|   `-- main.cpp
|-- data/
|   |-- input_video/
|   |-- images/
|   |-- images_selected/
|   |-- images_verified/
|   |-- sparse/
|   `-- dense/
|       `-- 0/
|           `-- fused.ply
|-- logs/
|   `-- colmap.log
|-- colmap_bin/
`-- raylib/
```

## Requirements

- Windows
- Python 3.10+
- COLMAP available through `config.json` or PATH
- FFmpeg available on PATH
- a C++ toolchain with `g++` if you want to rebuild the viewer
- Raylib files under `raylib/raylib-5.5_win64_mingw-w64/`

Python dependencies used by the current code:

- `tqdm`
- `psutil`
- `opencv-python`
- `numpy`

`requirements.txt` currently does not include all of these, so install any missing packages manually if needed.

## Setup

Create or activate a virtual environment, then install the Python packages you need:

```powershell
.\venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\venv\Scripts\python.exe -m pip install opencv-python numpy
```

Check these paths before your first run:

- `config.json`
- `colmap_bin/COLMAP-3.9.1-windows-cuda/`
- `raylib/raylib-5.5_win64_mingw-w64/`

## Quick Start

Run the full pipeline from the terminal with the PowerShell script:

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4
```

If `--video` is omitted, `main.py` will use the first supported video it finds in `data/input_video/`.

Check and open an existing reconstruction from the terminal with:

```powershell
.\view_existing_model.ps1
```

## Usage

Recommended terminal commands:

```powershell
.\venv\Scripts\python.exe .\main.py --video .\path\to\input.mp4
```

For normal use, prefer the `.ps1` scripts in the terminal:

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4
.\run_pipeline.ps1 --video .\path\to\input.mp4 --no-filter
.\run_pipeline.ps1 --video .\path\to\input.mp4 --no-viewer
.\view_existing_model.ps1
```

Run `main.py` directly only if you specifically want to bypass the PowerShell wrapper.

Useful flags:

```powershell
.\venv\Scripts\python.exe .\main.py --no-filter
.\venv\Scripts\python.exe .\main.py --no-viewer
.\venv\Scripts\python.exe .\main.py --skip-viewer-build
```

## Pipeline Stages

### 1. Frame Extraction

`scripts/extract_frames.py`:

- probes video duration
- chooses an extraction FPS automatically
- writes JPG frames into `data/images/`
- caps total extracted frames at `2000`

### 2. Frame Selection

`scripts/auto_select_frames.py`:

- computes ORB features on resized frames
- removes highly redundant images
- saves the filtered set to `data/images_selected/`

### 3. Geometry Verification

`scripts/geometric_filter.py`:

- estimates geometric consistency between selected frames
- keeps only frames with acceptable inlier ratios
- saves the verified set to `data/images_verified/`

### 4. COLMAP Reconstruction

`scripts/run_colmap.py`:

- clears previous reconstruction artifacts
- runs feature extraction, matching, mapping, undistortion, dense stereo, and fusion
- writes the final output to `data/dense/0/fused.ply`

### 5. Viewing

`.\view_existing_model.ps1` is the recommended way to check the generated model from the terminal.

That script verifies `data/dense/0/fused.ply` exists and then launches `viewer/viewer.exe`.

## Outputs

- final point cloud: `data/dense/0/fused.ply`
- COLMAP database: `data/database.db`
- sparse model: `data/sparse/`
- dense workspace: `data/dense/`
- log file: `logs/colmap.log`

## Viewer Controls

- right mouse drag: rotate
- mouse wheel: move forward/backward
- `W`, `A`, `S`, `D`: move
- `Q`: move up
- `E`: move down
- `Shift`: move faster
- `1`, `2`, `3`: point size
- `G`: toggle grid
- `F`: flip vertical orientation
- `R`: reset camera

Direct viewer launch:

```powershell
.\viewer\viewer.exe .\data\dense\0\fused.ply
```

## Configuration Notes

The repo still contains a few config/documentation mismatches:

- `config.json` says `"output_ply": "data/dense/fused.ply"`, but the real output is `data/dense/0/fused.ply`
- `config.json` says `"matcher": "exhaustive"`, but the current code uses `sequential_matcher`
- `config.json` says `"max_image_size": 2000`, but `scripts/run_colmap.py` currently uses `1200`

Treat the code as the source of truth until those values are reconciled.

## Troubleshooting

### FFmpeg not found

Install FFmpeg and make sure `ffmpeg` and `ffprobe` are available on PATH. The PowerShell wrapper currently adds a machine-specific FFmpeg path for one local setup, but that may not match yours.

### COLMAP executable not found

Verify the executable path in [config.json](/abs/path/c:/dev/3D_Reconstruction/config.json:1) and confirm the COLMAP files exist under `colmap_bin/`.

### Missing Python modules

If you see import errors for `cv2` or `numpy`, install:

```powershell
.\venv\Scripts\python.exe -m pip install opencv-python numpy
```

### Pipeline fails before the viewer opens

Check [logs/colmap.log](/abs/path/c:/dev/3D_Reconstruction/logs/colmap.log:1) for the last `[STEP]` and any `[ERROR]` entries.

### No reconstruction found

`view_existing_model.ps1` expects:

```text
data/dense/0/fused.ply
```

Run the full pipeline first if that file does not exist.
