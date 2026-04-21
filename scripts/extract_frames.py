import cv2
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


MAX_FRAMES = 2000


def _probe_duration_ffprobe(video_path):
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        return None

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    value = result.stdout.strip()
    if not value:
        return None
    return float(value)


def _probe_duration_opencv(video_path):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if frame_count <= 0 or fps <= 0:
        return None

    return frame_count / fps


def _get_video_duration(video_path):
    duration = _probe_duration_ffprobe(video_path)
    if duration is not None and duration > 0:
        return duration

    duration = _probe_duration_opencv(video_path)
    if duration is not None and duration > 0:
        return duration

    raise RuntimeError(f"Could not determine video duration: {video_path}")


def _compute_fps(duration_seconds):
    if duration_seconds < 20:
        base_fps = 6.0
    elif duration_seconds <= 60:
        base_fps = 5.0
    else:
        base_fps = max(4.0, min(5.0, MAX_FRAMES / duration_seconds))

    return base_fps


def _downsample_frames(image_dir, max_frames):
    frames = sorted(image_dir.glob("*.jpg"))
    frame_count = len(frames)
    if frame_count <= max_frames:
        return frame_count

    selected_indices = {
        round(index * (frame_count - 1) / (max_frames - 1))
        for index in range(max_frames)
    }
    selected_frames = [frames[index] for index in sorted(selected_indices)]

    temp_dir = image_dir / "_selected_frames"
    temp_dir.mkdir(exist_ok=True)

    for index, source in enumerate(selected_frames, start=1):
        target = temp_dir / f"frame_{index:04d}.jpg"
        shutil.move(str(source), str(target))

    for frame in image_dir.glob("*.jpg"):
        frame.unlink()

    for frame in sorted(temp_dir.glob("*.jpg")):
        shutil.move(str(frame), str(image_dir / frame.name))

    temp_dir.rmdir()
    return len(list(image_dir.glob("*.jpg")))


def extract_frames(video_path, image_dir, fps=None):
    """Extract frames from a video with ffmpeg using a duration-based FPS strategy."""
    video_path = Path(video_path).resolve()
    image_dir = Path(image_dir).resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg was not found. Install ffmpeg and add it to PATH.")

    duration_seconds = _get_video_duration(video_path)
    computed_fps = _compute_fps(duration_seconds)

    image_dir.mkdir(parents=True, exist_ok=True)
    for image_file in image_dir.glob("*.jpg"):
        image_file.unlink()

    print(f"\n[1/3] Extracting frames from: {video_path}")
    output_pattern = image_dir / "frame_%04d.jpg"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps={computed_fps:.4f}",
        "-q:v",
        "2",
        str(output_pattern),
    ]
    subprocess.run(command, check=True)

    frame_count = len(list(image_dir.glob("*.jpg")))
    if frame_count == 0:
        raise RuntimeError("No frames were extracted. Check the video file and computed FPS.")

    if frame_count > MAX_FRAMES:
        frame_count = _downsample_frames(image_dir, MAX_FRAMES)

    print(f"      Video duration: {duration_seconds:.2f} seconds")
    print(f"      FPS used: {computed_fps:.2f}")
    print(f"      Frames extracted: {frame_count}")
    return image_dir


def main():
    parser = argparse.ArgumentParser(description="Extract frames from a video for COLMAP.")
    parser.add_argument("--video", required=True, help="Path to the input video.")
    parser.add_argument("--output-dir", required=True, help="Directory for extracted frames.")
    args = parser.parse_args()

    extract_frames(Path(args.video), Path(args.output_dir))


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        main()
    else:
        main()
