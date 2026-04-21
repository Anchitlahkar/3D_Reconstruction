# 3D Reconstruction Working Notes

This file is the current reality-check document for the repo. It reflects how the code behaves today, even where that behavior differs from older docs or config values.

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
     -> scripts/auto_select_frames.py
     -> scripts/geometric_filter.py
     -> scripts/run_colmap.py
     -> viewer/viewer.exe   (unless --no-viewer)
```

For checking an already-generated model in the terminal, use:

```powershell
.\view_existing_model.ps1
```

## Main Pipeline Behavior

### `main.py`

`main.py` is the real orchestration layer now.

It:

- loads settings from `config.json`
- resolves an input video from `--video` or `data/input_video/`
- copies the input video into `data/input_video/` when needed
- extracts frames into `data/images/`
- optionally filters frames into `data/images_selected/`
- optionally verifies geometry into `data/images_verified/`
- runs COLMAP against the verified set by default
- optionally rebuilds and launches the viewer

Useful flags:

```powershell
.\venv\Scripts\python.exe .\main.py --video path\to\input.mp4
.\venv\Scripts\python.exe .\main.py --no-filter
.\venv\Scripts\python.exe .\main.py --no-viewer
.\venv\Scripts\python.exe .\main.py --skip-viewer-build
```

This direct Python entry point still works, but the recommended user-facing way to run the project is through the `.ps1` scripts in the terminal.

### `scripts/extract_frames.py`

This script uses `ffmpeg` to extract JPG frames into `data/images/`.

Current behavior:

- computes extraction FPS from video duration
- uses higher FPS for shorter clips
- caps output to `MAX_FRAMES = 2000`
- deletes old `.jpg` frames in the target folder before writing new ones

Dependencies used here:

- `ffmpeg` in PATH
- OpenCV (`cv2`) as a fallback for duration probing

### `scripts/auto_select_frames.py`

This stage reduces redundancy before COLMAP.

It:

- reads images from `data/images/`
- computes ORB features on resized grayscale images
- compares frame-to-frame overlap with a brute-force matcher
- keeps a subset in `data/images_selected/`

Current tuning:

- target range: roughly `150` to `300` selected frames
- force-keep interval: every `10` frames
- minimum spacing: `2` frames

### `scripts/geometric_filter.py`

This stage removes geometrically weak transitions from the selected set.

It:

- reads from `data/images_selected/`
- estimates an essential matrix between consecutive kept frames
- keeps frames with inlier ratio `>= 0.2`
- writes the verified set to `data/images_verified/`

### `scripts/run_colmap.py`

This is the actual reconstruction runner.

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

- matcher is hardcoded to `sequential_matcher`
- `ImageReader.single_camera` is hardcoded to `1`
- undistortion uses `--max_image_size 1200`
- dense stereo uses `geom_consistency=1`
- dense stereo uses `num_iterations=3`

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

and launches:

```text
viewer\viewer.exe
```

## Viewer Notes

Viewer source:

```text
viewer/main.cpp
```

Viewer binary:

```text
viewer/viewer.exe
```

Manual launch:

```powershell
.\viewer\viewer.exe .\data\dense\0\fused.ply
```

Current controls from `viewer/main.cpp`:

- right mouse drag: rotate camera
- mouse wheel: move forward/backward
- `W`, `A`, `S`, `D`: move
- `Q`: move up
- `E`: move down
- `Shift`: faster movement
- `1`, `2`, `3`: point size
- `G`: toggle grid
- `F`: flip vertical orientation
- `R`: reset camera

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
|   |-- auto_select_frames.py
|   |-- extract_frames.py
|   |-- geometric_filter.py
|   |-- progress_monitor.py
|   `-- run_colmap.py
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

## Mismatches To Keep In Mind

There are a few stale or incomplete pieces in the repo:

- `requirements.txt` currently lists only `tqdm` and `psutil`
- the code also imports `cv2` and `numpy`, so the dependency file is incomplete
- `config.json` still says `"output_ply": "data/dense/fused.ply"`
- the actual output path is `data/dense/0/fused.ply`
- `config.json` still says `"matcher": "exhaustive"`
- the active runner uses `sequential_matcher`
- `config.json` still says `"max_image_size": 2000`
- the active runner hardcodes `1200` for undistortion

For now, the code is the source of truth.

## Recommended Ways To Run It

### Full pipeline from video

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4
```

If `--video` is omitted, `main.py` will use the first supported video found in `data/input_video/`.

### Run without frame filtering

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4 --no-filter
```

### Run without opening the viewer

```powershell
.\run_pipeline.ps1 --video .\path\to\input.mp4 --no-viewer
```

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

This means the selected image folder passed into `scripts/run_colmap.py` is empty. Check earlier extraction and filtering stages first.

### `COLMAP executable not found`

Check:

- `config.json`
- `colmap_bin/COLMAP-3.9.1-windows-cuda/`
- the PATH setup in `run_pipeline.ps1`

### `ModuleNotFoundError` for `cv2` or `numpy`

Those packages are used by the current scripts but are not listed in `requirements.txt` yet.

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
