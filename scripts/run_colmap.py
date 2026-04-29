import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.resource_guard import (
    check_resources_before_dense,
    check_colmap_error_log,
    enforce_frame_limit,
    prepare_dry_run_dataset
)

if sys.version_info < (3, 10):
    raise RuntimeError("Python 3.10+ is required.")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.json"


def load_settings(config_path):
    with Path(config_path).resolve().open("r", encoding="utf-8") as file:
        return json.load(file)


def project_path(relative_or_absolute_path):
    path = Path(relative_or_absolute_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def resolve_executable(executable):
    executable_path = Path(executable)
    if executable_path.is_absolute() and executable_path.exists():
        return str(executable_path)

    project_relative = PROJECT_ROOT / executable_path
    if project_relative.exists():
        return str(project_relative.resolve())

    found = shutil.which(executable)
    if found:
        return found

    raise RuntimeError(
        f"COLMAP executable not found: {executable}. Add COLMAP to PATH or set a valid path in config.json."
    )


def clean_path(path):
    path = Path(path)
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def has_input_images(image_dir):
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    for pattern in patterns:
        if any(image_dir.glob(pattern)):
            return True
    return False


def write_log_line(log_file, text):
    log_file.write(f"{text}\n")
    log_file.flush()
    print(text)


def to_colmap_bool(value, default=False):
    if value is None:
        value = default
    return "1" if bool(value) else "0"


def validate_gpu_workload(use_gpu, max_image_size, patch_match, log_file):
    if not use_gpu:
        return

    warnings = []
    if max_image_size < 2000:
        warnings.append(
            f"max_image_size={max_image_size} is low for dense GPU utilization; use at least 2000 and preferably 2200-2800 if VRAM allows."
        )
    if int(patch_match.get("num_iterations", 0)) < 8:
        warnings.append(
            f"PatchMatchStereo.num_iterations={patch_match.get('num_iterations')} is likely too low to keep the GPU busy during dense reconstruction."
        )
    if int(patch_match.get("window_radius", 0)) < 6:
        warnings.append(
            f"PatchMatchStereo.window_radius={patch_match.get('window_radius')} is likely too small for meaningful dense-stage GPU load."
        )

    for warning in warnings:
        write_log_line(log_file, f"[WARN] {warning}")


def emit_stage_event(stage_callback, event_type, stage_name, command, **extra):
    if stage_callback is None:
        return
    payload = {
        "event": event_type,
        "stage": stage_name,
        "command": list(command) if command else [],
    }
    payload.update(extra)
    stage_callback(payload)


def build_match_command(colmap, matcher_type, database_path, gpu_flag, gpu_index, num_threads, options):
    command = [
        colmap,
        matcher_type,
        "--database_path",
        str(database_path),
        "--SiftMatching.use_gpu",
        gpu_flag,
        "--SiftMatching.gpu_index",
        gpu_index,
        "--SiftMatching.num_threads",
        num_threads,
        "--SiftMatching.guided_matching",
        "1",
        "--SiftMatching.max_num_matches",
        "65536",
    ]

    if matcher_type == "sequential_matcher":
        sequential_options = options.get("sequential_matcher", {})
        command.extend([
            "--SequentialMatching.overlap",
            str(sequential_options.get("overlap", 15)),
            "--SequentialMatching.quadratic_overlap",
            to_colmap_bool(sequential_options.get("quadratic_overlap", False)),
            "--SequentialMatching.loop_detection",
            to_colmap_bool(sequential_options.get("loop_detection", False)),
        ])

    return command


def run_step(name, command, log_file, stage_callback=None):
    write_log_line(log_file, f"[STEP] {name}")
    write_log_line(log_file, f"[CMD] {' '.join(command)}")
    emit_stage_event(stage_callback, "stage_start", name, command)
    start_time = time.time()
    try:
        subprocess.run(command, stdout=log_file, stderr=log_file, check=True)
        emit_stage_event(
            stage_callback,
            "stage_end",
            name,
            command,
            success=True,
            duration_seconds=time.time() - start_time,
        )
    except subprocess.CalledProcessError as error:
        emit_stage_event(
            stage_callback,
            "stage_end",
            name,
            command,
            success=False,
            duration_seconds=time.time() - start_time,
            returncode=error.returncode,
        )
        raise


def find_best_model(sparse_dir):
    sparse_path = Path(sparse_dir)
    models = [d for d in sparse_path.iterdir() if d.is_dir() and (d / "points3D.bin").exists()]
    if not models:
        models = [d for d in sparse_path.iterdir() if d.is_dir() and (d / "points3D.txt").exists()]
    
    if not models:
        return None
    
    best_model = None
    max_size = -1
    
    for model in models:
        p_bin = model / "points3D.bin"
        p_txt = model / "points3D.txt"
        size = 0
        if p_bin.exists():
            size = p_bin.stat().st_size
        elif p_txt.exists():
            size = p_txt.stat().st_size
            
        if size > max_size:
            max_size = size
            best_model = model
            
    return best_model


def run_colmap(image_dir, sparse_dir, dense_dir, database_path, output_ply, options, log_path, stage_callback=None, resume=False, is_dry_run=False):
    image_dir = Path(image_dir).resolve()
    sparse_dir = Path(sparse_dir).resolve()
    dense_dir = Path(dense_dir).resolve()
    database_path = Path(database_path).resolve()
    output_ply = Path(output_ply).resolve()
    log_path = Path(log_path).resolve()

    if not image_dir.exists() or not has_input_images(image_dir):
        raise RuntimeError(f"No input images found in: {image_dir}")

    colmap = resolve_executable(options.get("executable", "colmap"))
    use_gpu = bool(options.get("use_gpu", True))
    gpu_flag = to_colmap_bool(use_gpu, default=True)
    gpu_index = str(options.get("gpu_index", 0)) if use_gpu else "-1"
    num_threads = str(options.get("num_threads", 8))
    camera_model = str(options.get("camera_model", "SIMPLE_RADIAL"))
    single_camera_flag = to_colmap_bool(options.get("single_camera", True), default=True)
    matcher_type = str(options.get("matcher", "exhaustive_matcher"))
    
    patch_match = options.get("patch_match_stereo", {})
    patch_match_geom_consistency = to_colmap_bool(patch_match.get("geom_consistency", True), default=True)
    patch_match_num_iterations = str(patch_match.get("num_iterations", 7))
    patch_match_window_radius = str(patch_match.get("window_radius", 7))
    patch_match_filter_min_num_consistent = str(patch_match.get("filter_min_num_consistent", 5))
    max_image_size = int(options.get("max_image_size", 2000))

    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not resume:
        clean_path(database_path)
        clean_path(sparse_dir)
        clean_path(dense_dir)
        sparse_dir.mkdir(parents=True, exist_ok=True)
        dense_dir.mkdir(parents=True, exist_ok=True)
        output_ply.parent.mkdir(parents=True, exist_ok=True)

    image_count = sum(len(list(image_dir.glob(pattern))) for pattern in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"))
    
    start_time = time.time()

    with log_path.open("a" if resume else "w", encoding="utf-8") as log_file:
        write_log_line(log_file, f"=== COLMAP pipeline started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        write_log_line(log_file, f"[INFO] Resume mode: {resume}")
        write_log_line(log_file, f"[INFO] Dry Run: {is_dry_run}")
        write_log_line(log_file, f"[INFO] Images: {image_dir} ({image_count} images)")
        
        try:
            if not resume:
                run_step("feature_extractor", [
                    colmap, "feature_extractor",
                    "--database_path", str(database_path),
                    "--image_path", str(image_dir),
                    "--ImageReader.camera_model", camera_model,
                    "--ImageReader.single_camera", single_camera_flag,
                    "--SiftExtraction.use_gpu", gpu_flag,
                    "--SiftExtraction.gpu_index", gpu_index,
                    "--SiftExtraction.num_threads", num_threads,
                    "--SiftExtraction.max_num_features", "8192",
                    "--SiftExtraction.estimate_affine_shape", "1",
                    "--SiftExtraction.domain_size_pooling", "1",
                ], log_file, stage_callback)

                match_command = build_match_command(colmap, matcher_type, database_path, gpu_flag, gpu_index, num_threads, options)
                run_step(matcher_type, match_command, log_file, stage_callback)

                run_step("mapper", [
                    colmap, "mapper",
                    "--database_path", str(database_path),
                    "--image_path", str(image_dir),
                    "--output_path", str(sparse_dir),
                    "--Mapper.num_threads", num_threads,
                    "--Mapper.multiple_models", "1",
                    "--Mapper.extract_colors", "1",
                ], log_file, stage_callback)

            best_sparse = find_best_model(sparse_dir)
            if not best_sparse:
                 raise RuntimeError(f"Sparse reconstruction failed. No models found in: {sparse_dir}")
            
            write_log_line(log_file, f"[INFO] Using best sparse model: {best_sparse}")
            
            # --- PRE-DENSE RESOURCE CHECK & FALLBACK LOGIC ---
            
            def run_dense_block(img_size, pm_iterations):
                # Always re-run undistorter if we are retrying dense
                run_step("image_undistorter", [
                    colmap, "image_undistorter",
                    "--image_path", str(image_dir),
                    "--input_path", str(best_sparse),
                    "--output_path", str(dense_dir),
                    "--output_type", "COLMAP",
                    "--max_image_size", str(img_size),
                ], log_file, stage_callback=stage_callback)
                
                # Check resources right before dense
                is_safe, adjustments, reason = check_resources_before_dense(
                    num_images=image_count, 
                    max_image_size=img_size, 
                    gpu_index=int(gpu_index) if gpu_index != "-1" else 0
                )
                
                write_log_line(log_file, f"[RESOURCE GUARD] {reason}")
                if not is_safe:
                    write_log_line(log_file, f"[RESOURCE GUARD] Warning: Resources tight. Adjustments suggested: {adjustments}")
                    # If this is the first attempt, we could apply adjustments immediately, 
                    # but we are in a fallback loop, so we'll just try and let it fail if needed, 
                    # OR we could preemptively fail to save time. The prompt says: "If insufficient: STOP immediately -> Suggest reduced config"
                    # We will implement this as: if the initial run (Level 0) fails the check, we auto-scale.
                
                run_step("patch_match_stereo", [
                    colmap, "patch_match_stereo",
                    "--workspace_path", str(dense_dir),
                    "--workspace_format", "COLMAP",
                    "--PatchMatchStereo.use_gpu", gpu_flag,
                    "--PatchMatchStereo.geom_consistency", patch_match_geom_consistency,
                    "--PatchMatchStereo.num_iterations", str(pm_iterations),
                    "--PatchMatchStereo.window_radius", patch_match_window_radius,
                    "--PatchMatchStereo.filter_min_num_consistent", patch_match_filter_min_num_consistent,
                    "--PatchMatchStereo.gpu_index", gpu_index,
                ], log_file, stage_callback=stage_callback)

            # Auto-Scale Initial Config if needed
            is_safe, init_adjustments, guard_reason = check_resources_before_dense(
                image_count, max_image_size, int(gpu_index) if gpu_index != "-1" else 0
            )
            write_log_line(log_file, f"[RESOURCE GUARD] Initial Check: {guard_reason}")
            
            current_max_image_size = max_image_size
            current_pm_iterations = int(patch_match_num_iterations)
            
            if not is_safe:
                write_log_line(log_file, f"[RESOURCE GUARD] Pre-emptively scaling config: {init_adjustments}")
                if 'max_image_size' in init_adjustments:
                    current_max_image_size = init_adjustments['max_image_size']
                if 'num_iterations' in init_adjustments:
                    current_pm_iterations = init_adjustments['num_iterations']

            success = False
            levels = [
                {"name": "Level 0 (Current Best)", "size": current_max_image_size, "iter": current_pm_iterations},
                {"name": "Level 1", "size": 1920, "iter": current_pm_iterations},
                {"name": "Level 2", "size": 1600, "iter": 7},
                {"name": "Level 3", "size": 1600, "iter": 7, "reduce_frames": True}
            ]

            for level in levels:
                write_log_line(log_file, f"[INFO] Attempting Dense Reconstruction: {level['name']} (Size: {level['size']}, Iter: {level['iter']})")
                
                try:
                    if level.get("reduce_frames") and image_count > 180:
                        write_log_line(log_file, f"[INFO] Level 3: Enforcing frame limit to 180...")
                        enforce_frame_limit(image_dir, 180)
                        # Re-run sparse because we changed the dataset!
                        write_log_line(log_file, f"[INFO] Dataset modified. Restarting from Feature Extractor...")
                        raise RuntimeError("Needs Full Restart with fewer frames (Resume failed at Level 3)")

                    run_dense_block(level['size'], level['iter'])
                    success = True
                    break
                except Exception as error:
                    error_type = check_colmap_error_log(log_path)
                    write_log_line(log_file, f"[ERROR] Dense step failed: {error_type}. Error: {error}")
                    write_log_line(log_file, f"[INFO] Falling back to next level...")
                    # Clean dense dir before retry
                    clean_path(dense_dir)
                    dense_dir.mkdir(parents=True, exist_ok=True)
            
            if not success:
                write_log_line(log_file, f"[FATAL] All fallback levels exhausted. Dense reconstruction failed.")
                write_log_line(log_file, f"[RECOMMENDATION] Resource bottleneck summary: {check_colmap_error_log(log_path)}")
                raise RuntimeError("Dense reconstruction failed after all fallbacks.")

            run_step("stereo_fusion", [
                colmap, "stereo_fusion",
                "--workspace_path", str(dense_dir),
                "--workspace_format", "COLMAP",
                "--input_type", "geometric",
                "--output_path", str(output_ply),
                "--StereoFusion.min_num_pixels", "8",
                "--StereoFusion.max_reproj_error", "1.0",
            ], log_file, stage_callback=stage_callback)

            runtime = time.time() - start_time

            if not output_ply.exists():
                write_log_line(log_file, "[ERROR] fused.ply missing")
                raise RuntimeError(f"Point cloud not found: {output_ply}")

            write_log_line(log_file, f"[DONE] Point cloud saved at: {output_ply}")
            write_log_line(log_file, f"[DONE] Total runtime: {runtime:.2f} seconds")
        except Exception as error:
            write_log_line(log_file, f"[ERROR] {error}")
            raise


def main():
    parser = argparse.ArgumentParser(description="Run a room-scale COLMAP reconstruction pipeline.")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.json")
    parser.add_argument("--image-dir", help="Override image directory. Defaults to data/images.")
    parser.add_argument("--resume", action="store_true", help="Resume from dense reconstruction")
    parser.add_argument("--dry-run", action="store_true", help="Run a dry run with 20 images")
    args = parser.parse_args()

    settings = load_settings(args.config)
    paths = settings["paths"]
    options = settings["colmap"]

    image_dir = project_path(args.image_dir).resolve() if args.image_dir else project_path(paths["image_dir"]).resolve()
    sparse_dir = project_path(paths["sparse_dir"]).resolve()
    dense_dir = project_path(paths["dense_dir"]).resolve()
    database_path = project_path(paths["database_path"]).resolve()
    output_ply = project_path(paths["output_ply"]).resolve()
    log_path = PROJECT_ROOT / "logs" / "colmap.log"

    run_colmap(
        image_dir=image_dir,
        sparse_dir=sparse_dir,
        dense_dir=dense_dir,
        database_path=database_path,
        output_ply=output_ply,
        options=options,
        log_path=log_path,
        resume=args.resume,
        is_dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
