import shutil
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "images"
OUTPUT_DIR = PROJECT_ROOT / "data" / "images_selected"
MAX_SELECTED_FRAMES = 300
MIN_SELECTED_FRAMES = 150
RESIZE_WIDTH = 320
RESIZE_HEIGHT = 240
MIN_SPACING = 2
FORCE_KEEP_INTERVAL = 10


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


def compute_features(image_paths):
    orb = cv2.ORB_create(2000)
    features = []
    for image_path in image_paths:
        gray = load_gray_small(image_path)
        keypoints, descriptors = orb.detectAndCompute(gray, None)
        features.append(
            {
                "path": image_path,
                "keypoints": keypoints or [],
                "descriptors": descriptors,
            }
        )
    return features


def good_match_ratio(previous_features, current_features, matcher):
    previous_descriptors = previous_features["descriptors"]
    current_descriptors = current_features["descriptors"]
    previous_keypoints = previous_features["keypoints"]

    if previous_descriptors is None or current_descriptors is None or not previous_keypoints:
        return 0.0

    matches = matcher.knnMatch(previous_descriptors, current_descriptors, k=2)
    good_matches = 0
    for pair in matches:
        if len(pair) < 2:
            continue
        best, second = pair
        if best.distance < 0.75 * second.distance:
            good_matches += 1

    return good_matches / max(1, len(previous_keypoints))


def select_frames(features, similarity_threshold=0.85, overlap_threshold=0.5, difference_threshold=0.3):
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    selected_indices = [0]
    ratios = []
    last_selected_index = 0

    for index in range(1, len(features)):
        force_keep = index % FORCE_KEEP_INTERVAL == 0
        spacing_ok = (index - last_selected_index) >= MIN_SPACING

        ratio = good_match_ratio(features[last_selected_index], features[index], matcher)
        ratios.append(ratio)

        keep = False
        if force_keep:
            keep = True
        elif ratio > similarity_threshold:
            keep = False
        elif overlap_threshold <= ratio <= similarity_threshold and spacing_ok:
            keep = True
        elif ratio < difference_threshold:
            keep = True

        if keep:
            selected_indices.append(index)
            last_selected_index = index

    if selected_indices[-1] != len(features) - 1:
        selected_indices.append(len(features) - 1)

    return selected_indices, ratios


def tune_thresholds(features):
    similarity_threshold = 0.85
    overlap_threshold = 0.5
    difference_threshold = 0.3

    selected_indices, ratios = select_frames(
        features,
        similarity_threshold=similarity_threshold,
        overlap_threshold=overlap_threshold,
        difference_threshold=difference_threshold,
    )

    if len(selected_indices) > MAX_SELECTED_FRAMES:
        similarity_threshold = 0.80
        overlap_threshold = 0.55
        selected_indices, ratios = select_frames(
            features,
            similarity_threshold=similarity_threshold,
            overlap_threshold=overlap_threshold,
            difference_threshold=difference_threshold,
        )
    elif len(selected_indices) < MIN_SELECTED_FRAMES:
        similarity_threshold = 0.90
        overlap_threshold = 0.45
        selected_indices, ratios = select_frames(
            features,
            similarity_threshold=similarity_threshold,
            overlap_threshold=overlap_threshold,
            difference_threshold=difference_threshold,
        )

    return selected_indices, ratios


def copy_selected_frames(image_paths, selected_indices, output_dir):
    for output_index, feature_index in enumerate(selected_indices, start=1):
        source = image_paths[feature_index]
        target = output_dir / f"frame_{output_index:04d}{source.suffix.lower()}"
        shutil.copy2(source, target)


def main():
    image_paths = sorted_image_paths(INPUT_DIR)
    if not image_paths:
        raise RuntimeError(f"No images found in: {INPUT_DIR}")

    prepare_output_dir(OUTPUT_DIR)
    features = compute_features(image_paths)
    selected_indices, ratios = tune_thresholds(features)
    copy_selected_frames(image_paths, selected_indices, OUTPUT_DIR)

    total_frames = len(image_paths)
    selected_frames = len(selected_indices)
    average_match_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    reduction_percent = 100.0 * (1.0 - (selected_frames / total_frames))

    print(f"Total frames: {total_frames}")
    print(f"Selected frames: {selected_frames}")
    print(f"Average match ratio: {average_match_ratio:.3f}")
    print(f"Reduction: {reduction_percent:.1f}%")
    print(f"Saved selected frames to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
