from __future__ import annotations

"""Lightweight ML driving pipeline runner for recorded Lane Control runs."""

import argparse
import csv
import json
import os
from typing import Any, Dict, List, Optional

from ml_driving.data.dataset_builder import discover_runs
from ml_driving.evaluation.metrics import binary_quality_from_samples, lane_quality_from_offsets


_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_RUNS_DIR = os.path.join(_ROOT_DIR, "runs", "lane_control")
_DEFAULT_REPORT_PATH = os.path.join(_ROOT_DIR, "runs", "ml_driving_report.json")


def build_lane_control_report(runs_dir: str = _DEFAULT_RUNS_DIR, limit: int = 20) -> Dict[str, Any]:
    """Build a compact KPI report from recorded Lane Control runs."""

    runs = discover_runs(runs_dir)
    if limit > 0:
        runs = runs[-limit:]

    entries = []
    for run in runs:
        summary = _load_json(run.summary_path)
        offsets = _load_offsets(run.telemetry_path)
        white_ratios, upper_shares, shadow_scores = _load_binary_quality_samples(run.telemetry_path)
        lane_quality = lane_quality_from_offsets(offsets)
        binary_quality = binary_quality_from_samples(white_ratios, upper_shares, shadow_scores)
        entries.append(
            {
                "run_dir": run.run_dir,
                "score": _float_value(summary.get("score")),
                "duration_s": _float_value(summary.get("duration_s")),
                "valid_drive_time_s": _float_value(summary.get("valid_drive_time_s")),
                "valid_drive_distance_m": _float_value(summary.get("valid_drive_distance_m")),
                "mean_abs_offset_m": lane_quality.mean_abs_offset_m,
                "p95_abs_offset_m": lane_quality.p95_abs_offset_m,
                "lane_violation_ratio_08m": lane_quality.lane_violation_ratio_08m,
                "lane_violation_ratio_10m": lane_quality.lane_violation_ratio_10m,
                "binary_white_ratio_p95": binary_quality.p95_white_ratio,
                "binary_upper_white_share_p95": binary_quality.p95_upper_white_share,
                "shadow_boundary_score_p95": binary_quality.p95_shadow_boundary_score,
                "binary_noisy_frame_ratio": binary_quality.noisy_frame_ratio,
                "recorded_lane_violation_ratio_08m": _float_value(
                    summary.get("lane_violation_ratio_08m")
                ),
                "recorded_lane_violation_ratio_10m": _float_value(
                    summary.get("lane_violation_ratio_10m")
                ),
            }
        )

    return {
        "runs_dir": os.path.abspath(runs_dir),
        "run_count": len(entries),
        "entries": entries,
    }


def write_lane_control_report(
    runs_dir: str = _DEFAULT_RUNS_DIR,
    output_path: str = _DEFAULT_REPORT_PATH,
    limit: int = 20,
) -> Dict[str, Any]:
    report = build_lane_control_report(runs_dir=runs_dir, limit=limit)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    return report


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_offsets(telemetry_path: str) -> List[Optional[float]]:
    offsets: List[Optional[float]] = []
    if not os.path.exists(telemetry_path):
        return offsets
    with open(telemetry_path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            offsets.append(_float_value(row.get("smooth_offset_m")))
    return offsets


def _load_binary_quality_samples(telemetry_path: str) -> tuple:
    white_ratios: List[Optional[float]] = []
    upper_shares: List[Optional[float]] = []
    shadow_scores: List[Optional[float]] = []
    if not os.path.exists(telemetry_path):
        return white_ratios, upper_shares, shadow_scores
    with open(telemetry_path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            white_ratios.append(_float_value(row.get("binary_white_ratio")))
            upper_shares.append(_float_value(row.get("binary_upper_white_share")))
            shadow_scores.append(_float_value(row.get("shadow_boundary_score")))
    return white_ratios, upper_shares, shadow_scores


def _float_value(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ML driving KPI report over Lane Control runs.")
    parser.add_argument("--runs-dir", default=_DEFAULT_RUNS_DIR)
    parser.add_argument("--output", default=_DEFAULT_REPORT_PATH)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    report = write_lane_control_report(
        runs_dir=args.runs_dir,
        output_path=args.output,
        limit=args.limit,
    )
    print(f"wrote {args.output}")
    print(f"runs={report['run_count']}")
    if report["entries"]:
        latest = report["entries"][-1]
        print(
            "latest "
            f"score={latest['score']} "
            f"p95={latest['p95_abs_offset_m']} "
            f"vio08={latest['lane_violation_ratio_08m']} "
            f"vio10={latest['lane_violation_ratio_10m']} "
            f"shadow={latest['shadow_boundary_score_p95']} "
            f"noise={latest['binary_noisy_frame_ratio']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
