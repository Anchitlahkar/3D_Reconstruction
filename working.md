# Hybrid 3D Reconstruction Pipeline

This project runs a COLMAP-based reconstruction from extracted images in `data/images/`, writes the final dense point cloud to `data/dense/0/fused.ply`, and opens that model in a Raylib viewer.

## Current Workflow

The current system has two separate layers:

1. `main.py`
   - extracts frames from a video with FFmpeg
   - calls the COLMAP runner
   - can build and launch the viewer

2. `run_pipeline.ps1`
   - runs the COLMAP stage directly from existing images in `data/images/`
   - starts the progress monitor
   - waits for the pipeline to finish

Right now, the PowerShell pipeline is the cleanest way to run reconstruction if your frames are already present.

## Project Layout

```text
3D_Reconstruction/
|-- .gitignore
|-- config.json
|-- main.py
|-- run_pipeline.ps1
|-- view_existing_model.ps1
|-- working.md
|-- logs/
|   `-- colmap.log
|-- data/
|   |-- input_video/
|   |-- images/
|   |-- sparse/
|   `-- dense/
|       `-- 0/
|           `-- fused.ply
|-- scripts/
|   |-- extract_frames.py
|   |-- run_colmap.py
|   `-- progress_monitor.py
|-- viewer/
|   |-- main.cpp
|   |-- viewer.exe
|   `-- raylib.dll
`-- raylib/
    `-- raylib-5.5_win64_mingw-w64/
```

## Requirements

- Windows
- Python 3.10+
- COLMAP with CUDA support
- `tqdm`
- `psutil`
- `g++` if you want to rebuild the viewer
- Raylib in `raylib/raylib-5.5_win64_mingw-w64/`

The monitor now imports `psutil`, so both `tqdm` and `psutil` must be installed in the active environment.

## Main Scripts

### `scripts/run_colmap.py`

This is the standalone COLMAP runner used by `run_pipeline.ps1`.

It:

- reads settings from `config.json`
- uses images from `data/images/`
- deletes previous:
  - `data/database.db`
  - `data/sparse/`
  - `data/dense/`
- redirects all COLMAP output to:

```text
logs/colmap.log
```

- runs these steps in order:
  1. `feature_extractor`
  2. `sequential_matcher`
  3. `mapper`
  4. `image_undistorter`
  5. `patch_match_stereo`
  6. `stereo_fusion`

- writes the final output to:

```text
data/dense/0/fused.ply
```

### `scripts/progress_monitor.py`

This script tails `logs/colmap.log` and shows live progress.

It watches for:

- `Processed file`
- `Matching block`
- `Registering image`
- `Processing view`
- `Fusing image`

It tracks:

- `feature_count`
- `matching_count`
- `mapping_count`
- `dense_count`
- `fusion_count`

It exits when:

- `data/dense/0/fused.ply` appears
- the pipeline process exits
- you press `Ctrl+C`

### `run_pipeline.ps1`

This is the current clean Windows entry point for reconstruction from existing images.

It:

- clears the screen
- prints a header
- ensures `logs/` exists
- removes the old `logs/colmap.log`
- starts `scripts/run_colmap.py` in the background
- starts `scripts/progress_monitor.py` with the pipeline PID
- waits for the pipeline to finish
- prints `Reconstruction Complete`

### `view_existing_model.ps1`

This script opens the existing model without rerunning COLMAP.

It checks for:

```text
data/dense/0/fused.ply
```

If the file exists, it launches:

```text
viewer/viewer.exe
```

If the file does not exist, it prints:

```text
No reconstruction found
```

## Recommended Usage

### Run reconstruction from existing images

```powershell
.\run_pipeline.ps1
```

This path expects your frames to already exist in:

```text
data/images/
```

### Open the existing model

```powershell
.\view_existing_model.ps1
```

### Run the older end-to-end Python flow

