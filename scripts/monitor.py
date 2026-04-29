import csv
import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psutil
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency at runtime
    pynvml = None


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GpuStats:
    utilization_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    temperature_c: float | None = None


class PipelineMonitor:
    def __init__(self, output_dir, sample_interval=1.0, gpu_index=0):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sample_interval = sample_interval
        self.gpu_index = gpu_index

        self.metrics_jsonl_path = self.output_dir / "metrics.jsonl"
        self.metrics_csv_path = self.output_dir / "metrics.csv"
        self.events_jsonl_path = self.output_dir / "events.jsonl"
        self.summary_json_path = self.output_dir / "stage_summary.json"
        self.stage_time_distribution_csv_path = self.output_dir / "stage_time_distribution.csv"
        self.gpu_usage_over_time_csv_path = self.output_dir / "gpu_usage_over_time.csv"
        self.cpu_usage_over_time_csv_path = self.output_dir / "cpu_usage_over_time.csv"
        self.comparisons_path = self.output_dir.parent / "comparisons.json"

        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._live = None
        self._progress = None
        self._task_id = None
        self._csv_file = None
        self._csv_writer = None
        self._json_file = None
        self._event_file = None
        self._nvml_handle = None
        self._nvml_initialized = False
        self._prev_disk = None
        self._prev_disk_ts = None

        self.started_at = time.time()
        self.started_at_iso = utc_timestamp()
        self.ended_at_iso = None
        self.current_stage = "idle"
        self.current_command = []
        self.pipeline_error = None
        self.pipeline_completed = False
        self.pipeline_active = True
        self.alert_counts = defaultdict(int)
        self.samples_written = 0

        self.frames = {
            "extracted": 0,
            "selected": 0,
            "sparse": 0,
            "dense": 0,
        }
        self.image_count_hint = 0

        self.stage_records = {}
        self.stage_order = []
        self.stage_sample_totals = defaultdict(
            lambda: {
                "samples": 0,
                "cpu_percent_sum": 0.0,
                "gpu_util_sum": 0.0,
                "ram_percent_sum": 0.0,
                "colmap_cpu_sum": 0.0,
                "colmap_memory_mb_sum": 0.0,
            }
        )

        self.visualization_series = {
            "gpu_usage_over_time": [],
            "cpu_usage_over_time": [],
        }
        self.last_sample_for_hang = None
        self.stagnation_seconds = 0.0
        self.dense_gpu_low_40_seconds = 0.0
        self.dense_gpu_low_25_seconds = 0.0
        self.summary_data = None

    def start(self):
        self._open_outputs()
        self._init_nvml()
        psutil.cpu_percent(interval=None, percpu=True)
        self._progress = Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30),
            TimeElapsedColumn(),
        )
        self._task_id = self._progress.add_task("COLMAP pipeline", total=None)
        self._live = Live(self._render_dashboard({}), refresh_per_second=4, transient=False)
        self._live.start()
        self._thread = threading.Thread(target=self._sampling_loop, name="pipeline-monitor", daemon=True)
        self._thread.start()
        self.emit_event({"event": "monitor_start", "stage": self.current_stage})

    def stop(self, success=True, error_message=None):
        self.pipeline_completed = success
        self.pipeline_active = False
        self.pipeline_error = error_message
        self.emit_event(
            {
                "event": "monitor_stop",
                "stage": self.current_stage,
                "success": success,
                "error": error_message,
            }
        )
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(3.0, self.sample_interval * 2))
        self.ended_at_iso = utc_timestamp()
        self._write_summary()
        if self._live is not None:
            self._live.stop()
        self._shutdown_nvml()
        self._close_outputs()

    def stage_event(self, payload):
        event = dict(payload)
        event.setdefault("timestamp", utc_timestamp())
        stage = event.get("stage", "unknown")
        with self._lock:
            if event.get("event") == "stage_start":
                self.current_stage = stage
                self.current_command = event.get("command", [])
                if stage not in self.stage_order:
                    self.stage_order.append(stage)
                self.stage_records[stage] = {
                    "start_time": time.time(),
                    "start_timestamp": event["timestamp"],
                    "command": event.get("command", []),
                }
                if "image_count" in event:
                    self.stage_records[stage]["image_count"] = event["image_count"]
            elif event.get("event") == "stage_end":
                record = self.stage_records.setdefault(stage, {})
                record["end_time"] = time.time()
                record["end_timestamp"] = event["timestamp"]
                record["success"] = event.get("success", True)
                record["returncode"] = event.get("returncode")
                if "image_count" in event:
                    record["image_count"] = event["image_count"]
                if "start_time" in record:
                    record["duration_seconds"] = record["end_time"] - record["start_time"]
                elif "duration_seconds" in event:
                    record["duration_seconds"] = event["duration_seconds"]
                self.current_stage = "idle"
                self.current_command = []
        self.emit_event(event)

    def record_frame_stats(self, *, extracted=0, selected=0, sparse=0, dense=0):
        with self._lock:
            if extracted:
                self.frames["extracted"] = int(extracted)
            if selected:
                self.frames["selected"] = int(selected)
                self.image_count_hint = int(selected)
            if sparse:
                self.frames["sparse"] = int(sparse)
            if dense:
                self.frames["dense"] = int(dense)

    def emit_event(self, payload):
        event = dict(payload)
        event.setdefault("timestamp", utc_timestamp())
        if self._event_file is not None:
            self._event_file.write(json.dumps(event) + "\n")
            self._event_file.flush()

    def _open_outputs(self):
        self._json_file = self.metrics_jsonl_path.open("w", encoding="utf-8")
        self._event_file = self.events_jsonl_path.open("w", encoding="utf-8")
        self._csv_file = self.metrics_csv_path.open("w", encoding="utf-8", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_file,
            fieldnames=[
                "timestamp",
                "elapsed_seconds",
                "current_stage",
                "cpu_percent",
                "cpu_temperature_c",
                "ram_percent",
                "ram_used_gb",
                "ram_available_gb",
                "disk_read_mb_s",
                "disk_write_mb_s",
                "gpu_util_percent",
                "gpu_memory_used_mb",
                "gpu_memory_total_mb",
                "gpu_temperature_c",
                "colmap_process_count",
                "colmap_cpu_percent",
                "colmap_memory_mb",
                "alerts",
            ],
        )
        self._csv_writer.writeheader()

    def _close_outputs(self):
        for handle in (self._json_file, self._event_file, self._csv_file):
            if handle is not None:
                handle.close()

    def _init_nvml(self):
        if pynvml is None:
            return
        try:
            pynvml.nvmlInit()
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(self.gpu_index)
            self._nvml_initialized = True
        except Exception:
            self._nvml_handle = None
            self._nvml_initialized = False

    def _shutdown_nvml(self):
        if self._nvml_initialized and pynvml is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def _sampling_loop(self):
        while not self._stop_event.is_set():
            started = time.time()
            sample = self._collect_sample()
            self._write_sample(sample)
            if self._live is not None:
                self._live.update(self._render_dashboard(sample))
            elapsed = time.time() - started
            self._stop_event.wait(max(0.0, self.sample_interval - elapsed))

    def _collect_sample(self):
        now = time.time()
        elapsed = now - self.started_at
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        cpu_percent = round(sum(per_core) / len(per_core), 2) if per_core else 0.0
        cpu_temp = self._cpu_temperature()
        vm = psutil.virtual_memory()
        disk_read_mb_s, disk_write_mb_s = self._disk_rates(now)
        gpu = self._gpu_stats()
        colmap = self._colmap_process_stats()

        with self._lock:
            stage_name = self.current_stage
            current_command = list(self.current_command)

        alerts = self._detect_alerts(cpu_percent, cpu_temp, vm, gpu, colmap, disk_read_mb_s, disk_write_mb_s)

        with self._lock:
            if stage_name != "idle":
                totals = self.stage_sample_totals[stage_name]
                totals["samples"] += 1
                totals["cpu_percent_sum"] += cpu_percent
                totals["gpu_util_sum"] += gpu.utilization_percent or 0.0
                totals["ram_percent_sum"] += vm.percent
                totals["colmap_cpu_sum"] += colmap["cpu_percent"]
                totals["colmap_memory_mb_sum"] += colmap["memory_mb"]

        sample = {
            "timestamp": utc_timestamp(),
            "elapsed_seconds": round(elapsed, 2),
            "stage": {
                "current": stage_name,
                "command": current_command,
            },
            "system": {
                "cpu_percent": cpu_percent,
                "per_core_percent": per_core,
                "cpu_temperature_c": cpu_temp,
                "ram_percent": vm.percent,
                "ram_used_gb": round(vm.used / (1024 ** 3), 2),
                "ram_available_gb": round(vm.available / (1024 ** 3), 2),
                "disk_read_mb_s": disk_read_mb_s,
                "disk_write_mb_s": disk_write_mb_s,
            },
            "gpu": {
                "utilization_percent": gpu.utilization_percent,
                "memory_used_mb": gpu.memory_used_mb,
                "memory_total_mb": gpu.memory_total_mb,
                "temperature_c": gpu.temperature_c,
            },
            "colmap_process": colmap,
            "alerts": alerts,
        }
        self.samples_written += 1
        self.visualization_series["gpu_usage_over_time"].append(
            {
                "timestamp": sample["timestamp"],
                "elapsed_seconds": sample["elapsed_seconds"],
                "stage": stage_name,
                "gpu_util_percent": gpu.utilization_percent,
                "gpu_memory_used_mb": gpu.memory_used_mb,
            }
        )
        self.visualization_series["cpu_usage_over_time"].append(
            {
                "timestamp": sample["timestamp"],
                "elapsed_seconds": sample["elapsed_seconds"],
                "stage": stage_name,
                "cpu_percent": cpu_percent,
                "colmap_cpu_percent": colmap["cpu_percent"],
                "ram_percent": vm.percent,
            }
        )
        return sample

    def _cpu_temperature(self):
        try:
            sensors = psutil.sensors_temperatures()
        except Exception:
            return None
        if not sensors:
            return None
        for entries in sensors.values():
            for entry in entries:
                if entry.current is not None:
                    return round(float(entry.current), 1)
        return None

    def _disk_rates(self, now):
        counters = psutil.disk_io_counters()
        if counters is None:
            return 0.0, 0.0
        if self._prev_disk is None:
            self._prev_disk = counters
            self._prev_disk_ts = now
            return 0.0, 0.0
        elapsed = max(now - self._prev_disk_ts, 1e-6)
        read_mb_s = round((counters.read_bytes - self._prev_disk.read_bytes) / elapsed / (1024 ** 2), 2)
        write_mb_s = round((counters.write_bytes - self._prev_disk.write_bytes) / elapsed / (1024 ** 2), 2)
        self._prev_disk = counters
        self._prev_disk_ts = now
        return max(0.0, read_mb_s), max(0.0, write_mb_s)

    def _gpu_stats(self):
        if not self._nvml_initialized or self._nvml_handle is None:
            return GpuStats()
        try:
            utilization = pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
            memory = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
            temperature = pynvml.nvmlDeviceGetTemperature(self._nvml_handle, pynvml.NVML_TEMPERATURE_GPU)
            return GpuStats(
                utilization_percent=float(utilization.gpu),
                memory_used_mb=round(memory.used / (1024 ** 2), 2),
                memory_total_mb=round(memory.total / (1024 ** 2), 2),
                temperature_c=float(temperature),
            )
        except Exception:
            return GpuStats()

    def _colmap_process_stats(self):
        matches = []
        for process in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
            try:
                name = (process.info.get("name") or "").lower()
                cmdline = " ".join(process.info.get("cmdline") or []).lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if "colmap" in name or "colmap" in cmdline:
                matches.append(process)

        total_cpu = 0.0
        total_memory_mb = 0.0
        pids = []
        for process in matches:
            try:
                total_cpu += process.cpu_percent(interval=None)
                total_memory_mb += process.memory_info().rss / (1024 ** 2)
                pids.append(process.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            "pid_count": len(pids),
            "pids": pids,
            "cpu_percent": round(total_cpu, 2),
            "memory_mb": round(total_memory_mb, 2),
        }

    def _sample_signature(self, cpu_percent, gpu_util, ram_percent, disk_read_mb_s, disk_write_mb_s, colmap_cpu, colmap_mem):
        return (
            round(cpu_percent, 1),
            round(gpu_util or 0.0, 1),
            round(ram_percent, 1),
            round(disk_read_mb_s, 1),
            round(disk_write_mb_s, 1),
            round(colmap_cpu, 1),
            round(colmap_mem, 1),
        )

    def _record_alert(self, alerts, severity, code, message):
        alerts.append({"severity": severity, "code": code, "message": message})
        self.alert_counts[f"{severity}:{code}"] += 1

    def _detect_alerts(self, cpu_percent, cpu_temp, vm, gpu, colmap, disk_read_mb_s, disk_write_mb_s):
        alerts = []

        if cpu_temp is not None and cpu_temp > 90.0 and cpu_percent < 60.0:
            self._record_alert(alerts, "warning", "cpu_throttling", "CPU temperature is above 90C while utilization is below 60%; throttling is likely.")

        if vm.percent > 90.0:
            self._record_alert(alerts, "warning", "memory_pressure", "RAM utilization exceeded 90%.")

        gpu_util = gpu.utilization_percent or 0.0
        if self.current_stage == "patch_match_stereo":
            if gpu_util < 40.0:
                self.dense_gpu_low_40_seconds += self.sample_interval
                if self.dense_gpu_low_40_seconds > 10.0:
                    self._record_alert(alerts, "warning", "dense_gpu_underutilized", "GPU utilization stayed below 40% for more than 10 seconds during dense reconstruction.")
            else:
                self.dense_gpu_low_40_seconds = 0.0

            if gpu_util < 25.0:
                self.dense_gpu_low_25_seconds += self.sample_interval
                if self.dense_gpu_low_25_seconds > 20.0:
                    self._record_alert(alerts, "critical", "dense_gpu_very_low", "GPU utilization stayed below 25% for more than 20 seconds during dense reconstruction.")
            else:
                self.dense_gpu_low_25_seconds = 0.0
        else:
            self.dense_gpu_low_40_seconds = 0.0
            self.dense_gpu_low_25_seconds = 0.0

        signature = self._sample_signature(
            cpu_percent,
            gpu_util,
            vm.percent,
            disk_read_mb_s,
            disk_write_mb_s,
            colmap["cpu_percent"],
            colmap["memory_mb"],
        )
        if self.last_sample_for_hang == signature and self.current_stage != "idle":
            self.stagnation_seconds += self.sample_interval
            if self.stagnation_seconds > 15.0:
                self._record_alert(alerts, "warning", "possible_hang", "Metrics have not changed for more than 15 seconds; the pipeline may be stalled.")
        else:
            self.stagnation_seconds = 0.0
        self.last_sample_for_hang = signature

        return alerts

    def _write_sample(self, sample):
        self._json_file.write(json.dumps(sample) + "\n")
        self._json_file.flush()
        self._csv_writer.writerow(
            {
                "timestamp": sample["timestamp"],
                "elapsed_seconds": sample["elapsed_seconds"],
                "current_stage": sample["stage"]["current"],
                "cpu_percent": sample["system"]["cpu_percent"],
                "cpu_temperature_c": sample["system"]["cpu_temperature_c"],
                "ram_percent": sample["system"]["ram_percent"],
                "ram_used_gb": sample["system"]["ram_used_gb"],
                "ram_available_gb": sample["system"]["ram_available_gb"],
                "disk_read_mb_s": sample["system"]["disk_read_mb_s"],
                "disk_write_mb_s": sample["system"]["disk_write_mb_s"],
                "gpu_util_percent": sample["gpu"]["utilization_percent"],
                "gpu_memory_used_mb": sample["gpu"]["memory_used_mb"],
                "gpu_memory_total_mb": sample["gpu"]["memory_total_mb"],
                "gpu_temperature_c": sample["gpu"]["temperature_c"],
                "colmap_process_count": sample["colmap_process"]["pid_count"],
                "colmap_cpu_percent": sample["colmap_process"]["cpu_percent"],
                "colmap_memory_mb": sample["colmap_process"]["memory_mb"],
                "alerts": "|".join(alert["code"] for alert in sample["alerts"]),
            }
        )
        self._csv_file.flush()

    def _render_dashboard(self, sample):
        stage = sample.get("stage", {}).get("current", self.current_stage)
        system = sample.get("system", {})
        gpu = sample.get("gpu", {})
        colmap = sample.get("colmap_process", {})
        alerts = sample.get("alerts", [])

        status = Table.grid(expand=True)
        status.add_column()
        status.add_column()
        status.add_row("Stage", stage)
        status.add_row("Elapsed", f"{sample.get('elapsed_seconds', 0.0):.1f}s")
        status.add_row("CPU", f"{system.get('cpu_percent', 0.0)}%")
        status.add_row("GPU", f"{gpu.get('utilization_percent', 'n/a')}%")
        status.add_row("RAM", f"{system.get('ram_percent', 0.0)}%")
        status.add_row("COLMAP Proc", str(colmap.get("pid_count", 0)))

        details = Table(title="System Metrics", expand=True)
        details.add_column("Metric")
        details.add_column("Value")
        details.add_row("CPU Temp", str(system.get("cpu_temperature_c")))
        details.add_row("VRAM", f"{gpu.get('memory_used_mb', 'n/a')} / {gpu.get('memory_total_mb', 'n/a')} MB")
        details.add_row("GPU Temp", str(gpu.get("temperature_c")))
        details.add_row("Disk R/W", f"{system.get('disk_read_mb_s', 0.0)} / {system.get('disk_write_mb_s', 0.0)} MB/s")
        details.add_row("COLMAP CPU", f"{colmap.get('cpu_percent', 0.0)}%")
        details.add_row("COLMAP RAM", f"{colmap.get('memory_mb', 0.0)} MB")

        alert_text = ", ".join(f"{alert['severity']}:{alert['code']}" for alert in alerts) if alerts else "none"
        self._progress.update(self._task_id, description=f"Pipeline stage: {stage}")

        return Group(
            Panel(status, title="Pipeline Monitor", border_style="cyan"),
            self._progress,
            Panel(details, title=f"Alerts: {alert_text}", border_style="magenta"),
        )

    def _stage_image_count(self, stage):
        if stage == "extract_frames":
            return self.frames["extracted"] or 0
        if stage in {"feature_extractor", "sequential_matcher", "mapper"}:
            return self.frames["selected"] or self.image_count_hint or 0
        if stage in {"image_undistorter", "patch_match_stereo", "stereo_fusion"}:
            return self.frames["dense"] or self.frames["sparse"] or self.frames["selected"] or self.image_count_hint or 0
        return self.image_count_hint or self.frames["selected"] or 0

    def _write_stage_time_distribution_csv(self, stage_time_percent):
        with self.stage_time_distribution_csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["stage", "duration_seconds", "percent_of_total"])
            writer.writeheader()
            for stage in self.stage_order:
                record = self.stage_records.get(stage, {})
                writer.writerow(
                    {
                        "stage": stage,
                        "duration_seconds": round(record.get("duration_seconds", 0.0), 2),
                        "percent_of_total": stage_time_percent.get(stage, 0.0),
                    }
                )

    def _write_series_csv(self, path, rows):
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _performance_score(self, total_duration_seconds, avg_gpu_util, avg_time_per_image):
        runtime_component = max(0.0, min(1.0, 1.0 - (total_duration_seconds / 3600.0)))
        gpu_component = max(0.0, min(1.0, avg_gpu_util / 100.0))
        efficiency_component = 0.0
        if avg_time_per_image is not None:
            efficiency_component = max(0.0, min(1.0, 1.0 - (avg_time_per_image / 10.0)))
        score = (gpu_component * 0.4) + (runtime_component * 0.35) + (efficiency_component * 0.25)
        return round(score * 100.0, 2)

    def _load_previous_summary(self):
        if not self.output_dir.parent.exists():
            return None
        candidates = sorted(
            path for path in self.output_dir.parent.iterdir()
            if path.is_dir() and (path / "stage_summary.json").exists() and path != self.output_dir
        )
        if not candidates:
            return None
        return json.loads((candidates[-1] / "stage_summary.json").read_text(encoding="utf-8"))

    def _update_comparisons(self, summary):
        previous = self._load_previous_summary()
        comparison = {
            "dense_time_change_percent": None,
            "total_time_change_percent": None,
            "gpu_util_change": None,
            "frame_count_change": None,
        }
        if previous:
            previous_dense = previous.get("stages", {}).get("patch_match_stereo", {}).get("duration_seconds")
            current_dense = summary.get("stages", {}).get("patch_match_stereo", {}).get("duration_seconds")
            previous_total = previous.get("total_duration_seconds")
            current_total = summary.get("total_duration_seconds")
            previous_gpu = previous.get("stages", {}).get("patch_match_stereo", {}).get("avg_gpu_util_percent")
            current_gpu = summary.get("stages", {}).get("patch_match_stereo", {}).get("avg_gpu_util_percent")
            previous_selected = previous.get("frames", {}).get("selected")
            current_selected = summary.get("frames", {}).get("selected")

            comparison["dense_time_change_percent"] = self._percent_change(previous_dense, current_dense)
            comparison["total_time_change_percent"] = self._percent_change(previous_total, current_total)
            comparison["gpu_util_change"] = round((current_gpu or 0.0) - (previous_gpu or 0.0), 2) if current_gpu is not None and previous_gpu is not None else None
            comparison["frame_count_change"] = int((current_selected or 0) - (previous_selected or 0)) if current_selected is not None and previous_selected is not None else None

        all_comparisons = []
        if self.comparisons_path.exists():
            try:
                all_comparisons = json.loads(self.comparisons_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                all_comparisons = []
        all_comparisons.append(
            {
                "run_id": self.output_dir.name,
                "timestamp": self.ended_at_iso or utc_timestamp(),
                "comparison": comparison,
            }
        )
        self.comparisons_path.write_text(json.dumps(all_comparisons, indent=2), encoding="utf-8")
        return comparison

    def _percent_change(self, previous, current):
        if previous in (None, 0) or current is None:
            return None
        return round(((current - previous) / previous) * 100.0, 2)

    def _generate_insights(self, stage_time_percent, bottleneck_stage, stages, comparison):
        insights = []
        if bottleneck_stage:
            insights.append(f"{bottleneck_stage} dominates runtime ({stage_time_percent.get(bottleneck_stage, 0.0)}%).")

        dense_stage = stages.get("patch_match_stereo", {})
        dense_gpu = dense_stage.get("avg_gpu_util_percent", 0.0)
        if dense_gpu < 40.0:
            insights.append(f"GPU utilization is suboptimal during dense reconstruction (avg {dense_gpu}%).")

        if self.frames["selected"] and self.frames["extracted"]:
            keep_ratio = self.frames["selected"] / max(self.frames["extracted"], 1)
            if keep_ratio > 0.8:
                insights.append("Frame count remains high after filtering; tighten duplicate or motion thresholds.")

        dense_time_per_image = dense_stage.get("time_per_image")
        if dense_time_per_image is not None and dense_time_per_image > 2.0:
            insights.append("Dense time per image is high; consider reducing max_image_size or pruning weak frames before dense.")

        if comparison.get("total_time_change_percent") is not None and comparison["total_time_change_percent"] > 10.0:
            insights.append(f"Total runtime regressed by {comparison['total_time_change_percent']}% versus the previous run.")

        if not insights:
            insights.append("Pipeline efficiency is balanced; no dominant regressions were detected in this run.")
        return insights

    def _write_summary(self):
        total_duration = round(time.time() - self.started_at, 2)
        stages = {}
        total_stage_time = sum(self.stage_records.get(stage, {}).get("duration_seconds", 0.0) or 0.0 for stage in self.stage_order)

        for stage in self.stage_order:
            record = self.stage_records.get(stage, {})
            totals = self.stage_sample_totals.get(stage, {})
            samples = totals.get("samples", 0)
            image_count = record.get("image_count") or self._stage_image_count(stage)
            duration = round(record.get("duration_seconds", 0.0), 2) if record else None
            avg_cpu = round(totals.get("cpu_percent_sum", 0.0) / samples, 2) if samples else 0.0
            avg_gpu = round(totals.get("gpu_util_sum", 0.0) / samples, 2) if samples else 0.0
            avg_ram = round(totals.get("ram_percent_sum", 0.0) / samples, 2) if samples else 0.0
            avg_colmap_cpu = round(totals.get("colmap_cpu_sum", 0.0) / samples, 2) if samples else 0.0
            avg_colmap_mem = round(totals.get("colmap_memory_mb_sum", 0.0) / samples, 2) if samples else 0.0
            time_per_image = round(duration / image_count, 4) if duration is not None and image_count else None

            stages[stage] = {
                "start_timestamp": record.get("start_timestamp"),
                "end_timestamp": record.get("end_timestamp"),
                "duration_seconds": duration,
                "success": record.get("success"),
                "returncode": record.get("returncode"),
                "command": record.get("command"),
                "samples": samples,
                "image_count": image_count,
                "avg_cpu_percent": avg_cpu,
                "avg_gpu_util_percent": avg_gpu,
                "avg_ram_percent": avg_ram,
                "avg_colmap_cpu_percent": avg_colmap_cpu,
                "avg_colmap_memory_mb": avg_colmap_mem,
                "time_per_image": time_per_image,
                "gpu_efficiency_score": round(avg_gpu / 100.0, 4),
                "cpu_efficiency_score": round(avg_cpu / 100.0, 4),
            }

        if not self.frames["sparse"]:
            self.frames["sparse"] = self.frames["selected"]
        if not self.frames["dense"]:
            self.frames["dense"] = self.frames["sparse"]

        stage_time_percent = {}
        bottleneck_stage = None
        if total_stage_time > 0:
            stage_time_percent = {
                stage: round(((self.stage_records.get(stage, {}).get("duration_seconds", 0.0) or 0.0) / total_stage_time) * 100.0, 2)
                for stage in self.stage_order
            }
            bottleneck_stage = max(stage_time_percent, key=stage_time_percent.get) if stage_time_percent else None

        avg_dense_gpu = stages.get("patch_match_stereo", {}).get("avg_gpu_util_percent", 0.0)
        time_per_image_values = [stage["time_per_image"] for stage in stages.values() if stage["time_per_image"] is not None]
        avg_time_per_image = round(sum(time_per_image_values) / len(time_per_image_values), 4) if time_per_image_values else None
        performance_score = self._performance_score(total_duration, avg_dense_gpu, avg_time_per_image)

        summary = {
            "pipeline_started_at": self.started_at_iso,
            "pipeline_ended_at": self.ended_at_iso or utc_timestamp(),
            "total_duration_seconds": total_duration,
            "pipeline_completed": self.pipeline_completed,
            "pipeline_error": self.pipeline_error,
            "samples_written": self.samples_written,
            "frames": dict(self.frames),
            "alert_counts": dict(self.alert_counts),
            "bottleneck_stage": bottleneck_stage,
            "stage_time_percent": stage_time_percent,
            "performance_score": performance_score,
            "visualization_outputs": {
                "stage_time_distribution": str(self.stage_time_distribution_csv_path),
                "gpu_usage_over_time": str(self.gpu_usage_over_time_csv_path),
                "cpu_usage_over_time": str(self.cpu_usage_over_time_csv_path),
            },
            "stages": stages,
        }

        self._write_stage_time_distribution_csv(stage_time_percent)
        self._write_series_csv(self.gpu_usage_over_time_csv_path, self.visualization_series["gpu_usage_over_time"])
        self._write_series_csv(self.cpu_usage_over_time_csv_path, self.visualization_series["cpu_usage_over_time"])

        comparison = self._update_comparisons(summary)
        summary["comparison"] = comparison
        summary["insights"] = self._generate_insights(stage_time_percent, bottleneck_stage, stages, comparison)

        self.summary_data = summary
        self.summary_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
