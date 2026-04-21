import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.json"


def load_settings(config_path):
    with Path(config_path).resolve().open("r", encoding="utf-8") as file:
        return json.load(file)


def project_path(relative_or_absolute_path):
    path = Path(relative_or_absolute_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def find_default_video(input_video_dir):
    video_extensions = (".mp4", ".mov", ".avi", ".mkv", ".m4v")
    if not input_video_dir.exists():
        return None

    for path in sorted(input_video_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in video_extensions:
            return path

    return None


def prepare_video(video_argument, input_video_dir):
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

    if video_path.resolve() != stored_video.resolve():
        shutil.copy2(video_path, stored_video)
        return stored_video

    return video_path


def run_python_script(script_path, extra_args=None):
    command = [sys.executable, str(script_path)]
    if extra_args:
        command.extend(extra_args)
    subprocess.run(command, check=True)


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


if __name__ == "__main__":
    main()
