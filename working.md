# 3D Reconstruction Working Notes

This document provides a live technical status of the Frame2Scene project, detailing the implementation specifics, current tuning, and known behaviors.

## Current Technical Status

### 1. Frame Extraction Logic (`scripts/extract_frames.py`)
The extraction process is designed to balance reconstruction quality with processing speed.

**Implementation Details:**
- **FFmpeg stage**: `fps={fps},scale='min({max_width},iw)':-1`. High quality (`-q:v 2`) is used to minimize compression artifacts.
- **Sharpness**: Uses `cv2.Laplacian` variance. Frames with low variance (blurred) are discarded.
- **Redundancy Filter**:
    - **Farneback Optical Flow**: Measures pixel-wise motion. Frames with mean magnitude below `min_flow_magnitude` are treated as static and rejected.
    - **Histogram Comparison**: Correlation-based check (`cv2.HISTCMP_CORREL`). Captures lighting/content shifts.
- **Continuity Guard**: A `max_frame_gap` (default 3) ensures that even if motion is low, we don't lose the "thread" of the sequence, preventing sparse reconstruction failures.

### 2. Reconstruction Pipeline (`scripts/run_colmap.py`)
The COLMAP wrapper is the core "intelligent" component of the backend.

**COLMAP Stage Parameters:**
- **Feature Extraction**:
    - `max_num_features`: 8192
    - `estimate_affine_shape`: 1 (Improves matching on slanted surfaces)
    - `domain_size_pooling`: 1 (Better scale invariance)
- **Mapper**:
    - `multiple_models`: 1 (Allows COLMAP to create sub-clouds if the whole sequence doesn't link)
    - `extract_colors`: 1
- **Dense Stereo (PatchMatch)**:
    - `geom_consistency`: 1 (Higher quality, checks depth consistency across views)
    - `num_iterations`: 9 (Configurable in `config.json`)
    - `filter_min_num_consistent`: 5 (Reduces noise in the point cloud)

**The Fallback System:**
The pipeline detects failures in the dense stage (usually `std::bad_alloc` or CUDA OOM) and cycles through:
1. **Best**: 2304px, 9 iterations.
2. **Standard**: 1920px (1080p target).
3. **Safe**: 1600px, 7 iterations.
4. **Emergency**: 1600px + pruning image count to 180 frames.

### 3. Monitoring Engine (`scripts/monitor.py`)
This is a background thread that samples system state every 1.0s.

**Outputs generated per run:**
- `metrics.csv`: Full time-series of hardware usage.
- `events.jsonl`: Log of stage starts, ends, and errors.
- `stage_summary.json`: Final report including performance scores and insights.
- `cpu_usage_over_time.csv` & `gpu_usage_over_time.csv`: Data for visualization.

**Performance Score Formula:**
```text
Score = (GPU_Util * 0.4) + (Runtime_Efficiency * 0.35) + (Processing_Efficiency * 0.25)
```
- **GPU_Util**: Average utilization during the `patch_match_stereo` stage.
- **Runtime_Efficiency**: Scaled by how close the total time is to an "ideal" 1-hour window.
- **Processing_Efficiency**: Average time taken per image.

### 4. Custom Viewer (`viewer/`)
The viewer is optimized for point-cloud visualization rather than triangle meshes.

**Technical Features:**
- **Sampling**: If a model exceeds 1,000,000 points, it is randomly sampled down to 500,000 for the GPU to maintain 60 FPS.
- **Robust Normalization**: 
    - Standard min-max normalization is broken by "stray" points (outliers).
    - We calculate the 0.5% and 99.5% quantiles for X, Y, and Z.
    - The model is scaled based on this "robust" extent.
- **PCA Alignment**:
    - Centroid Calculation: Translates the model to origin (0,0,0).
    - Eigen-decomposition: Uses Jacobi iterations to find the 3 principal axes of the point distribution.
    - Classification: Detects if the cloud is "Linear", "Planar", or "Volumetric".
    - Rotation: If the cloud is "Linear" or "Planar", it rotates the principal axis to the world Z-axis for a more natural viewing angle.

## Configuration Guide (`config.json`)

```json
{
  "fps": 5,
  "frame_selection": {
    "min_sharpness": 80.0,      // Increase if you get blurry results
    "min_flow_magnitude": 1.5,  // Increase for faster movement scans
    "target_max_frames": 220    // Decrease for faster reconstruction
  },
  "colmap": {
    "matcher": "sequential_matcher", // Use "exhaustive_matcher" for objects
    "max_image_size": 2304,          // 2304-2800 is sweet spot for 8GB+ VRAM
    "patch_match_stereo": {
      "num_iterations": 9           // 5 is fast, 9-12 is high quality
    }
  }
}
```

## Known Behaviors & Limitations

1. **Windows Dependency**: The resource monitor uses `GlobalMemoryStatusEx` (Windows-only) and the `run_pipeline.ps1` script is PowerShell-based.
2. **GPU Prerequisite**: COLMAP's dense reconstruction requires a CUDA-capable GPU. The pipeline will fail at the `patch_match_stereo` stage on AMD or Intel GPUs.
3. **Outliers**: Sparse reconstruction occasionally creates "stray" points floating far from the scene. The viewer's Robust Normalization and Grid toggle help mitigate the visual impact of these.
4. **Orientation**: Photogrammetry has no absolute "up". Use the `F` key in the viewer to flip the model if it appears upside-down.

## Recent Changes

- **Added Resource Guard**: Prevents pipeline crashes by checking RAM/VRAM before heavy stages.
- **Multi-Level Fallback**: Implemented automatic resolution scaling for dense reconstruction.
- **Enhanced Monitoring**: Added performance scoring and run comparisons.
- **PCA Alignment**: Improved viewer initial orientation and centering.
- **Adaptive Frame Selection**: Replaced fixed FPS extraction with content-aware selection.
