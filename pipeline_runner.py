import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from scripts.extract_frames import extract_frames
from scripts.monitor import PipelineMonitor
from scripts.run_colmap import run_colmap


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


def build_monitor_output_dir():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "logs" / "monitor_runs" / run_id


def count_dense_images(dense_dir):
    image_dir = Path(dense_dir).resolve() / "images"
    if not image_dir.exists():
        return 0
    return sum(1 for path in image_dir.iterdir() if path.is_file())


def run_pipeline(video_argument=None, config_path=DEFAULT_CONFIG, resume=False, dry_run=False):
    settings = load_settings(config_path)
    paths = settings["paths"]
    colmap_options = settings["colmap"]

    input_video_dir = project_path(paths["input_video_dir"]).resolve()
    image_dir = project_path(paths["image_dir"]).resolve()
    sparse_dir = project_path(paths["sparse_dir"]).resolve()
    dense_dir = project_path(paths["dense_dir"]).resolve()
    database_path = project_path(paths["database_path"]).resolve()
    output_ply = project_path(paths["output_ply"]).resolve()
    log_path = PROJECT_ROOT / "logs" / "colmap.log"
    video_path = prepare_video(video_argument, input_video_dir)

    monitor = PipelineMonitor(
        output_dir=build_monitor_output_dir(),
        sample_interval=1.0,
        gpu_index=int(colmap_options.get("gpu_index", 0)),
    )
    extraction_fps = settings.get("fps", 5)
    extraction_max_frames = None

    try:
        monitor.start()
        
        if dry_run:
            from scripts.resource_guard import prepare_dry_run_dataset
            print("--- Starting Dry Run (max 40 extracted frames) ---")
            extraction_fps = 1
            extraction_max_frames = 40
            print(f"[DRY RUN] Extracting limited frames: fps={extraction_fps}, max_frames={extraction_max_frames}")
            dry_run_image_dir = PROJECT_ROOT / "tmp_dry_run" / "images"
            dry_run_sparse = PROJECT_ROOT / "tmp_dry_run" / "sparse"
            dry_run_dense = PROJECT_ROOT / "tmp_dry_run" / "dense"
            dry_run_db = PROJECT_ROOT / "tmp_dry_run" / "database.db"
            dry_run_ply = PROJECT_ROOT / "tmp_dry_run" / "fused.ply"

        if not resume:
            monitor.stage_event(
                {
                    "event": "stage_start",
                    "stage": "extract_frames",
                    "command": [sys.executable, "scripts/extract_frames.py", "--video", str(video_path)],
                }
            )
            extraction_result = extract_frames(
                video_path=video_path,
                image_dir=image_dir,
                fps=extraction_fps,
                max_width=colmap_options.get("max_image_size", 2304),
                frame_selection=settings.get("frame_selection", {}),
                max_frames=extraction_max_frames,
            )
            extraction_stats = extraction_result.get("stats", {})
            monitor.record_frame_stats(
                extracted=extraction_stats.get("total_raw_frames", 0),
                selected=extraction_stats.get("kept_frames", 0),
            )
            monitor.stage_event(
                {
                    "event": "stage_end",
                    "stage": "extract_frames",
                    "command": [sys.executable, "scripts/extract_frames.py", "--video", str(video_path)],
                    "success": True,
                }
            )

        if dry_run:
            prepare_dry_run_dataset(image_dir, dry_run_image_dir, num_images=20)
            run_colmap(
                image_dir=dry_run_image_dir,
                sparse_dir=dry_run_sparse,
                dense_dir=dry_run_dense,
                database_path=dry_run_db,
                output_ply=dry_run_ply,
                options=colmap_options,
                log_path=PROJECT_ROOT / "logs" / "dry_run.log",
                stage_callback=None,
                resume=False,
                is_dry_run=True
            )
            print("--- Dry Run Completed Successfully ---")

        run_colmap(
            image_dir=image_dir,
            sparse_dir=sparse_dir,
            dense_dir=dense_dir,
            database_path=database_path,
            output_ply=output_ply,
            options=colmap_options,
            log_path=log_path,
            stage_callback=monitor.stage_event,
            resume=resume,
            is_dry_run=False
        )
        dense_frames = count_dense_images(dense_dir)
        monitor.record_frame_stats(
            sparse=dense_frames or extraction_stats.get("kept_frames", 0) if not resume else dense_frames,
            dense=dense_frames or extraction_stats.get("kept_frames", 0) if not resume else dense_frames,
        )
        monitor.stop(success=True)
        print(f"Monitoring logs written to: {monitor.output_dir}")
    except Exception as error:
        monitor.stop(success=False, error_message=str(error))
        print(f"Monitoring logs written to: {monitor.output_dir}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Run the monitored COLMAP reconstruction pipeline.")
    parser.add_argument("--video", help="Path to the input video. If omitted, the first video in data/input_video is used.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    parser.add_argument("--resume", action="store_true", help="Resume from dense reconstruction")
    parser.add_argument("--dry-run", action="store_true", help="Perform a quick dry run before the full pipeline")
    args = parser.parse_args()
    run_pipeline(video_argument=args.video, config_path=Path(args.config).resolve(), resume=args.resume, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
