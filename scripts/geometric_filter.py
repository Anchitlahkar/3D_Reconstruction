import shutil
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "images_selected"
OUTPUT_DIR = PROJECT_ROOT / "data" / "images_verified"
RESIZE_WIDTH = 320
RESIZE_HEIGHT = 240
MIN_MATCH_COUNT = 8


def sorted_image_paths(image_dir):
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    paths = []
    for pattern in patterns:
        paths.extend(image_dir.glob(pattern))
    return sorted(set(paths))


def prepare_output_dir(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.iterdir():
        if existing.is_file():
            existing.unlink()


def load_gray_small(image_path):
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")
    return cv2.resize(image, (RESIZE_WIDTH, RESIZE_HEIGHT), interpolation=cv2.INTER_AREA)


def compute_features(image_path, orb):
    gray = load_gray_small(image_path)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    return keypoints or [], descriptors


def compute_inlier_ratio(previous_keypoints, previous_descriptors, current_keypoints, current_descriptors, matcher):
    if previous_descriptors is None or current_descriptors is None:
        return 0.0
    if len(previous_keypoints) < MIN_MATCH_COUNT or len(current_keypoints) < MIN_MATCH_COUNT:
        return 0.0

    matches = matcher.knnMatch(previous_descriptors, current_descriptors, k=2)
    good_matches = []
    for pair in matches:
        if len(pair) < 2:
            continue
        best, second = pair
        if best.distance < 0.75 * second.distance:
            good_matches.append(best)

    if len(good_matches) < MIN_MATCH_COUNT:
        return 0.0

    points_prev = np.float32([previous_keypoints[m.queryIdx].pt for m in good_matches])
    points_curr = np.float32([current_keypoints[m.trainIdx].pt for m in good_matches])

    essential_matrix, mask = cv2.findEssentialMat(
        points_prev,
        points_curr,
        focal=1.0,
        pp=(RESIZE_WIDTH / 2.0, RESIZE_HEIGHT / 2.0),
        method=cv2.RANSAC,
        prob=0.999,
        threshold=1.0,
    )

    if essential_matrix is None or mask is None:
        return 0.0

    inlier_count = int(mask.ravel().sum())
    return inlier_count / max(1, len(good_matches))


def copy_frame(source, target_dir, output_index):
    target = target_dir / f"frame_{output_index:04d}{source.suffix.lower()}"
    shutil.copy2(source, target)


def main():
    image_paths = sorted_image_paths(INPUT_DIR)
    if not image_paths:
        raise RuntimeError(f"No images found in: {INPUT_DIR}")

    prepare_output_dir(OUTPUT_DIR)

    orb = cv2.ORB_create(2000)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    verified_paths = [image_paths[0]]
    inlier_ratios = []
    copy_frame(image_paths[0], OUTPUT_DIR, 1)

    previous_keypoints, previous_descriptors = compute_features(image_paths[0], orb)
    output_index = 2

    for image_path in image_paths[1:]:
        current_keypoints, current_descriptors = compute_features(image_path, orb)
        inlier_ratio = compute_inlier_ratio(
            previous_keypoints,
            previous_descriptors,
            current_keypoints,
            current_descriptors,
            matcher,
        )
        inlier_ratios.append(inlier_ratio)

        keep_frame = inlier_ratio >= 0.2
        if keep_frame:
            verified_paths.append(image_path)
            copy_frame(image_path, OUTPUT_DIR, output_index)
            output_index += 1
            previous_keypoints = current_keypoints
            previous_descriptors = current_descriptors

    if verified_paths[-1] != image_paths[-1]:
        verified_paths.append(image_paths[-1])
        copy_frame(image_paths[-1], OUTPUT_DIR, output_index)

    total_frames = len(image_paths)
    verified_frames = len(verified_paths)
    average_inlier_ratio = sum(inlier_ratios) / len(inlier_ratios) if inlier_ratios else 0.0
    reduction_percent = 100.0 * (1.0 - (verified_frames / total_frames))

    print(f"Total selected frames: {total_frames}")
    print(f"Verified frames: {verified_frames}")
    print(f"Average inlier ratio: {average_inlier_ratio:.3f}")
    print(f"Reduction: {reduction_percent:.1f}%")
    print(f"Saved verified frames to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
