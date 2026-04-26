# 3D Reconstruction

Windows-first photogrammetry pipeline that turns a video into a dense COLMAP point cloud and opens it in a custom Raylib viewer.

The current flow is:

```text
video -> frame extraction -> COLMAP -> fused.ply -> viewer
```

## Features

- extracts frames from a source video with `ffmpeg`
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
|   |-- run_colmap.py
|   `-- progress_monitor.py
|-- viewer/
|   `-- main.cpp
|-- data/
|   |-- input_video/
|   |-- images/
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

Python dependencies used by the active scripts:

- `tqdm`
- `psutil`

## Setup

Create or activate a virtual environment, then install the Python dependencies:

```powershell
.\venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

Check these paths before your first run:

- `config.json`
- `colmap_bin/COLMAP-3.9.1-windows-cuda/`
- `raylib/raylib-5.5_win64_mingw-w64/`

## Quick Start

Run the full pipeline from the terminal with:

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4
```

If `--video` is omitted, `main.py` uses the first supported video it finds in `data/input_video/`.

Open an existing reconstruction from the terminal with:

```powershell
.\view_existing_model.ps1
```

## Usage

Recommended terminal commands:

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4
.\view_existing_model.ps1
```

Direct Python entry point:

```powershell
.\venv\Scripts\python.exe .\main.py --video .\path\to\input.mp4
.\venv\Scripts\python.exe .\main.py --config .\config.json
```

Use `main.py` directly only if you want to bypass the PowerShell wrapper.

## Pipeline Stages

### 1. Frame Extraction

`scripts/extract_frames.py`:

- extracts JPG frames into `data/images/`
- uses fixed `fps=2` (optimized for better parallax)
- downscales frames to max width `2000`
- clears old JPG frames in the output folder before writing new ones

### 2. COLMAP Reconstruction

`scripts/run_colmap.py`:

- clears previous reconstruction artifacts
- uses `exhaustive_matcher` for better loop closure on objects
- runs feature extraction, matching, mapping, undistortion, dense stereo, and fusion
- logs every stage to `logs/colmap.log`
- writes the final output to `data/dense/0/fused.ply`

Current COLMAP behavior:

- `ImageReader.single_camera=1`
- `SiftExtraction.max_num_features=8192`
- `SiftExtraction.contrast_threshold=0.01`
- `SiftExtraction.edge_threshold=10`
- `image_undistorter --max_image_size 2000`
- `Mapper.init_min_tri_angle=8.0` (prevents depth uncertainty spikes)
- `PatchMatchStereo.geom_consistency=1`
- `PatchMatchStereo.num_iterations=5`
- `PatchMatchStereo.window_radius=5`
- `StereoFusion.min_num_pixels=8` (aggressive noise filtering)
- `StereoFusion.max_reproj_error=1.0`

### 3. Progress Monitoring

`scripts/progress_monitor.py`:

- tails `logs/colmap.log`
- tracks feature, match, mapping, dense, and fusion progress
- exits when `data/dense/0/fused.ply` appears, the pipeline PID exits, or an error is logged

### 4. Viewing

`.\view_existing_model.ps1` is the recommended viewer entry point.

It:

- checks that `data/dense/0/fused.ply` exists
- checks that `viewer/viewer.exe` exists
- launches the viewer with the reconstructed `.ply` path

The full pipeline does not auto-open the viewer anymore. Viewing is a separate step.

## Outputs

- final point cloud: `data/dense/0/fused.ply`
- COLMAP database: `data/database.db`
- sparse model: `data/sparse/`
- dense workspace: `data/dense/`
- log file: `logs/colmap.log`

## Viewer Controls

The viewer renders the point cloud using `GL_POINTS` to prevent "spiky" triangle artifacts. It supports robust normalization and large models up to 10,000 units from the origin.

- right mouse drag: rotate
- mouse wheel: move forward/backward
- `W`, `A`, `S`, `D`: move
- `Q`: move up
- `E`: move down
- `Shift`: move faster
- `F`: flip vertical orientation (fix upside-down models)
- `G`: toggle grid
- `V`: toggle density mode
- `R`: reset camera
- `U`: rerun PCA alignment (resets flip)

Direct viewer launch:

```powershell
.\viewer\viewer.exe .\data\dense\0\fused.ply
```

If you launch `viewer.exe` without an argument, it tries a small set of default PLY paths and prefers `data/dense/0/fused.ply` when found.

## Configuration Notes

`config.json` is now aligned with the active pipeline:

- output path: `data/dense/0/fused.ply`
- matcher: `exhaustive_matcher`
- max image size: `2000`
- COLMAP executable: `colmap_bin/COLMAP-3.9.1-windows-cuda/COLMAP.bat`

The code still hardcodes a few runtime values instead of reading every setting from config:

- extraction uses fixed `fps=2`
- `scripts/run_colmap.py` hardcodes several COLMAP tuning flags listed above
- `run_pipeline.ps1` adds a machine-specific FFmpeg path when it exists locally

## Troubleshooting

### FFmpeg not found

Install FFmpeg and make sure `ffmpeg` is available on PATH. `run_pipeline.ps1` also tries to add one local FFmpeg install path, but that path may not match your machine.

### COLMAP executable not found

Verify the executable path in [config.json](C:/dev/3D_Reconstruction/config.json) and confirm the COLMAP files exist under `colmap_bin/`.

### Missing Python modules

Install the required packages with:

```powershell
.\venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

### Pipeline fails before the viewer opens

Check [logs/colmap.log](C:/dev/3D_Reconstruction/logs/colmap.log) for the last `[STEP]` and any `[ERROR]` entries.

### No reconstruction found

`view_existing_model.ps1` expects:

```text
data/dense/0/fused.ply
```

Run the full pipeline first if that file does not exist.

### Viewer executable not found

`view_existing_model.ps1` also requires:

```text
viewer/viewer.exe
```

If that file is missing, rebuild or restore the viewer binary before trying to open the model.
