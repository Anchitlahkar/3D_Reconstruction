import argparse
from pathlib import Path
import shutil
import subprocess
import sys


FPS = 2
MAX_WIDTH = 2000


def extract_frames(video_path, image_dir, fps=FPS, max_width=MAX_WIDTH):
    """Extract all video viewpoints at a fixed FPS for room-scale reconstruction."""
    video_path = Path(video_path).resolve()
    image_dir = Path(image_dir).resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg was not found. Install ffmpeg and add it to PATH.")

    image_dir.mkdir(parents=True, exist_ok=True)
    for image_file in image_dir.glob("*.jpg"):
        image_file.unlink()

    output_pattern = image_dir / "frame_%04d.jpg"
    scale_filter = f"fps={fps},scale='min({max_width},iw)':-1"
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

    # ffmpeg applies rotation metadata automatically unless explicitly disabled.
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_count = len(list(image_dir.glob("*.jpg")))
    if frame_count == 0:
        raise RuntimeError("No frames were extracted. Check the video file and ffmpeg installation.")

    print(f"Total frames extracted: {frame_count}")
    return image_dir


def main():
    parser = argparse.ArgumentParser(description="Extract frames from a video for room-scale COLMAP reconstruction.")
    parser.add_argument("--video", required=True, help="Path to the input video.")
    parser.add_argument("--output-dir", required=True, help="Directory for extracted frames.")
    parser.add_argument("--config", help="Path to config.json to load FPS and MAX_WIDTH.")
    args = parser.parse_args()

    fps = FPS
    max_width = MAX_WIDTH

    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            import json
            with open(config_path, "r") as f:
                config = json.load(f)
                fps = config.get("fps", FPS)
                max_width = config.get("colmap", {}).get("max_image_size", MAX_WIDTH)

    extract_frames(args.video, args.output_dir, fps, max_width)


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required.")
    main()
