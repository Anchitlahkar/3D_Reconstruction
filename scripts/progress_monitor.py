import argparse
import os
import sys
import time
from pathlib import Path

import psutil
from tqdm import tqdm


if sys.version_info < (3, 10):
    raise RuntimeError("Python 3.10+ is required.")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "colmap.log"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "dense" / "0" / "fused.ply"
STEP_ORDER = [
    "Feature Extraction",
    "Matching",
    "Sparse Reconstruction",
    "Undistort",
    "Dense Stereo",
    "Fusion",
]


def is_running(pid):
    if pid is None:
        return True
    return psutil.pid_exists(pid)


def update_state_from_line(line, state):
    if line.startswith("[STEP] "):
        step_name = line[7:].strip()
        if step_name in STEP_ORDER:
            step_index = STEP_ORDER.index(step_name)
            if step_index + 1 > state["completed_steps"]:
                state["completed_steps"] = step_index
            state["current_step"] = step_name

    if "[DONE]" in line:
        state["done"] = True
        state["completed_steps"] = len(STEP_ORDER)

    if "[ERROR]" in line:
        state["error"] = True

    if "Processed file" in line:
        state["feature_count"] += 1
    if "Matching block" in line or "Matching image" in line:
        state["matching_count"] += 1
    if "Registering image" in line:
        state["mapping_count"] += 1
    if "Processing view" in line:
        state["dense_count"] += 1
    if "Fusing image" in line:
        state["fusion_count"] += 1


def monitor_log(log_path, pid=None):
    state = {
        "current_step": "Waiting",
        "completed_steps": 0,
        "feature_count": 0,
        "matching_count": 0,
        "mapping_count": 0,
        "dense_count": 0,
        "fusion_count": 0,
        "done": False,
        "error": False,
    }

    pbar = tqdm(total=len(STEP_ORDER), desc="COLMAP Pipeline", ncols=100)
    last_position = 0

    try:
        while True:
            if log_path.exists():
                with log_path.open("r", encoding="utf-8", errors="ignore") as log_file:
                    log_file.seek(last_position)
                    for line in log_file:
                        update_state_from_line(line.strip(), state)
                    last_position = log_file.tell()

            pbar.n = min(state["completed_steps"], len(STEP_ORDER))
            pbar.set_postfix_str(
                f"{state['current_step']} | feat:{state['feature_count']} "
                f"match:{state['matching_count']} map:{state['mapping_count']} "
                f"dense:{state['dense_count']} fuse:{state['fusion_count']}"
            )
            pbar.refresh()

            if os.path.exists(DEFAULT_OUTPUT_PATH):
                state["done"] = True
                state["completed_steps"] = len(STEP_ORDER)
                print("\nReconstruction finished")
                break

            if state["done"] or state["error"]:
                break

            if pid is not None and not is_running(pid):
                if log_path.exists():
                    with log_path.open("r", encoding="utf-8", errors="ignore") as log_file:
                        log_file.seek(last_position)
                        for line in log_file:
                            update_state_from_line(line.strip(), state)
                        last_position = log_file.tell()
                print("\nPipeline process ended")
                break

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nMonitor stopped manually")
    finally:
        pbar.close()

    if state["error"]:
        print("Pipeline ended with an error. Check logs/colmap.log")
    elif state["done"]:
        print("Log monitor finished.")
    else:
        print("Pipeline process exited. Check logs/colmap.log for details.")


def main():
    parser = argparse.ArgumentParser(description="Monitor COLMAP progress by parsing logs/colmap.log.")
    parser.add_argument("--log", default=str(DEFAULT_LOG_PATH), help="Path to the COLMAP log file.")
    parser.add_argument("--pid", type=int, help="Optional PID of the pipeline process.")
    args = parser.parse_args()

    monitor_log(Path(args.log).resolve(), pid=args.pid)


if __name__ == "__main__":
    main()
