import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from scripts.extract_frames import extract_frames
from scripts.run_colmap import run_colmap


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


def main():
    parser = argparse.ArgumentParser(description="Automated video-to-3D photogrammetry pipeline.")
    parser.add_argument("--video", help="Path to the input video. If omitted, the first video in data/input_video is used.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    parser.add_argument("--no-viewer", action="store_true", help="Run reconstruction without opening the C++ viewer")
    parser.add_argument("--skip-viewer-build", action="store_true", help="Open the existing viewer.exe without recompiling")
    args = parser.parse_args()

    settings = load_settings(args.config)
    paths = settings["paths"]

    input_video_dir = project_path(paths["input_video_dir"]).resolve()
    image_dir = project_path(paths["image_dir"]).resolve()
    sparse_dir = project_path(paths["sparse_dir"]).resolve()
    dense_dir = project_path(paths["dense_dir"]).resolve()
    database_path = project_path(paths["database_path"]).resolve()

    print("[0/3] Starting photogrammetry pipeline")
    print(f"Project root: {PROJECT_ROOT}")

    video_path = prepare_video(args.video, input_video_dir)
    extract_frames(video_path, image_dir, settings["fps"])

    log_path = PROJECT_ROOT / "logs" / "colmap.log"

    fused_ply = run_colmap(
        image_dir=image_dir,
        sparse_dir=sparse_dir,
        dense_dir=dense_dir,
        database_path=database_path,
        options=settings["colmap"],
        log_path=log_path,
    )

    print("\n[3/3] Pipeline finished")
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
