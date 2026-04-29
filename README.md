# Frame2Scene

**Frame2Scene** is a high-performance, Windows-optimized photogrammetry pipeline that converts video footage into dense 3D point clouds using COLMAP and a custom high-performance Raylib viewer. It features adaptive frame selection, a multi-level resource-aware reconstruction fallback system, and real-time performance monitoring.

## Pipeline Architecture

The pipeline follows a structured flow designed for robustness and quality:

```text
Input Video -> Adaptive Extraction -> Sparse Reconstruction -> Dense Fallback Logic -> Fusion -> Custom Viewer
```

### 1. Adaptive Frame Extraction (`scripts/extract_frames.py`)
Instead of simple periodic sampling, Frame2Scene uses a multi-stage analysis to ensure the best possible input for COLMAP:
- **Raw Extraction**: FFmpeg extracts frames at a base FPS (default 5).
- **Sharpness Filtering**: Uses Laplacian variance to reject motion-blurred frames.
- **Motion & Content Analysis**:
    - **Histogram Difference**: Detects significant scene changes.
    - **Optical Flow (Farneback)**: Measures camera movement to ensure sufficient parallax without redundancy.
    - **Feature Change Ratio**: Tracks corner distribution changes using `goodFeaturesToTrack`.
- **Adaptive Selection**: Keeps frames only if they meet motion/content thresholds or to prevent excessive gaps (max 3 frames).
- **Target Optimization**: Aims for a target range (default 150-220 frames) for optimal reconstruction time vs. quality.

### 2. Monitored COLMAP Reconstruction (`scripts/run_colmap.py`)
A robust wrapper around COLMAP that implements automated error recovery and resource management:
- **Sift Features**: Uses GPU-accelerated extraction with affine shape estimation and domain size pooling.
- **Flexible Matching**: Supports `exhaustive_matcher` for objects and `sequential_matcher` (with loop detection) for paths/rooms.
- **Intelligent Fallback System**: If dense reconstruction fails (often due to VRAM/RAM limits), the pipeline automatically retries with progressively safer configurations:
    - **Level 0**: Original config (e.g., 2304px).
    - **Level 1**: Reduced resolution (1920px).
    - **Level 2**: Lower resolution (1600px) + reduced PatchMatch iterations.
    - **Level 3**: Strict frame count enforcement (max 180 frames) + minimum resolution.
- **Resource Guard**: Pre-emptively checks VRAM/RAM availability before the dense stage using `nvidia-smi` and Win32 APIs.

### 3. Pipeline Monitor & Analytics (`scripts/monitor.py`)
A real-time dashboard and logging system providing deep visibility into the process:
- **Metrics**: Tracks CPU (per-core), GPU utilization, VRAM, System RAM, and Disk I/O.
- **Alert System**: Detects and logs CPU throttling, memory pressure, and GPU underutilization during the dense stage.
- **Performance Scoring**: Calculates an efficiency score (0-100) based on GPU busy-time, runtime, and frames processed.
- **Comparative Analysis**: Compares the current run against previous sessions to detect regressions in speed or quality.

### 4. Custom 3D Viewer (`viewer/`)
A high-performance C++ application built with Raylib for inspecting large point clouds:
- **PCA Alignment**: Automatically centers the cloud and optionally rotates the principal axis to align with the world grid.
- **Robust Normalization**: Uses quantile-based (0.5% - 99.5%) scaling to eliminate "outlier" points that often break standard normalization.
- **Point-Cloud Rendering**: Uses `GL_POINTS` with custom shaders for clean visualization of millions of points.
- **Orientation Correction**: Supports manual Y-axis flipping to correct upside-down reconstructions.

---

## Project Structure

```text
3D_Reconstruction/
├── main.py                     # Primary orchestration layer
├── pipeline_runner.py          # Internal pipeline logic and monitoring integration
├── run_pipeline.ps1            # Windows entry point for full reconstruction
├── view_existing_model.ps1     # Quick entry point for the viewer
├── config.json                 # Central configuration for all stages
├── requirements.txt            # Python dependencies (tqdm, psutil, rich, opencv, pynvml)
├── scripts/
│   ├── extract_frames.py       # Adaptive frame selection logic
│   ├── run_colmap.py           # COLMAP runner with fallback logic
│   ├── monitor.py              # Performance monitoring engine
│   ├── resource_guard.py       # Hardware checks and dataset manipulation
│   └── progress_monitor.py     # Simple terminal progress tracker
├── viewer/
│   ├── main.cpp                # Viewer entry point and rendering logic
│   ├── ply_loader.cpp          # Optimized ASCII/Binary PLY loader
│   ├── alignment.cpp           # PCA and normalization math
│   └── viewer.exe              # Pre-compiled Windows binary
├── data/                       # Workspace for images, database, and models
├── logs/                       # Detailed logs and performance metrics
├── colmap_bin/                 # COLMAP binaries (CUDA enabled)
└── raylib/                     # Raylib development files
```

---

## Requirements

- **OS**: Windows 10/11
- **GPU**: NVIDIA GPU (CUDA support required for COLMAP)
- **Python**: 3.10+
- **Tools**: `ffmpeg` (must be in PATH)

---

## Configuration (`config.json`)

Key parameters in `config.json`:

- **`fps`**: Base extraction rate (default: 5).
- **`frame_selection`**:
    - `min_sharpness`: Reject blurry frames (default: 80.0).
    - `min_flow_magnitude`: Min motion required (default: 1.5).
    - `target_max_frames`: Soft cap for reconstruction speed (default: 220).
- **`colmap`**:
    - `max_image_size`: Resolution for reconstruction (default: 2304).
    - `matcher`: `sequential_matcher` or `exhaustive_matcher`.
    - `patch_match_stereo`: Tuning for dense quality (iterations, window size).

---

## Usage

### 1. Run the Full Pipeline
Provide a video file and let the pipeline handle the rest:

```powershell
.\run_pipeline.ps1 --video "C:\videos\room_scan.mp4"
```

### 2. View Existing Model
Instantly open the latest `fused.ply`:

```powershell
.\view_existing_model.ps1
```

### 3. Dry Run
Test the setup with a small subset (20 frames) of images:

```powershell
.\venv\Scripts\python.exe main.py --video "input.mp4" --dry-run
```

---

## Viewer Controls

| Key | Action |
|-----|--------|
| **RMB + Drag** | Rotate Camera |
| **W, A, S, D** | Movement |
| **Q / E** | Move Up / Down |
| **Mouse Wheel** | Zoom In / Out |
| **Shift** | Move Faster |
| **F** | Flip Y-Axis (Correction) |
| **U** | Toggle PCA Rotation Alignment |
| **N** | Toggle Robust Normalization |
| **G** | Toggle Grid |
| **R** | Reset Camera |
| **+/-** | Adjust Point Size |
| **F11** | Fullscreen |

---

## Troubleshooting

- **`ffmpeg` not found**: Ensure FFmpeg is installed and added to your System Environment Variables (PATH).
- **Out of Memory (OOM)**: The pipeline will attempt to downscale. If it still fails, reduce `max_image_size` in `config.json` to 1600.
- **No Reconstruction**: Ensure the video has significant camera movement (parallax). Static videos will fail at the Sparse stage.
- **Viewer won't open**: Ensure `viewer/viewer.exe` exists. You may need to compile it from `viewer/main.cpp` using the provided Raylib headers.
