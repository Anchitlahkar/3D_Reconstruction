import cv2
from pathlib import Path
import shutil
import subprocess


def extract_frames(video_path, image_dir, fps):
    """Extract frames from a video with ffmpeg (primary) or OpenCV (fallback)."""
    video_path = Path(video_path).resolve()
    image_dir = Path(image_dir).resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    image_dir.mkdir(parents=True, exist_ok=True)

    # Remove old extracted frames so COLMAP receives only frames from this run.
    for image_file in image_dir.glob("*.jpg"):
        image_file.unlink()

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"\n[1/3] Extracting frames (ffmpeg) from: {video_path}")
        output_pattern = image_dir / "frame_%06d.jpg"
        command = [
            ffmpeg_path,
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
    else:
        print(f"\n[1/3] Extracting frames (OpenCV fallback) from: {video_path}")
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        if video_fps <= 0:
            video_fps = 30 # Default if unknown

        hop = round(video_fps / fps)
        if hop < 1:
            hop = 1

        count = 0
        saved_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if count % hop == 0:
                output_path = image_dir / f"frame_{saved_count:06d}.jpg"
                cv2.imwrite(str(output_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved_count += 1
            count += 1
        cap.release()

    frame_count = len(list(image_dir.glob("*.jpg")))
    if frame_count == 0:
        raise RuntimeError("No frames were extracted. Check the video file and FPS value.")

    print(f"      Extracted {frame_count} frames.")
    return image_dir
