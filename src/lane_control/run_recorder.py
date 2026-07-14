from __future__ import annotations

"""Run recorder for Lane Control experiments."""

import csv
import json
import math
import os
import time
from typing import Any, Dict, List, Optional

from ml_driving.evaluation.metrics import binary_quality_from_samples, lane_quality_from_offsets


_CSV_FIELDS = [
    "frame_index",
    "timestamp_s",
    "elapsed_s",
    "status",
    "ready",
    "left_detected",
    "right_detected",
    "raw_offset_m",
    "smooth_offset_m",
    "curve_radius_m",
    "steer_raw",
    "steer_limited",
    "steer_out",
    "throttle",
    "brake",
    "speed_kmh",
    "target_kmh",
    "binary_white_ratio",
    "binary_upper_white_share",
    "shadow_boundary_score",
    "no_det_count",
    "no_valid_count",
]


def _clean_value(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


class LaneRunRecorder:
    """Persist one Lane Control run and compute basic quality metrics."""

    def __init__(self, run_dir: str, config: Dict[str, Any], log_fn=None):
        self.run_dir = os.path.abspath(run_dir)
        self.video_path = os.path.join(self.run_dir, "debug.mp4")
        self.telemetry_path = os.path.join(self.run_dir, "telemetry.csv")
        self.config_path = os.path.join(self.run_dir, "run_config.json")
        self.summary_path = os.path.join(self.run_dir, "summary.json")
        self._config = dict(config)
        self._log = log_fn or (lambda msg, level="INFO": None)
        self._started_at = time.time()
        self._frame_count = 0
        self._last_steer: Optional[float] = None
        self._last_timestamp_s: Optional[float] = None
        self._offset_abs: List[float] = []
        self._steer_delta_sq: List[float] = []
        self._speed_error_abs: List[float] = []
        self._binary_white_ratios: List[float] = []
        self._binary_upper_white_shares: List[float] = []
        self._shadow_boundary_scores: List[float] = []
        self._status_counts: Dict[str, int] = {}
        self._total_distance_m = 0.0
        self._valid_drive_distance_m = 0.0
        self._valid_drive_time_s = 0.0
        self._lane_violation_time_08m = 0.0
        self._lane_violation_time_10m = 0.0
        self._csv_file = None
        self._writer = None

    def open(self) -> None:
        os.makedirs(self.run_dir, exist_ok=True)
        self._config["run_dir"] = self.run_dir
        self._config["video_path"] = self.video_path
        self._config["created_at_s"] = self._started_at
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, sort_keys=True)
        self._csv_file = open(self.telemetry_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._csv_file, fieldnames=_CSV_FIELDS)
        self._writer.writeheader()
        self._log(f"[Record] run dir: {self.run_dir}")

    def record(self, row: Dict[str, Any]) -> None:
        if self._writer is None:
            return

        self._frame_count += 1
        timestamp_s = float(row.get("timestamp_s") or time.time())
        out = {
            "frame_index": self._frame_count,
            "timestamp_s": timestamp_s,
            "elapsed_s": timestamp_s - self._started_at,
        }
        for field in _CSV_FIELDS:
            if field not in out:
                out[field] = _clean_value(row.get(field))
        self._writer.writerow(out)

        status = str(out.get("status") or "")
        status_key = status.split("(", 1)[0]
        self._status_counts[status_key] = self._status_counts.get(status_key, 0) + 1

        dt = 0.0
        if self._last_timestamp_s is not None:
            dt = max(0.0, timestamp_s - self._last_timestamp_s)
        self._last_timestamp_s = timestamp_s
        speed = out.get("speed_kmh")
        speed_mps = float(speed) / 3.6 if isinstance(speed, (int, float)) else 0.0
        distance_m = speed_mps * dt
        self._total_distance_m += distance_m
        lane_ok = status_key in ("DET", "REC") and bool(out.get("ready"))
        if lane_ok and speed_mps > (0.5 / 3.6):
            self._valid_drive_distance_m += distance_m
            self._valid_drive_time_s += dt

        offset = out.get("smooth_offset_m")
        if isinstance(offset, (int, float)):
            abs_offset = abs(float(offset))
            self._offset_abs.append(abs_offset)
            if lane_ok and dt > 0.0:
                if abs_offset > 0.8:
                    self._lane_violation_time_08m += dt
                if abs_offset > 1.0:
                    self._lane_violation_time_10m += dt

        steer = out.get("steer_out")
        if isinstance(steer, (int, float)) and self._last_steer is not None:
            delta = float(steer) - self._last_steer
            self._steer_delta_sq.append(delta * delta)
        if isinstance(steer, (int, float)):
            self._last_steer = float(steer)

        target = out.get("target_kmh")
        if isinstance(speed, (int, float)) and isinstance(target, (int, float)):
            self._speed_error_abs.append(abs(float(target) - float(speed)))

        binary_white_ratio = out.get("binary_white_ratio")
        if isinstance(binary_white_ratio, (int, float)):
            self._binary_white_ratios.append(float(binary_white_ratio))
        binary_upper_white_share = out.get("binary_upper_white_share")
        if isinstance(binary_upper_white_share, (int, float)):
            self._binary_upper_white_shares.append(float(binary_upper_white_share))
        shadow_boundary_score = out.get("shadow_boundary_score")
        if isinstance(shadow_boundary_score, (int, float)):
            self._shadow_boundary_scores.append(float(shadow_boundary_score))

    def close(self, stop_reason: str = "stopped") -> Dict[str, Any]:
        if self._csv_file is not None:
            self._csv_file.flush()
            self._csv_file.close()
            self._csv_file = None
            self._writer = None

        duration_s = max(0.0, time.time() - self._started_at)
        frame_count = max(1, self._frame_count)
        no_det = sum(v for k, v in self._status_counts.items() if k.startswith("NO_DET"))
        bad_w = sum(v for k, v in self._status_counts.items() if k.startswith("BAD_W"))
        lane_quality = lane_quality_from_offsets(self._offset_abs)
        binary_quality = binary_quality_from_samples(
            self._binary_white_ratios,
            self._binary_upper_white_shares,
            self._shadow_boundary_scores,
        )
        mean_abs_offset = lane_quality.mean_abs_offset_m
        p95_abs_offset = lane_quality.p95_abs_offset_m
        steer_delta_rms = (
            math.sqrt(sum(self._steer_delta_sq) / len(self._steer_delta_sq))
            if self._steer_delta_sq
            else None
        )
        speed_error_mean = (
            sum(self._speed_error_abs) / len(self._speed_error_abs)
            if self._speed_error_abs
            else None
        )

        score = 0.0
        if mean_abs_offset is not None:
            score += mean_abs_offset
        if p95_abs_offset is not None:
            score += p95_abs_offset * 0.8
        score += (no_det / frame_count) * 3.0
        score += (bad_w / frame_count) * 1.5
        score += lane_quality.lane_violation_ratio_08m * 2.0
        score += lane_quality.lane_violation_ratio_10m * 3.0
        score += binary_quality.noisy_frame_ratio * 1.5
        if binary_quality.p95_white_ratio is not None:
            score += max(0.0, binary_quality.p95_white_ratio - 0.08) * 10.0
        if steer_delta_rms is not None:
            score += steer_delta_rms * 0.5
        if speed_error_mean is not None:
            score += speed_error_mean * 0.2

        summary = {
            "run_dir": self.run_dir,
            "stop_reason": stop_reason,
            "duration_s": duration_s,
            "frame_count": self._frame_count,
            "status_counts": self._status_counts,
            "mean_abs_offset_m": mean_abs_offset,
            "p95_abs_offset_m": p95_abs_offset,
            "lane_violation_ratio_08m": lane_quality.lane_violation_ratio_08m,
            "lane_violation_ratio_10m": lane_quality.lane_violation_ratio_10m,
            "lane_violation_time_08m_s": self._lane_violation_time_08m,
            "lane_violation_time_10m_s": self._lane_violation_time_10m,
            "binary_white_ratio_mean": binary_quality.mean_white_ratio,
            "binary_white_ratio_p95": binary_quality.p95_white_ratio,
            "binary_upper_white_share_mean": binary_quality.mean_upper_white_share,
            "binary_upper_white_share_p95": binary_quality.p95_upper_white_share,
            "shadow_boundary_score_mean": binary_quality.mean_shadow_boundary_score,
            "shadow_boundary_score_p95": binary_quality.p95_shadow_boundary_score,
            "binary_noisy_frame_ratio": binary_quality.noisy_frame_ratio,
            "no_detect_ratio": no_det / frame_count,
            "bad_width_ratio": bad_w / frame_count,
            "steer_delta_rms": steer_delta_rms,
            "speed_error_mean_kmh": speed_error_mean,
            "total_distance_m": self._total_distance_m,
            "valid_drive_distance_m": self._valid_drive_distance_m,
            "valid_drive_time_s": self._valid_drive_time_s,
            "score": score,
            "config_path": self.config_path,
            "telemetry_path": self.telemetry_path,
            "video_path": self.video_path,
        }
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, sort_keys=True)
        self._log(f"[Record] summary: score={score:.3f}, frames={self._frame_count}")
        return summary
