import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from tqdm import tqdm


if sys.version_info < (3, 10):
    raise RuntimeError("Python 3.10+ is required.")


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_executable(executable):
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


def _clean_path(path):
    path = Path(path)
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _has_input_images(image_dir):
    image_extensions = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    return any(image_dir.glob(pattern) for pattern in image_extensions)


def run_step(name, cmd, log_file):
    tqdm.write(f"{name}...")
    subprocess.run(cmd, stdout=log_file, stderr=log_file, check=True)


def run_colmap(image_dir, sparse_dir, dense_dir, database_path, options):
    image_dir = Path(image_dir).resolve()
    sparse_dir = Path(sparse_dir).resolve()
    dense_dir = Path(dense_dir).resolve()
    database_path = Path(database_path).resolve()

    if not image_dir.exists() or not _has_input_images(image_dir):
        raise RuntimeError(f"No input images found in: {image_dir}")

    colmap = _resolve_executable(options.get("executable", "colmap"))
    use_gpu = bool(options.get("use_gpu", True))
    gpu_flag = "1" if use_gpu else "0"
    gpu_index = str(options.get("gpu_index", 0)) if use_gpu else "-1"
    camera_model = options.get("camera_model", "SIMPLE_RADIAL")
    single_camera = "1" if options.get("single_camera", True) else "0"
    max_image_size = str(options.get("max_image_size", 2000))

    sparse_model = sparse_dir / "0"
    fused_ply = dense_dir / "0" / "fused.ply"
    logs_dir = PROJECT_ROOT / "logs"
    log_path = logs_dir / "colmap.log"

    tqdm.write("Cleaning previous outputs...")
    _clean_path(database_path)
    _clean_path(sparse_dir)
    _clean_path(dense_dir)

    sparse_dir.mkdir(parents=True, exist_ok=True)
    dense_dir.mkdir(parents=True, exist_ok=True)
    fused_ply.parent.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        (
            "Feature Extraction",
            [
                colmap,
                "feature_extractor",
                "--database_path",
                str(database_path),
                "--image_path",
                str(image_dir),
                "--ImageReader.camera_model",
                camera_model,
                "--ImageReader.single_camera",
                single_camera,
                "--SiftExtraction.use_gpu",
                gpu_flag,
            ],
        ),
        (
            "Matching",
            [
                colmap,
                "sequential_matcher",
                "--database_path",
                str(database_path),
                "--SiftMatching.use_gpu",
                gpu_flag,
            ],
        ),
        (
            "Sparse Reconstruction",
            [
                colmap,
                "mapper",
                "--database_path",
                str(database_path),
                "--image_path",
                str(image_dir),
                "--output_path",
                str(sparse_dir),
            ],
        ),
        (
            "Undistort",
            [
                colmap,
                "image_undistorter",
                "--image_path",
                str(image_dir),
                "--input_path",
                str(sparse_model),
                "--output_path",
                str(dense_dir),
                "--output_type",
                "COLMAP",
                "--max_image_size",
                max_image_size,
            ],
        ),
        (
            "Dense Stereo",
            [
                colmap,
                "patch_match_stereo",
                "--workspace_path",
                str(dense_dir),
                "--workspace_format",
                "COLMAP",
                "--PatchMatchStereo.gpu_index",
                gpu_index,
                "--PatchMatchStereo.geom_consistency",
                "1",
            ],
        ),
        (
            "Fusion",
            [
                colmap,
                "stereo_fusion",
                "--workspace_path",
                str(dense_dir),
                "--workspace_format",
                "COLMAP",
                "--input_type",
                "geometric",
                "--output_path",
                str(fused_ply),
            ],
        ),
    ]

    start = time.time()
    pbar = tqdm(total=len(steps), desc="COLMAP Pipeline", ncols=80)

    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n=== COLMAP pipeline started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            for name, cmd in steps:
                run_step(name, cmd, log_file)
                if name == "Sparse Reconstruction" and not sparse_model.exists():
                    raise RuntimeError(f"Sparse reconstruction failed. Missing model folder: {sparse_model}")
                pbar.update(1)
    finally:
        pbar.close()

    runtime = time.time() - start

    if os.path.exists(fused_ply):
        print("SUCCESS: Reconstruction complete")
    else:
        print("ERROR: fused.ply missing")
        raise RuntimeError(f"Point cloud not found: {fused_ply}")

    print(f"Point cloud saved at: {fused_ply}")
    print(f"Log saved at: {log_path}")
    print(f"Total runtime: {runtime:.2f} seconds")

    return fused_ply
