# 3D Reconstruction Working Notes

This file is the current reality-check document for the repo. It reflects how the code behaves today.

## What The Project Does

The project turns a video into a dense 3D point cloud with COLMAP, then opens the result in a custom Raylib viewer.

The main output is:

```text
data/dense/0/fused.ply
```

The live COLMAP log is:

```text
logs/colmap.log
```

## Current Execution Flow

The active Windows entry point is:

```powershell
.\run_pipeline.ps1
```

That script currently:

1. sets up PATH entries for FFmpeg and COLMAP
2. starts `main.py`
3. starts `scripts/progress_monitor.py` against the Python process
4. waits for the pipeline to finish

So the real flow is:

```text
run_pipeline.ps1
  -> main.py
     -> scripts/extract_frames.py
     -> scripts/run_colmap.py
```

For checking an already-generated model in the terminal, use:

```powershell
.\view_existing_model.ps1
```

## Main Pipeline Behavior

### `main.py`

`main.py` is the orchestration layer.

It:

- loads settings from `config.json`
- resolves an input video from `--video` or `data/input_video/`
- copies the input video into `data/input_video/` when needed
- extracts frames into `data/images/`
- runs COLMAP against `data/images/`

Useful flags:

```powershell
.\venv\Scripts\python.exe .\main.py --video path\to\input.mp4
.\venv\Scripts\python.exe .\main.py --config .\config.json
```

The direct Python entry point still works, but the recommended user-facing way to run the project is through the `.ps1` scripts.

### `scripts/extract_frames.py`

This script uses `ffmpeg` to extract JPG frames into `data/images/`.

Current behavior:

- always extracts at `fps = 4`
- downscales frames to max width `1200`
- deletes old `.jpg` frames in the target folder before writing new ones

Dependencies used here:

- `ffmpeg` in PATH

### `scripts/run_colmap.py`

This is the reconstruction runner.

It:

- loads COLMAP settings from `config.json`
- removes old `data/database.db`, `data/sparse/`, and `data/dense/`
- logs every stage to `logs/colmap.log`
- runs COLMAP in this order:
  1. `feature_extractor`
  2. `sequential_matcher`
  3. `mapper`
  4. `image_undistorter`
  5. `patch_match_stereo`
  6. `stereo_fusion`

It writes the final point cloud to:

```text
data/dense/0/fused.ply
```

Important current details:

- matcher is `sequential_matcher`
- `ImageReader.single_camera` is hardcoded to `1`
- feature extraction enables affine shape estimation and domain-size pooling
- undistortion uses `--max_image_size 1200`
- dense stereo uses `geom_consistency=1`
- dense stereo uses `num_iterations=3`
- dense stereo uses `window_radius=4`
- stereo fusion uses `min_num_pixels=3`

### `scripts/progress_monitor.py`

This script tails `logs/colmap.log` and displays a `tqdm` progress bar.

It tracks:

- current pipeline step
- processed features
- matching progress
- sparse registration progress
- dense stereo progress
- fusion progress

It exits when:

- `data/dense/0/fused.ply` appears
- the monitored PID exits
- an error is logged
- you stop it manually

### `view_existing_model.ps1`

This opens the latest saved model without rerunning reconstruction.

It checks for:

```text
data/dense/0/fused.ply
```

It also checks for:

```text
viewer\viewer.exe
```

and then launches:

```text
viewer\viewer.exe
```

This script is now the recommended way to open the viewer. The reconstruction pipeline itself does not launch the viewer automatically.

## Viewer Notes

Viewer source:

```text
viewer/main.cpp
```

Viewer binary:

```text
viewer/viewer.exe
```

Viewer behavior from `viewer/main.cpp`:

- accepts a PLY path as the first CLI argument
- if no argument is given, searches several default paths and prefers `data/dense/0/fused.ply`
- supports ASCII and `binary_little_endian` PLY files
- requires vertex `x`, `y`, and `z` properties
- uses embedded vertex colors when `red/green/blue` or `r/g/b` are present
- applies a vertical coordinate correction before normalization
- normalizes the point cloud to fit the viewer scene
- shows an on-screen overlay with stats and controls

Manual launch:

```powershell
.\viewer\viewer.exe .\data\dense\0\fused.ply
```

You can also run:

```powershell
.\viewer\viewer.exe
```

and let the viewer try its built-in default PLY locations.

Current controls from `viewer/main.cpp`:

- right mouse drag: rotate camera
- mouse wheel: move forward/backward
- `W`, `A`, `S`, `D`: move
- `Q`: move up
- `E`: move down
- `Shift`: faster movement
- `F`: flip vertical orientation (fix upside-down models)
- `G`: toggle grid
- `V`: toggle density mode (dense vs light)
- `R`: reset camera
- `U`: rerun PCA alignment (resets flip)

## Config Reality Check

`config.json` is aligned with the current pipeline:

- `"output_ply": "data/dense/0/fused.ply"`
- `"matcher": "sequential_matcher"`
- `"max_image_size": 1200`

Still worth noting:

- `scripts/extract_frames.py` hardcodes `fps=4` instead of reading `config.json`
- `scripts/run_colmap.py` reads the COLMAP executable and GPU settings from config, but several tuning flags are still hardcoded in code
- `run_pipeline.ps1` still injects one machine-specific FFmpeg path if it exists

## Dependencies Right Now

`requirements.txt` currently contains:

- `tqdm`
- `psutil`

That matches the active Python scripts in the current pipeline.

External tools still required:

- `ffmpeg`
- COLMAP

## Project Layout Right Now

```text
3D_Reconstruction/
|-- config.json
|-- main.py
|-- README.md
|-- requirements.txt
|-- run_pipeline.ps1
|-- view_existing_model.ps1
|-- working.md
|-- scripts/
|   |-- extract_frames.py
|   |-- progress_monitor.py
|   `-- run_colmap.py
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

## Recommended Ways To Run It

### Full pipeline from video

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4
```

If `--video` is omitted, `main.py` uses the first supported video found in `data/input_video/`.

### Open an existing reconstruction

```powershell
.\view_existing_model.ps1
```

This is the recommended way to check the model from the terminal.

## Troubleshooting

### `ffmpeg was not found`

`scripts/extract_frames.py` needs `ffmpeg` on PATH. `run_pipeline.ps1` tries to add a local FFmpeg install path, but that path is machine-specific.

### `No video provided and no video found`

Pass `--video`, or place a supported video in:

```text
data/input_video/
```

### `No input images found`

This means `data/images/` is empty. Check frame extraction first.

### `COLMAP executable not found`

Check:

- `config.json`
- `colmap_bin/COLMAP-3.9.1-windows-cuda/`
- the PATH setup in `run_pipeline.ps1`

### `Pipeline ended with an error. Check logs/colmap.log`

Open:

```text
logs/colmap.log
```

and inspect the most recent `[STEP]` or `[ERROR]` lines.

### `No reconstruction found`

`view_existing_model.ps1` could not find:

```text
data/dense/0/fused.ply
```

Run the reconstruction first.

### `viewer\viewer.exe was not found`

`view_existing_model.ps1` found the model but could not find the viewer binary. Restore or rebuild `viewer/viewer.exe` before trying again.