```powershell
.\venv\Scripts\python.exe .\main.py --video path\to\input.mp4
```

That route still:

- copies the video into `data/input_video/` if needed
- extracts frames with FFmpeg
- calls `run_colmap(...)`
- can build and launch the viewer

Useful flags:

```powershell
.\venv\Scripts\python.exe .\main.py --no-viewer
.\venv\Scripts\python.exe .\main.py --skip-viewer-build
```

## Output Paths

The real reconstruction output is:

```text
data/dense/0/fused.ply
```

The current log file is:

```text
logs/colmap.log
```

## Viewer

The viewer source is:

```text
viewer/main.cpp
```

The compiled executable is:

```text
viewer/viewer.exe
```

Manual launch:

```powershell
.\viewer\viewer.exe .\data\dense\0\fused.ply
```

Viewer controls:

- right mouse drag: rotate
- mouse wheel: move forward/backward
- `W`, `A`, `S`, `D`: move
- `Q` / `E`: move down/up
- `Shift`: faster movement
- `1`, `2`, `3`: point size
- `G`: toggle grid
- `R`: reset camera

## Configuration Notes

Current `config.json` still contains:

```json
"output_ply": "data/dense/fused.ply"
```

But the actual pipeline writes:

```text
data/dense/0/fused.ply
```

So `config.json` still has a stale output path entry.

Also note:

- `config.json` still says `"matcher": "exhaustive"`
- the active `scripts/run_colmap.py` ignores that and uses `sequential_matcher`
- `config.json` still says `"max_image_size": 2000`
- the active runner currently hardcodes `1200`

So the current code is the source of truth, not every field in `config.json`.

## Performance Settings In The Current Runner

The active COLMAP runner uses:

- `--ImageReader.single_camera 1`
- `--SiftExtraction.use_gpu 1` when GPU is enabled
- `--SiftMatching.use_gpu 1` when GPU is enabled
- `--max_image_size 1200`
- `--PatchMatchStereo.num_iterations 3`

This version is aimed more at cleaner execution and lower terminal noise than at maximum reconstruction density.

## Logging And Progress

The terminal stays relatively clean because:

- COLMAP stdout/stderr goes into `logs/colmap.log`
- the PowerShell script only shows the monitor
- the monitor prints a `tqdm` bar plus counters

The monitor is log-driven, so if COLMAP changes its console wording, some counters may stop moving even if the pipeline still works.

## Troubleshooting

### `No input images found`

`scripts/run_colmap.py` only works if image files already exist in `data/images/`.

Use `main.py` with a video first, or place frames in `data/images/`.

### `COLMAP executable not found`

Check:

- `config.json`
- `colmap_bin/COLMAP-3.9.1-windows-cuda/`
- the PATH setup in `run_pipeline.ps1`

### `ModuleNotFoundError: No module named 'psutil'`

Install `psutil` in the project venv. The progress monitor now depends on it.

### `Pipeline process exited. Check logs/colmap.log for details.`

The runner ended before producing `fused.ply`. Open:

```text
logs/colmap.log
```

and inspect the last failing stage.

### `No reconstruction found`

`view_existing_model.ps1` did not find:

```text
data/dense/0/fused.ply
```

Run reconstruction first.

### Viewer says `Input is not a PLY file`

That CRLF parsing issue was fixed in the current viewer source. Rebuild `viewer.exe` if you are still using an older binary.

## Reality Check

This document matches the current behavior of:

- [main.py](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/main.py:1)
- [scripts/run_colmap.py](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/scripts/run_colmap.py:1)
- [scripts/progress_monitor.py](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/scripts/progress_monitor.py:1)
- [run_pipeline.ps1](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/run_pipeline.ps1:1)
- [view_existing_model.ps1](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/view_existing_model.ps1:1)
- [viewer/main.cpp](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/viewer/main.cpp:1)

If you change the workflow again, update this file in the same pass. It keeps the whole project much less haunted.
