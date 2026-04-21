# Hybrid 3D Reconstruction Pipeline

This project turns a video into a COLMAP reconstruction, saves the dense point cloud to `data/dense/0/fused.ply`, and opens it in a lightweight Raylib viewer.

## What The Pipeline Does

The current workflow is:

1. Read a video from `--video` or from `data/input_video/`.
2. Extract JPG frames into `data/images/` with FFmpeg.
3. Clean old COLMAP outputs:
   - `data/database.db`
   - `data/sparse/`
   - `data/dense/`
4. Run the COLMAP pipeline with a quiet `tqdm` progress bar.
5. Save COLMAP logs to `logs/colmap.log`.
6. Write the dense point cloud to:

```text
data/dense/0/fused.ply
```

7. Optionally compile and launch the C++ point cloud viewer.

## Project Layout

```text
3D_Reconstruction/
|-- config.json
|-- main.py
|-- run_pipeline.ps1
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
|   `-- run_colmap.py
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
- FFmpeg available on `PATH`
- COLMAP with CUDA support
- `tqdm` installed in the project virtual environment
- `g++` for rebuilding the viewer
- Raylib headers and libraries in `raylib/raylib-5.5_win64_mingw-w64/`

The current environment in this project already uses:

- Python virtual environment: `venv/`
- COLMAP path from `config.json`:

```json
"executable": "colmap_bin/COLMAP-3.9.1-windows-cuda/COLMAP.bat"
```

If COLMAP is installed globally, you can switch that to:

```json
"executable": "colmap"
```

## Main Entry Points

### Python

Run directly:

```powershell
.\venv\Scripts\python.exe .\main.py --video path\to\input.mp4
```

If `--video` is omitted, `main.py` uses the first supported video found in `data/input_video/`.

Useful flags:

```powershell
.\venv\Scripts\python.exe .\main.py --no-viewer
.\venv\Scripts\python.exe .\main.py --skip-viewer-build
.\venv\Scripts\python.exe .\main.py --config .\config.json
```

### PowerShell

Run the project launcher:

```powershell
.\run_pipeline.ps1
```

This script:

- resolves paths from the script location instead of the current shell folder
- adds FFmpeg and COLMAP to `PATH`
- uses `venv\Scripts\python.exe` when available
- forwards any extra arguments to `main.py`

Example:

```powershell
.\run_pipeline.ps1 --video .\data\input_video\sample.mp4 --no-viewer
```

## Frame Extraction

`scripts/extract_frames.py` uses FFmpeg to:

- overwrite previous frame output
- extract frames at the configured FPS
- write images as:

```text
data/images/frame_000001.jpg
data/images/frame_000002.jpg
...
```

The FPS is controlled by `config.json`:

```json
{
  "fps": 2
}
```

Lower FPS is faster. Higher FPS produces more overlap and can help reconstruction quality, but also increases runtime and memory use.

## COLMAP Pipeline

`scripts/run_colmap.py` runs six steps with `subprocess.run(..., check=True)` and sends all COLMAP output to `logs/colmap.log`.

The steps are:

1. `feature_extractor`
2. `sequential_matcher`
3. `mapper`
4. `image_undistorter`
5. `patch_match_stereo`
6. `stereo_fusion`

The terminal stays mostly clean:

- each stage name is printed with `tqdm.write(...)`
- a progress bar shows overall status
- COLMAP stdout and stderr are appended to `logs/colmap.log`

At the end, the script checks for:

```text
data/dense/0/fused.ply
```

and prints:

- success or failure
- saved point cloud path
- log file path
- total runtime

## Viewer

The viewer source is:

```text
viewer/main.cpp
```

The Python pipeline can rebuild it automatically before launch. The executable path is:

```text
viewer/viewer.exe
```

### Manual Viewer Build

If you want to compile it yourself:

```powershell
g++ .\viewer\main.cpp -o .\viewer\viewer.exe -std=c++17 -IC:\Extra_s\Code\C++_project\3D_Reconstruction\raylib\raylib-5.5_win64_mingw-w64\include -LC:\Extra_s\Code\C++_project\3D_Reconstruction\raylib\raylib-5.5_win64_mingw-w64\lib -lraylib -lopengl32 -lgdi32 -lwinmm
```

