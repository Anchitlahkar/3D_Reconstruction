import json
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path


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


def run_step(name, cmd, log_file):
    write_log_line(log_file, f"[STEP] {name}")
    subprocess.run(cmd, stdout=log_file, stderr=log_file, check=True)


def run_colmap(image_dir, sparse_dir, dense_dir, database_path, options, log_path):
    image_dir = Path(image_dir).resolve()
    sparse_dir = Path(sparse_dir).resolve()
    dense_dir = Path(dense_dir).resolve()
    database_path = Path(database_path).resolve()
    log_path = Path(log_path).resolve()

    if not image_dir.exists() or not has_input_images(image_dir):
        raise RuntimeError(f"No input images found in: {image_dir}")

    colmap = resolve_executable(options.get("executable", "colmap"))
    gpu_flag = "1" if bool(options.get("use_gpu", True)) else "0"
    gpu_index = str(options.get("gpu_index", 0)) if bool(options.get("use_gpu", True)) else "-1"
    camera_model = options.get("camera_model", "SIMPLE_RADIAL")

    sparse_model = sparse_dir / "0"
    fused_ply = dense_dir / "0" / "fused.ply"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    clean_path(database_path)
    clean_path(sparse_dir)
    clean_path(dense_dir)
    sparse_dir.mkdir(parents=True, exist_ok=True)
    dense_dir.mkdir(parents=True, exist_ok=True)
    fused_ply.parent.mkdir(parents=True, exist_ok=True)

    matcher_cmd = "sequential_matcher"

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
                "1",
                "--SiftExtraction.use_gpu",
                gpu_flag,
                "--SiftExtraction.max_num_features",
                "12000",
            ],
        ),
        (
            "Matching",
            [
                colmap,
                matcher_cmd,
                "--database_path",
                str(database_path),
                "--SiftMatching.use_gpu",
                gpu_flag,
                "--SiftMatching.guided_matching",
                "1",
                "--SiftMatching.max_num_matches",
                "32768",
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
                "--Mapper.num_threads",
                "8",
                "--Mapper.init_min_tri_angle",
                "2",
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
                "1200",
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
                "--PatchMatchStereo.num_iterations",
                "3",
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

    start_time = time.time()

    with log_path.open("a", encoding="utf-8") as log_file:
        write_log_line(log_file, "")
        write_log_line(log_file, f"=== COLMAP pipeline started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        write_log_line(log_file, f"[INFO] Images: {image_dir}")
        write_log_line(log_file, f"[INFO] Sparse: {sparse_dir}")
        write_log_line(log_file, f"[INFO] Dense: {dense_dir}")
        try:
            for name, cmd in steps:
                run_step(name, cmd, log_file)
                if name == "Sparse Reconstruction" and not sparse_model.exists():
                    raise RuntimeError(f"Sparse reconstruction failed. Missing model folder: {sparse_model}")

            runtime = time.time() - start_time

            if not fused_ply.exists():
                write_log_line(log_file, "[ERROR] fused.ply missing")
                raise RuntimeError(f"Point cloud not found: {fused_ply}")

            write_log_line(log_file, f"[DONE] Point cloud saved at: {fused_ply}")
            write_log_line(log_file, f"[DONE] Total runtime: {runtime:.2f} seconds")
        except Exception as error:
            write_log_line(log_file, f"[ERROR] {error}")
            raise

    print(f"Point cloud saved at: {fused_ply}")
    print(f"Total runtime: {runtime:.2f} seconds")
    return fused_ply


def main():
    parser = argparse.ArgumentParser(description="Run the COLMAP reconstruction pipeline.")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.json")
    parser.add_argument("--image-dir", help="Override image directory. Defaults to data/images_verified.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    paths = settings["paths"]
    options = settings["colmap"]

    image_dir = project_path(args.image_dir).resolve() if args.image_dir else (PROJECT_ROOT / "data" / "images_verified").resolve()
    sparse_dir = project_path(paths["sparse_dir"]).resolve()
    dense_dir = project_path(paths["dense_dir"]).resolve()
    database_path = project_path(paths["database_path"]).resolve()
    log_path = PROJECT_ROOT / "logs" / "colmap.log"

    if not image_dir.exists() or not has_input_images(image_dir):
        print(f"Error: no input images found in {image_dir}")
        raise SystemExit(1)

    run_colmap(
        image_dir=image_dir,
        sparse_dir=sparse_dir,
        dense_dir=dense_dir,
        database_path=database_path,
        options=options,
        log_path=log_path,
    )


if __name__ == "__main__":
    main()
