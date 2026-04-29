# XLR8 Code Snippets

## 1. main.py
### Overview
Entry point of the pipeline. It handles video selection, folder setup, and coordinates the frame extraction and COLMAP reconstruction steps.

### Key Snippet
```python
def main():
    parser = argparse.ArgumentParser(description="Room-scale video-to-COLMAP reconstruction pipeline.")
    parser.add_argument("--video", help="Path to the input video. If omitted, the first video in data/input_video is used.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    args = parser.parse_args()

    settings = load_settings(args.config)
    paths = settings["paths"]

    input_video_dir = project_path(paths["input_video_dir"]).resolve()
    image_dir = project_path(paths["image_dir"]).resolve()

    video_path = prepare_video(args.video, input_video_dir)

    print("[1/2] Extracting frames")
    run_python_script(
        PROJECT_ROOT / "scripts" / "extract_frames.py",
        ["--video", str(video_path), "--output-dir", str(image_dir)],
    )

    print("[2/2] Running reconstruction")
    run_python_script(
        PROJECT_ROOT / "scripts" / "run_colmap.py",
        ["--config", str(Path(args.config).resolve()), "--image-dir", str(image_dir)],
    )
```

### Explanation
- `load_settings` reads the project configuration from `config.json` to define directory paths and processing parameters.
- `prepare_video` ensures the input video exists and copies it to the internal `data/input_video` directory if it's not already there.
- `run_python_script` executes the extraction and COLMAP scripts as separate subprocesses using the current Python interpreter.
- The pipeline follows a strict sequence: first extracting viewpoints from the video, then passing those images to the COLMAP engine.

---

## 2. scripts/extract_frames.py
### Overview
Uses FFmpeg to convert an input video into a series of JPEG images at a fixed frame rate (FPS) and resizes them to optimize reconstruction performance.

### Key Snippet
```python
def extract_frames(video_path, image_dir):
    """Extract all video viewpoints at a fixed FPS for room-scale reconstruction."""
    video_path = Path(video_path).resolve()
    image_dir = Path(image_dir).resolve()

    image_dir.mkdir(parents=True, exist_ok=True)
    for image_file in image_dir.glob("*.jpg"):
        image_file.unlink()

    output_pattern = image_dir / "frame_%04d.jpg"
    scale_filter = f"fps={FPS},scale='min({MAX_WIDTH},iw)':-1"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        scale_filter,
        "-q:v",
        "2",
        str(output_pattern),
    ]

    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

### Explanation
- `image_dir.mkdir` and the subsequent `unlink` loop ensure a clean output directory before extraction begins.
- The FFmpeg filter `fps=4` samples the video at a consistent rate to provide sufficient overlap for SfM matching.
- `scale='min(1200,iw)':-1` ensures that high-resolution videos are downscaled to 1200px width while maintaining the aspect ratio.
- `subprocess.run` executes the command with `-q:v 2` to ensure high-quality JPEG output which is critical for feature detection.

---

## 3. scripts/run_colmap.py
### Overview
Orchestrates the COLMAP SfM (Structure-from-Motion) and MVS (Multi-View Stereo) pipeline, handling everything from feature matching to dense point cloud fusion.

### Key Snippet
```python
    steps = [
        ("feature", [colmap, "feature_extractor", "--database_path", str(database_path), ...]),
        ("match", [colmap, matcher_type, "--database_path", str(database_path), ...]),
        ("map", [colmap, "mapper", "--database_path", str(database_path), ...]),
    ]

    for name, command in steps:
        run_step(name, command, log_file)

    best_sparse = find_best_model(sparse_dir)
    
    run_step("undistort", [colmap, "image_undistorter", "--input_path", str(best_sparse), ...], log_file)
    
    run_step("dense", [colmap, "patch_match_stereo", "--workspace_path", str(dense_dir), ...], log_file)
    
    run_step("fuse", [colmap, "stereo_fusion", "--output_path", str(fused_ply), ...], log_file)
```

### Explanation
- `matcher_type` is dynamically chosen between `exhaustive` and `sequential` based on whether the image count exceeds 500.
- `run_step` wraps the execution of each COLMAP command, logging all stdout/stderr to a dedicated log file for monitoring.
- `find_best_model` identifies the largest reconstruction fragment (most points) to use for the subsequent dense reconstruction phase.
- The pipeline concludes with `stereo_fusion`, which merges depth maps into a final `fused.ply` point cloud file.

---

## 4. scripts/progress_monitor.py
### Overview
A real-time monitoring tool that parses the COLMAP log file to display a progress bar and granular statistics using the `tqdm` library.

### Key Snippet
```python
def update_state_from_line(line, state):
    if line.startswith("[STEP] "):
        raw_step = line[7:].strip()
        mapped_step = STEP_LABELS.get(raw_step, raw_step)
        if mapped_step in STEP_ORDER:
            state["current_step"] = mapped_step
            state["completed_steps"] = max(state["completed_steps"], STEP_ORDER.index(mapped_step))

    if "Processed file" in line:
        state["feature_count"] += 1
    if "Matching block" in line or "Matching image" in line:
        state["match_count"] += 1
    if "Registering image" in line:
        state["map_count"] += 1