### Manual Viewer Launch

```powershell
.\viewer\viewer.exe .\data\dense\0\fused.ply
```

### Viewer Controls

- Right mouse button drag: rotate camera
- Mouse wheel: move forward and backward
- `W`, `A`, `S`, `D`: move
- `Q` / `E`: move down / up
- `Shift`: faster movement
- `1`, `2`, `3`: point size
- `G`: toggle grid
- `R`: reset camera

## Configuration

Current `config.json`:

```json
{
  "fps": 2,
  "paths": {
    "input_video_dir": "data/input_video",
    "image_dir": "data/images",
    "sparse_dir": "data/sparse",
    "dense_dir": "data/dense",
    "database_path": "data/database.db",
    "output_ply": "data/dense/fused.ply"
  },
  "colmap": {
    "executable": "colmap_bin/COLMAP-3.9.1-windows-cuda/COLMAP.bat",
    "use_gpu": true,
    "camera_model": "SIMPLE_RADIAL",
    "single_camera": true,
    "matcher": "exhaustive",
    "max_image_size": 2000
  }
}
```

Important note:

- The active pipeline code writes to `data/dense/0/fused.ply`.
- The `paths.output_ply` value in `config.json` still says `data/dense/fused.ply`.
- `main.py` currently uses the path returned by `run_colmap.py`, so the pipeline still works.
- That config entry is now stale and should be updated if you want the config to match the implementation.

## Logs

All COLMAP command output is appended to:

```text
logs/colmap.log
```

This is the first place to check when reconstruction fails.

## Typical Run

```powershell
.\run_pipeline.ps1 --video .\data\input_video\sample.mp4
```

Expected high-level flow:

1. Video is copied into `data/input_video/` if needed.
2. Frames are extracted into `data/images/`.
3. Old COLMAP outputs are deleted.
4. The COLMAP progress bar advances through the six stages.
5. `data/dense/0/fused.ply` is created.
6. The viewer opens the result unless `--no-viewer` was passed.

## Troubleshooting

### `ffmpeg was not found`

FFmpeg is not on `PATH`. Install FFmpeg or update `run_pipeline.ps1` so it points to the correct FFmpeg `bin` folder.

### `COLMAP executable not found`

Check `config.json` and make sure `colmap.executable` points to a valid `COLMAP.bat`, `COLMAP.exe`, or global `colmap` command.

### `No input images found`

Frame extraction did not produce any JPG files in `data/images/`, or the folder is empty.

### `Sparse reconstruction failed. Missing model folder: data/sparse/0`

COLMAP could not build a sparse model. Common causes:

- too few frames
- weak overlap between frames
- motion blur
- repetitive or textureless surfaces
- reflective or transparent objects

### `ERROR: fused.ply missing`

Dense reconstruction failed. Check `logs/colmap.log` for the failing COLMAP stage.

### Viewer says `Input is not a PLY file`

That issue was caused by CRLF header parsing and has been fixed in the current viewer. Rebuild the viewer if you are still running an older `viewer.exe`.

### Viewer opens but shows the wrong file or nothing useful

Launch it directly with the actual dense output:

```powershell
.\viewer\viewer.exe .\data\dense\0\fused.ply
```

## Notes On Performance And Quality

- `sequential_matcher` is used now, which is a better fit for video frame sequences than exhaustive matching.
- GPU is enabled through `SiftExtraction.use_gpu`, `SiftMatching.use_gpu`, and `PatchMatchStereo.gpu_index`.
- `max_image_size` controls the dense stage memory and speed tradeoff.
- Higher frame counts can improve coverage, but they also slow down matching and dense stereo.

## Current Reality Check

This document matches the code in:

- [main.py](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/main.py:1)
- [scripts/run_colmap.py](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/scripts/run_colmap.py:1)
- [run_pipeline.ps1](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/run_pipeline.ps1:1)
- [viewer/main.cpp](/abs/path/c:/Extra_s/Code/C++_project/3D_Reconstruction/viewer/main.cpp:1)

If those files change again, update this doc at the same time so it keeps telling the truth.
