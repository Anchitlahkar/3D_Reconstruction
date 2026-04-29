import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


FPS = 5
MAX_WIDTH = 2304
DEFAULT_FRAME_SELECTION = {
    "enabled": True,
    "analysis_width": 640,
    "min_sharpness": 80.0,
    "min_histogram_diff": 0.12,
    "min_flow_magnitude": 1.5,
    "min_feature_change_ratio": 0.08,
    "max_frame_gap": 3,
    "target_min_frames": 150,
    "target_max_frames": 220,
}


def run_ffmpeg_extract(video_path, output_dir, fps, max_width, max_frames=None):
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg was not found. Install ffmpeg and add it to PATH.")

    output_dir.mkdir(parents=True, exist_ok=True)
    for image_file in output_dir.glob("*.jpg"):
        image_file.unlink()

    output_pattern = output_dir / "frame_%04d.jpg"
    scale_filter = f"fps={fps},scale='min({max_width},iw)':-1"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        scale_filter,
    ]
    if max_frames is not None:
        command.extend([
            "-frames:v",
            str(int(max_frames)),
        ])
    command.extend([
        "-q:v",
        "2",
        str(output_pattern),
    ])
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return command


def load_analysis_views(image_path, analysis_width):
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Failed to read extracted frame: {image_path}")

    height, width = image.shape[:2]
    if width > analysis_width:
        scale = analysis_width / float(width)
        resized = cv2.resize(image, (analysis_width, max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)
    else:
        resized = image

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return image, gray


def sharpness_score(gray_image):
    return float(cv2.Laplacian(gray_image, cv2.CV_64F).var())


def normalized_histogram(gray_image):
    histogram = cv2.calcHist([gray_image], [0], None, [64], [0, 256])
    cv2.normalize(histogram, histogram)
    return histogram


def histogram_difference(hist_a, hist_b):
    correlation = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
    return max(0.0, min(2.0, 1.0 - float(correlation)))


def mean_flow_magnitude(previous_gray, current_gray):
    flow = cv2.calcOpticalFlowFarneback(
        previous_gray,
        current_gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=21,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    return float(np.mean(magnitude))


def feature_change_ratio(previous_gray, current_gray):
    previous_features = cv2.goodFeaturesToTrack(previous_gray, maxCorners=600, qualityLevel=0.01, minDistance=7)
    current_features = cv2.goodFeaturesToTrack(current_gray, maxCorners=600, qualityLevel=0.01, minDistance=7)

    previous_count = 0 if previous_features is None else len(previous_features)
    current_count = 0 if current_features is None else len(current_features)
    baseline = max(previous_count, current_count, 1)
    return abs(current_count - previous_count) / baseline


def select_frames(raw_dir, output_dir, frame_selection):
    output_dir.mkdir(parents=True, exist_ok=True)
    for image_file in output_dir.glob("*.jpg"):
        image_file.unlink()

    raw_frames = sorted(raw_dir.glob("*.jpg"))
    if not raw_frames:
        raise RuntimeError("No frames were extracted. Check the video file and ffmpeg installation.")

    selected_frames = []
    stats = {
        "total_raw_frames": len(raw_frames),
        "kept_frames": 0,
        "rejected_blur": 0,
        "rejected_duplicate": 0,
        "forced_keeps": 0,
    }

    analysis_width = int(frame_selection["analysis_width"])
    min_sharpness = float(frame_selection["min_sharpness"])
    min_histogram_diff = float(frame_selection["min_histogram_diff"])
    min_flow_magnitude = float(frame_selection["min_flow_magnitude"])
    min_feature_change_ratio = float(frame_selection["min_feature_change_ratio"])
    max_frame_gap = max(1, int(frame_selection["max_frame_gap"]))

    last_kept_gray = None
    last_kept_hist = None
    last_kept_index = None

    for index, raw_frame in enumerate(raw_frames):
        _, gray = load_analysis_views(raw_frame, analysis_width)
        sharpness = sharpness_score(gray)
        if sharpness < min_sharpness:
            stats["rejected_blur"] += 1
            continue

        keep = False
        forced_keep = False
        if last_kept_gray is None:
            keep = True
        else:
            hist = normalized_histogram(gray)
            hist_diff = histogram_difference(last_kept_hist, hist)
            flow_mag = mean_flow_magnitude(last_kept_gray, gray)
            feature_delta = feature_change_ratio(last_kept_gray, gray)

            if hist_diff >= min_histogram_diff:
                keep = True
            if flow_mag >= min_flow_magnitude:
                keep = True
            if feature_delta >= min_feature_change_ratio:
                keep = True
            if last_kept_index is not None and (index - last_kept_index) >= max_frame_gap:
                keep = True
                forced_keep = True

            if not keep:
                stats["rejected_duplicate"] += 1

        if keep:
            target_path = output_dir / f"frame_{len(selected_frames) + 1:04d}.jpg"
            shutil.copy2(raw_frame, target_path)
            selected_frames.append(target_path)
            last_kept_gray = gray
            last_kept_hist = normalized_histogram(gray)
            last_kept_index = index
            if forced_keep:
                stats["forced_keeps"] += 1

    stats["kept_frames"] = len(selected_frames)
    return selected_frames, stats


def enforce_selected_frame_cap(selected_frames, max_frames):
    if max_frames is None or len(selected_frames) <= max_frames:
        return selected_frames

    capped_frames = selected_frames[:max_frames]
    for extra_frame in selected_frames[max_frames:]:
        if extra_frame.exists():
            extra_frame.unlink()
    return capped_frames


def extract_frames(video_path, image_dir, fps=FPS, max_width=MAX_WIDTH, frame_selection=None, max_frames=None):
    video_path = Path(video_path).resolve()
    image_dir = Path(image_dir).resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    raw_dir = image_dir.parent / f"{image_dir.name}_raw"
    if raw_dir.exists():
        shutil.rmtree(raw_dir)

    ffmpeg_command = run_ffmpeg_extract(video_path, raw_dir, fps, max_width, max_frames=max_frames)

    frame_selection = {**DEFAULT_FRAME_SELECTION, **(frame_selection or {})}
    if frame_selection.get("enabled", True):
        selected_frames, stats = select_frames(raw_dir, image_dir, frame_selection)
    else:
        image_dir.mkdir(parents=True, exist_ok=True)
        for image_file in image_dir.glob("*.jpg"):
            image_file.unlink()
        raw_frames = sorted(raw_dir.glob("*.jpg"))
        for index, raw_frame in enumerate(raw_frames, start=1):
            shutil.copy2(raw_frame, image_dir / f"frame_{index:04d}.jpg")
        selected_frames = sorted(image_dir.glob("*.jpg"))
        stats = {
            "total_raw_frames": len(selected_frames),
            "kept_frames": len(selected_frames),
            "rejected_blur": 0,
            "rejected_duplicate": 0,
            "forced_keeps": 0,
        }

    selected_frames = enforce_selected_frame_cap(selected_frames, max_frames)
    stats["kept_frames"] = len(selected_frames)
    shutil.rmtree(raw_dir)

    if not selected_frames:
        raise RuntimeError("Adaptive frame selection removed all frames. Relax thresholds in config.json.")

    print(f"Raw frames extracted: {stats['total_raw_frames']}")
    print(f"Frames kept: {stats['kept_frames']}")
    print(f"Rejected for blur: {stats['rejected_blur']}")
    print(f"Rejected as near-duplicate/low-motion: {stats['rejected_duplicate']}")
    print(f"Forced keeps for continuity: {stats['forced_keeps']}")

    target_min = int(frame_selection["target_min_frames"])
    target_max = int(frame_selection["target_max_frames"])
    if max_frames is None and (stats["kept_frames"] < target_min or stats["kept_frames"] > target_max):
        print(
            "Warning: kept frame count is outside the target range "
            f"({target_min}-{target_max}). Adjust frame_selection thresholds if needed."
        )

    return {
        "image_dir": image_dir,
        "stats": stats,
        "ffmpeg_command": ffmpeg_command,
    }


def main():
    parser = argparse.ArgumentParser(description="Extract and adaptively filter frames for COLMAP reconstruction.")
    parser.add_argument("--video", required=True, help="Path to the input video.")
    parser.add_argument("--output-dir", required=True, help="Directory for extracted frames.")
    parser.add_argument("--config", help="Path to config.json to load extraction settings.")
    args = parser.parse_args()

    fps = FPS
    max_width = MAX_WIDTH
    frame_selection = DEFAULT_FRAME_SELECTION.copy()

    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as file:
                config = json.load(file)
            fps = config.get("fps", FPS)
            max_width = config.get("colmap", {}).get("max_image_size", MAX_WIDTH)
            frame_selection = {
                **frame_selection,
                **config.get("frame_selection", {}),
            }

    extract_frames(args.video, args.output_dir, fps=fps, max_width=max_width, frame_selection=frame_selection)


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required.")
    main()