```

### Explanation
- `update_state_from_line` scans the log for custom `[STEP]` markers emitted by the pipeline script to update the overall progress.
- It tracks "Processed file" strings to increment the feature extraction counter, providing visual feedback on individual image progress.
- "Registering image" matches indicate that the Sparse Mapper is successfully triangulating camera poses and points.
- The monitor utilizes a `while True` loop with `log_file.seek` to tail the log file without reloading the entire content from disk.

---

## 5. viewer/main.cpp
### Overview
A C++/Raylib-based 3D point cloud viewer that loads the reconstruction, aligns it to the ground plane using PCA, and provides navigation.

### Key Snippet
```cpp
    while (!WindowShouldClose()) {
        UpdateCameraFPS(cameraState, camera);

        if (IsKeyPressed(KEY_F)) {
            FlipY(viewerState);
        }

        BeginDrawing();
        ClearBackground(BLACK);

        BeginMode3D(camera);
        if (viewerState.showGrid) DrawGrid(20, 0.1f);
        DrawPointCloud(viewerState.renderPoints);
        EndMode3D();

        DrawFPS(10, 10);
        DrawText(TextFormat("Points: %i / %i", static_cast<int>(viewerState.renderPoints.size()), ...), 10, 34, 20, RAYWHITE);
        EndDrawing();
    }
```

### Explanation
- `UpdateCameraFPS` calculates the new camera position based on WASD input and mouse rotation (yaw/pitch).
- `BeginMode3D` sets up the perspective projection matrix based on the current camera state before rendering points.
- `DrawPointCloud` iterates through the sampled vertex buffer and uses `DrawPoint3D` to render individual RGB points.
- The loop handles real-time UI updates, displaying the point count, frame rate, and current orientation state (Normal/Flipped).

---

## 6. run_pipeline.ps1
### Overview
The primary PowerShell entry script for Windows. It configures the environment, clears old data, and launches the pipeline and monitor together.

### Key Snippet
```powershell
    $pipelineArgs = @($mainScript) + $args
    $pipelineProcess = Start-Process -FilePath $pythonExe -ArgumentList $pipelineArgs -PassThru
    & $pythonExe $monitorScript --pid $pipelineProcess.Id
    $pipelineProcess.WaitForExit()

    if ($pipelineProcess.ExitCode -ne 0) {
        throw "Pipeline failed with exit code $($pipelineProcess.ExitCode)"
    }
```

### Explanation
- `Start-Process -PassThru` launches the main Python pipeline as a background process so the PowerShell script can continue.
- The script immediately executes the `progress_monitor.py` script in the foreground, passing it the `$pipelineProcess.Id`.
- `$pipelineProcess.WaitForExit()` ensures the script blocks until the reconstruction is finished or has failed.
- The script performs pre-flight checks on `$env:Path` to ensure `colmap.exe` and `ffmpeg.exe` are visible to the system.

---

## 7. config.json
### Overview
Central configuration file defining the parameters for frame extraction, project directory structure, and COLMAP engine settings.

### Full File
```json
{
  "fps": 4,
  "paths": {
    "input_video_dir": "data/input_video",
    "image_dir": "data/images",
    "sparse_dir": "data/sparse",
    "dense_dir": "data/dense",
    "database_path": "data/database.db",
    "output_ply": "data/dense/0/fused.ply"
  },
  "colmap": {
    "executable": "colmap_bin/COLMAP-3.9.1-windows-cuda/COLMAP.bat",
    "use_gpu": true,
    "camera_model": "SIMPLE_RADIAL",
    "single_camera": true,
    "matcher": "sequential_matcher",
    "max_image_size": 1200
  }
}
```

### Explanation
- `fps` determines the temporal density of extracted images; a value of 4 is optimized for standard walking-speed room scans.
- `use_gpu` enables CUDA acceleration, which significantly reduces the time required for Sift extraction and PatchMatch stereo.
- `camera_model` set to `SIMPLE_RADIAL` provides a robust balance between lens distortion correction and computational stability.
- `max_image_size` limits the resolution of images processed by COLMAP to prevent out-of-memory errors on consumer GPUs.
