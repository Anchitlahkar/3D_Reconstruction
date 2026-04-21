from pathlib import Path
import shutil
import subprocess


def extract_frames(video_path, image_dir, fps):
    """Extract frames from a video with ffmpeg and save them as JPG images."""
    video_path = Path(video_path).resolve()
    image_dir = Path(image_dir).resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg was not found. Install ffmpeg and add it to PATH.")

    image_dir.mkdir(parents=True, exist_ok=True)

    # Remove old extracted frames so COLMAP receives only frames from this run.
    for image_file in image_dir.glob("*.jpg"):
        image_file.unlink()

    output_pattern = image_dir / "frame_%06d.jpg"

    print(f"\n[1/3] Extracting frames from: {video_path}")
    print(f"      FPS: {fps}")
    print(f"      Output folder: {image_dir}")

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "2",
        str(output_pattern),
    ]

    subprocess.run(command, check=True)

    frame_count = len(list(image_dir.glob("*.jpg")))
    if frame_count == 0:
        raise RuntimeError("No frames were extracted. Check the video file and FPS value.")

    print(f"      Extracted {frame_count} frames.")
    return image_dir
