import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.json"


def load_settings(config_path):
    """Read pipeline settings from JSON."""
    with Path(config_path).resolve().open("r", encoding="utf-8") as file:
        return json.load(file)


def project_path(relative_or_absolute_path):
    """Resolve config paths relative to the project root unless already absolute."""
    path = Path(relative_or_absolute_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def find_default_video(input_video_dir):
    """Use the first common video file from data/input_video when --video is omitted."""
    video_extensions = (".mp4", ".mov", ".avi", ".mkv", ".m4v")
    if not input_video_dir.exists():
        return None

    for path in sorted(input_video_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in video_extensions:
            return path

    return None


def prepare_video(video_argument, input_video_dir):
    """Accept an absolute/relative video path or a filename inside data/input_video."""
    if video_argument is None:
        video_path = find_default_video(input_video_dir)
        if video_path is None:
            raise FileNotFoundError(
                f"No video provided and no video found in: {input_video_dir}. "
                "Pass --video path\\to\\input.mp4 or place one in data/input_video."
            )
        return video_path.resolve()

    video_path = Path(video_argument)

    if not video_path.is_absolute():
        local_path = (PROJECT_ROOT / video_path).resolve()
        input_video_path = (input_video_dir / video_path.name).resolve()

        if local_path.exists():
            video_path = local_path
        elif input_video_path.exists():
            video_path = input_video_path
        else:
            video_path = local_path
    else:
        video_path = video_path.resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    input_video_dir.mkdir(parents=True, exist_ok=True)
    stored_video = input_video_dir / video_path.name

    # Keep a copy under data/input_video so project inputs are collected in one place.
    if video_path.resolve() != stored_video.resolve():
        shutil.copy2(video_path, stored_video)
        print(f"Copied input video to: {stored_video}")
        return stored_video

    return video_path


def build_viewer():
    """Compile the C++ Raylib viewer and copy raylib.dll beside the executable."""
    viewer_dir = PROJECT_ROOT / "viewer"
    source = viewer_dir / "main.cpp"
    executable = viewer_dir / "viewer.exe"
    raylib_root = PROJECT_ROOT / "raylib" / "raylib-5.5_win64_mingw-w64"
    include_dir = raylib_root / "include"
    lib_dir = raylib_root / "lib"
    dll_source = lib_dir / "raylib.dll"
    dll_target = viewer_dir / "raylib.dll"

    if not source.exists():
        raise FileNotFoundError(f"Viewer source not found: {source}")

    command = [
        "g++",
        str(source),
        "-o",
        str(executable),
        "-std=c++17",
        f"-I{include_dir}",
        f"-L{lib_dir}",
        "-lraylib",
        "-lopengl32",
        "-lgdi32",
        "-lwinmm",
    ]

    print("\n[viewer] Compiling Raylib point cloud viewer")
    print(" ".join(command))
    subprocess.run(command, check=True)

    if dll_source.exists():
        shutil.copy2(dll_source, dll_target)

    return executable


def launch_viewer(executable, ply_path):
    """Open the generated point cloud in the C++ viewer."""
    print("\n[viewer] Launching point cloud viewer")
    print(f"{executable} {ply_path}")
    subprocess.Popen([str(executable), str(ply_path)], cwd=executable.parent)


def count_images(image_dir):
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    count = 0
    for pattern in patterns:
        count += len(list(Path(image_dir).glob(pattern)))
    return count


def run_python_script(script_path, extra_args=None):
    command = [sys.executable, str(script_path)]
    if extra_args:
        command.extend(extra_args)
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description="Automated video-to-3D photogrammetry pipeline.")
    parser.add_argument("--video", help="Path to the input video. If omitted, the first video in data/input_video is used.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    parser.add_argument("--no-filter", action="store_true", help="Skip adaptive frame selection and use data/images directly")
    parser.add_argument("--no-viewer", action="store_true", help="Run reconstruction without opening the C++ viewer")
    parser.add_argument("--skip-viewer-build", action="store_true", help="Open the existing viewer.exe without recompiling")
    args = parser.parse_args()

    settings = load_settings(args.config)
    paths = settings["paths"]

    input_video_dir = project_path(paths["input_video_dir"]).resolve()
    image_dir = project_path(paths["image_dir"]).resolve()
    selected_image_dir = (PROJECT_ROOT / "data" / "images_selected").resolve()
    verified_image_dir = (PROJECT_ROOT / "data" / "images_verified").resolve()
    sparse_dir = project_path(paths["sparse_dir"]).resolve()
    dense_dir = project_path(paths["dense_dir"]).resolve()
    fused_ply = dense_dir / "0" / "fused.ply"

    print("[0/4] Starting photogrammetry pipeline")
    print(f"Project root: {PROJECT_ROOT}")

    video_path = prepare_video(args.video, input_video_dir)

    print("[1/4] Extracting frames...")
    run_python_script(
        PROJECT_ROOT / "scripts" / "extract_frames.py",
        ["--video", str(video_path), "--output-dir", str(image_dir)],
    )

    input_frame_count = count_images(image_dir)

    colmap_image_dir = image_dir
    if not args.no_filter:
        print("[2/4] Selecting frames...")
        run_python_script(PROJECT_ROOT / "scripts" / "auto_select_frames.py")
        selected_frame_count = count_images(selected_image_dir)
        reduction_percent = 100.0 * (1.0 - (selected_frame_count / max(1, input_frame_count)))
        print(f"      Total input frames: {input_frame_count}")
        print(f"      Selected frames: {selected_frame_count}")
        print(f"      Reduction: {reduction_percent:.1f}%")
        print("[3/4] Verifying geometry...")
        run_python_script(PROJECT_ROOT / "scripts" / "geometric_filter.py")
        verified_frame_count = count_images(verified_image_dir)
        verified_reduction_percent = 100.0 * (1.0 - (verified_frame_count / max(1, selected_frame_count)))
        print(f"      Total selected frames: {selected_frame_count}")
        print(f"      Verified frames: {verified_frame_count}")
        print(f"      Reduction: {verified_reduction_percent:.1f}%")
        colmap_image_dir = verified_image_dir
    else:
        print("[2/4] Skipping frame selection (--no-filter)")
        print(f"      Total input frames: {input_frame_count}")
        print("[3/4] Skipping geometry verification (--no-filter)")

    print("[4/4] Running COLMAP...")
    run_python_script(
        PROJECT_ROOT / "scripts" / "run_colmap.py",
        ["--config", str(Path(args.config).resolve()), "--image-dir", str(colmap_image_dir)],
    )

    print("\n[4/4] Pipeline finished")
    print(f"Point cloud saved at: {fused_ply}")
    if os.path.exists(fused_ply):
        print("Reconstruction successful")
    else:
        print("File not found")

    if not args.no_viewer:
        viewer_executable = PROJECT_ROOT / "viewer" / "viewer.exe"
        if not args.skip_viewer_build:
            viewer_executable = build_viewer()
        launch_viewer(viewer_executable, fused_ply)


if __name__ == "__main__":
    main()
