import argparse
from pathlib import Path
import shutil
import subprocess
import sys


FPS = 4
MAX_WIDTH = 1200


def extract_frames(video_path, image_dir):
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
    args = parser.parse_args()

    extract_frames(args.video, args.output_dir)


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required.")
    main()
