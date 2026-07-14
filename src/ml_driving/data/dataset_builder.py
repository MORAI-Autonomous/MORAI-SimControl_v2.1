from __future__ import annotations

import csv
import os
from typing import Iterable, List

from ml_driving.data.schema import FrameLabel, RunRecord


def discover_runs(runs_dir: str) -> List[RunRecord]:
    """Find recorded runs that have the minimum files needed for indexing."""

    records: List[RunRecord] = []
    if not os.path.isdir(runs_dir):
        return records

    for name in sorted(os.listdir(runs_dir)):
        run_dir = os.path.join(runs_dir, name)
        if not os.path.isdir(run_dir):
            continue
        config_path = os.path.join(run_dir, "run_config.json")
        summary_path = os.path.join(run_dir, "summary.json")
        telemetry_path = os.path.join(run_dir, "telemetry.csv")
        if not (
            os.path.exists(config_path)
            and os.path.exists(summary_path)
            and os.path.exists(telemetry_path)
        ):
            continue
        records.append(
            RunRecord(
                run_dir=os.path.abspath(run_dir),
                config_path=os.path.abspath(config_path),
                summary_path=os.path.abspath(summary_path),
                telemetry_path=os.path.abspath(telemetry_path),
                video_path=_optional_path(run_dir, "debug.mp4"),
                frames_dir=_optional_path(run_dir, "frames"),
                labels_path=_optional_path(run_dir, "labels.csv"),
            )
        )
    return records


def write_label_index(labels: Iterable[FrameLabel], output_csv: str) -> None:
    """Write frame labels to a flat CSV manifest."""

    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
    fieldnames = [
        "frame_index",
        "timestamp_s",
        "image_path",
        "speed_kmh",
        "steer",
        "throttle",
        "brake",
        "offset_m",
        "lane_detected",
        "status",
        "scenario",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for label in labels:
            writer.writerow(
                {
                    "frame_index": label.frame_index,
                    "timestamp_s": label.timestamp_s,
                    "image_path": label.image_path,
                    "speed_kmh": label.speed_kmh,
                    "steer": label.steer,
                    "throttle": label.throttle,
                    "brake": label.brake,
                    "offset_m": label.offset_m,
                    "lane_detected": label.lane_detected,
                    "status": label.status,
                    "scenario": label.scenario,
                }
            )


def _optional_path(run_dir: str, name: str) -> str:
    path = os.path.join(run_dir, name)
    return os.path.abspath(path) if os.path.exists(path) else ""

