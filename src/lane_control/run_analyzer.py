from __future__ import annotations

"""Analyze Lane Control run artifacts and suggest the next test parameters."""

import csv
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from ml_driving.evaluation.metrics import binary_quality_from_samples, lane_quality_from_offsets


_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_RUNS_DIR = os.path.join(_ROOT_DIR, "runs", "lane_control")
_STABLE_SPEED_STEP_KMH = 2.0
_MAX_AUTO_TARGET_KMH = 40.0
_ANCHOR_MIN_DURATION_S = 30.0
_ANCHOR_MIN_DISTANCE_M = 45.0
_ANCHOR_MAX_MEAN_OFFSET_M = 0.40
_ANCHOR_MAX_P95_OFFSET_M = 1.35
_ANCHOR_MAX_VIOLATION_08M = 0.16
_ANCHOR_MAX_VIOLATION_10M = 0.12
_ANCHOR_MAX_NO_DET_RATIO = 0.55
_ANCHOR_MAX_BAD_WIDTH_RATIO = 0.55


def _float_value(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _latest_run_dir(runs_dir: str = _RUNS_DIR) -> Optional[str]:
    if not os.path.isdir(runs_dir):
        return None
    candidates = []
    for name in os.listdir(runs_dir):
        path = os.path.join(runs_dir, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "summary.json")):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_telemetry(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def _load_previous_summaries(run_dir: str) -> List[Dict[str, Any]]:
    parent = os.path.dirname(os.path.abspath(run_dir))
    current = os.path.abspath(run_dir)
    current_mtime = os.path.getmtime(current) if os.path.exists(current) else None
    summaries: List[Dict[str, Any]] = []
    if not os.path.isdir(parent):
        return summaries

    for name in os.listdir(parent):
        path = os.path.abspath(os.path.join(parent, name))
        if path == current or not os.path.isdir(path):
            continue
        if current_mtime is not None and os.path.getmtime(path) >= current_mtime:
            continue
        summary_path = os.path.join(path, "summary.json")
        if not os.path.exists(summary_path):
            continue
        try:
            summary = _load_json(summary_path)
        except (OSError, ValueError):
            continue
        summary["_run_dir"] = path
        summaries.append(summary)

    summaries.sort(key=lambda item: os.path.getmtime(str(item.get("_run_dir") or "")))
    return summaries


def _is_progress_anchor(summary: Dict[str, Any]) -> bool:
    duration_s = _float_value(summary.get("duration_s"), 0.0) or 0.0
    total_distance_m = _float_value(summary.get("total_distance_m"), 0.0) or 0.0
    mean_offset = _float_value(summary.get("mean_abs_offset_m"), 999.0) or 999.0
    p95_offset = _float_value(summary.get("p95_abs_offset_m"), 999.0) or 999.0
    violation_08m = _float_value(summary.get("lane_violation_ratio_08m"), 0.0) or 0.0
    violation_10m = _float_value(summary.get("lane_violation_ratio_10m"), 0.0) or 0.0
    no_det_ratio = _float_value(summary.get("no_detect_ratio"), 1.0) or 1.0
    bad_width_ratio = _float_value(summary.get("bad_width_ratio"), 1.0) or 1.0
    return (
        duration_s >= _ANCHOR_MIN_DURATION_S
        and total_distance_m >= _ANCHOR_MIN_DISTANCE_M
        and mean_offset <= _ANCHOR_MAX_MEAN_OFFSET_M
        and p95_offset <= _ANCHOR_MAX_P95_OFFSET_M
        and violation_08m <= _ANCHOR_MAX_VIOLATION_08M
        and violation_10m <= _ANCHOR_MAX_VIOLATION_10M
        and no_det_ratio <= _ANCHOR_MAX_NO_DET_RATIO
        and bad_width_ratio <= _ANCHOR_MAX_BAD_WIDTH_RATIO
    )


def _ui_params_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    tune = dict(config.get("tune_params") or {})
    target_kmh = _float_value(config.get("target_kmh"), 15.0) or 15.0
    return {
        "lc_target_kmh": target_kmh,
        "lc_tune_speed": _float_value(tune.get("target_kmh"), target_kmh) or target_kmh,
        "lc_kp": _float_value(tune.get("kp"), 0.5) or 0.5,
        "lc_kd": _float_value(tune.get("kd"), 0.1) or 0.1,
        "lc_ema": _float_value(tune.get("ema_alpha"), 0.3) or 0.3,
        "lc_steer_rate": _float_value(tune.get("steer_rate"), 0.15) or 0.15,
        "lc_offset_clip": _float_value(tune.get("offset_clip"), 1.5) or 1.5,
        "lc_bev_top_crop": _int_value(tune.get("bev_top_crop"), 80),
        "lc_min_blob": _int_value(tune.get("min_blob_area"), 50),
        "lc_shadow_filter": _int_value(tune.get("shadow_filter_strength"), 0),
        "lc_preprocess_mode": str(tune.get("preprocess_mode") or "legacy"),
        "lc_search_ratio": _float_value(tune.get("search_ratio"), 0.5) or 0.5,
        "lc_min_pixels": _int_value(tune.get("min_pixels"), 30),
    }


def _best_progress_anchor(previous: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [item for item in previous if _is_progress_anchor(item)]
    if not candidates:
        return None

    def _rank(item: Dict[str, Any]) -> Tuple[float, float, float]:
        return (
            _float_value(item.get("total_distance_m"), 0.0) or 0.0,
            _float_value(item.get("duration_s"), 0.0) or 0.0,
            -(_float_value(item.get("lane_violation_ratio_08m"), 999.0) or 999.0),
        )

    best = max(candidates, key=_rank)
    run_dir = str(best.get("_run_dir") or "")
    config_path = os.path.join(run_dir, "run_config.json")
    if not os.path.exists(config_path):
        return None
    try:
        params = _ui_params_from_config(_load_json(config_path))
    except (OSError, ValueError):
        return None
    return {
        "run_dir": run_dir,
        "summary": best,
        "params": params,
    }


def _apply_progress_anchor_limits(
    suggestion: Dict[str, Any],
    anchor: Dict[str, Any],
    notes: List[str],
    strict: bool = False,
) -> None:
    params = dict(anchor.get("params") or {})
    if not params:
        return

    if strict:
        for key in (
            "lc_kp",
            "lc_kd",
            "lc_ema",
            "lc_steer_rate",
            "lc_bev_top_crop",
            "lc_min_blob",
            "lc_shadow_filter",
            "lc_preprocess_mode",
            "lc_search_ratio",
            "lc_min_pixels",
        ):
            suggestion[key] = params[key]
        notes.append(
            "Run regressed after a long-progress setup; reverting core params to that anchor."
        )
        return

    suggestion["lc_kp"] = _clamp(
        float(suggestion["lc_kp"]),
        float(params["lc_kp"]) - 0.10,
        float(params["lc_kp"]) + 0.05,
    )
    suggestion["lc_kd"] = _clamp(
        float(suggestion["lc_kd"]),
        float(params["lc_kd"]) - 0.04,
        float(params["lc_kd"]) + 0.03,
    )
    suggestion["lc_steer_rate"] = _clamp(
        float(suggestion["lc_steer_rate"]),
        float(params["lc_steer_rate"]) - 0.05,
        float(params["lc_steer_rate"]) + 0.02,
    )
    suggestion["lc_ema"] = _clamp(
        float(suggestion["lc_ema"]),
        float(params["lc_ema"]) - 0.05,
        float(params["lc_ema"]) + 0.05,
    )
    suggestion["lc_search_ratio"] = _clamp(
        float(suggestion["lc_search_ratio"]),
        float(params["lc_search_ratio"]) - 0.05,
        float(params["lc_search_ratio"]) + 0.05,
    )
    suggestion["lc_bev_top_crop"] = int(_clamp(
        float(suggestion["lc_bev_top_crop"]),
        float(params["lc_bev_top_crop"]) - 20,
        float(params["lc_bev_top_crop"]) + 20,
    ))
    suggestion["lc_min_blob"] = int(_clamp(
        float(suggestion["lc_min_blob"]),
        float(params["lc_min_blob"]) - 10,
        float(params["lc_min_blob"]) + 20,
    ))
    suggestion["lc_shadow_filter"] = int(_clamp(
        float(suggestion["lc_shadow_filter"]),
        max(0.0, float(params["lc_shadow_filter"]) - 20),
        float(params["lc_shadow_filter"]) + 20,
    ))
    suggestion["lc_min_pixels"] = int(_clamp(
        float(suggestion["lc_min_pixels"]),
        max(10.0, float(params["lc_min_pixels"])),
        float(params["lc_min_pixels"]) + 10,
    ))
    notes.append(
        "Previous long-progress run is used as an anchor; limiting next params near that setup."
    )


def _telemetry_stats(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    speeds = [_float_value(row.get("speed_kmh"), 0.0) or 0.0 for row in rows]
    throttles = [_float_value(row.get("throttle"), 0.0) or 0.0 for row in rows]
    brakes = [_float_value(row.get("brake"), 0.0) or 0.0 for row in rows]
    ready_rows = [row for row in rows if row.get("ready") == "True"]
    ready_count = len(ready_rows)
    return {
        "max_speed_kmh": max(speeds) if speeds else 0.0,
        "mean_speed_kmh": sum(speeds) / len(speeds) if speeds else 0.0,
        "max_throttle": max(throttles) if throttles else 0.0,
        "mean_throttle": sum(throttles) / len(throttles) if throttles else 0.0,
        "brake_ratio": (
            sum(1 for brake in brakes if brake > 0.0) / len(brakes)
            if brakes
            else 0.0
        ),
        "ready_ratio": ready_count / len(rows) if rows else 0.0,
    }


def _telemetry_lane_quality(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    offsets = [_float_value(row.get("smooth_offset_m")) for row in rows]
    quality = lane_quality_from_offsets(offsets)
    return {
        "lane_violation_ratio_08m": quality.lane_violation_ratio_08m,
        "lane_violation_ratio_10m": quality.lane_violation_ratio_10m,
    }


def _telemetry_binary_quality(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    white_ratios = [_float_value(row.get("binary_white_ratio")) for row in rows]
    upper_shares = [_float_value(row.get("binary_upper_white_share")) for row in rows]
    shadow_scores = [_float_value(row.get("shadow_boundary_score")) for row in rows]
    quality = binary_quality_from_samples(white_ratios, upper_shares, shadow_scores)
    return {
        "binary_white_ratio_p95": quality.p95_white_ratio or 0.0,
        "binary_upper_white_share_p95": quality.p95_upper_white_share or 0.0,
        "shadow_boundary_score_p95": quality.p95_shadow_boundary_score or 0.0,
        "binary_noisy_frame_ratio": quality.noisy_frame_ratio,
    }


def analyze_latest_run(runs_dir: str = _RUNS_DIR) -> Tuple[Optional[str], Dict[str, Any]]:
    run_dir = _latest_run_dir(runs_dir)
    if run_dir is None:
        return None, {"error": "No Lane Control run found."}
    return run_dir, analyze_run(run_dir)


def analyze_run(run_dir: str) -> Dict[str, Any]:
    summary = _load_json(os.path.join(run_dir, "summary.json"))
    config = _load_json(os.path.join(run_dir, "run_config.json"))
    telemetry = _load_telemetry(os.path.join(run_dir, "telemetry.csv"))
    stats = _telemetry_stats(telemetry)
    lane_quality = _telemetry_lane_quality(telemetry)
    binary_quality = _telemetry_binary_quality(telemetry)

    tune = dict(config.get("tune_params") or {})
    target_kmh = _float_value(config.get("target_kmh"), 15.0) or 15.0
    suggestion = {
        "lc_target_kmh": target_kmh,
        "lc_tune_speed": _float_value(tune.get("target_kmh"), target_kmh) or target_kmh,
        "lc_kp": _float_value(tune.get("kp"), 0.5) or 0.5,
        "lc_kd": _float_value(tune.get("kd"), 0.1) or 0.1,
        "lc_ema": _float_value(tune.get("ema_alpha"), 0.3) or 0.3,
        "lc_steer_rate": _float_value(tune.get("steer_rate"), 0.15) or 0.15,
        "lc_offset_clip": _float_value(tune.get("offset_clip"), 1.5) or 1.5,
        "lc_bev_top_crop": _int_value(tune.get("bev_top_crop"), 80),
        "lc_min_blob": _int_value(tune.get("min_blob_area"), 50),
        "lc_shadow_filter": _int_value(tune.get("shadow_filter_strength"), 0),
        "lc_preprocess_mode": str(tune.get("preprocess_mode") or "legacy"),
        "lc_search_ratio": _float_value(tune.get("search_ratio"), 0.5) or 0.5,
        "lc_min_pixels": _int_value(tune.get("min_pixels"), 30),
    }
    notes: List[str] = []

    max_speed = stats["max_speed_kmh"]
    max_throttle = stats["max_throttle"]
    ready_ratio = stats["ready_ratio"]
    frame_count = max(1, int(summary.get("frame_count") or len(telemetry) or 1))
    status_counts = dict(summary.get("status_counts") or {})
    wait_ratio = (
        sum(int(v) for k, v in status_counts.items() if str(k).startswith("WAIT"))
        / frame_count
    )
    no_det_ratio = _float_value(summary.get("no_detect_ratio"), 0.0) or 0.0
    bad_width_ratio = _float_value(summary.get("bad_width_ratio"), 0.0) or 0.0
    p95_offset = _float_value(summary.get("p95_abs_offset_m"), 0.0) or 0.0
    binary_white_p95 = (
        _float_value(summary.get("binary_white_ratio_p95"))
        if summary.get("binary_white_ratio_p95") is not None
        else binary_quality["binary_white_ratio_p95"]
    ) or 0.0
    binary_upper_p95 = (
        _float_value(summary.get("binary_upper_white_share_p95"))
        if summary.get("binary_upper_white_share_p95") is not None
        else binary_quality["binary_upper_white_share_p95"]
    ) or 0.0
    shadow_boundary_p95 = (
        _float_value(summary.get("shadow_boundary_score_p95"))
        if summary.get("shadow_boundary_score_p95") is not None
        else binary_quality["shadow_boundary_score_p95"]
    ) or 0.0
    binary_noisy_ratio = (
        _float_value(summary.get("binary_noisy_frame_ratio"))
        if summary.get("binary_noisy_frame_ratio") is not None
        else binary_quality["binary_noisy_frame_ratio"]
    ) or 0.0
    shadow_noise_high = shadow_boundary_p95 > 0.025
    binary_noise_high = (
        binary_noisy_ratio > 0.30
        or binary_white_p95 > 0.10
        or binary_upper_p95 > 0.70
        or shadow_noise_high
    )
    violation_08m = (
        _float_value(summary.get("lane_violation_ratio_08m"))
        if summary.get("lane_violation_ratio_08m") is not None
        else lane_quality["lane_violation_ratio_08m"]
    ) or 0.0
    violation_10m = (
        _float_value(summary.get("lane_violation_ratio_10m"))
        if summary.get("lane_violation_ratio_10m") is not None
        else lane_quality["lane_violation_ratio_10m"]
    ) or 0.0
    steer_delta = _float_value(summary.get("steer_delta_rms"), 0.0) or 0.0
    duration_s = _float_value(summary.get("duration_s"), 0.0) or 0.0
    valid_drive_time_s = _float_value(summary.get("valid_drive_time_s"), 0.0) or 0.0
    valid_drive_ratio = valid_drive_time_s / duration_s if duration_s > 0.0 else 0.0
    score = _float_value(summary.get("score"))
    previous = _load_previous_summaries(run_dir)
    progress_anchor = _best_progress_anchor(previous)
    previous_scores = [
        float(value)
        for value in (_float_value(item.get("score")) for item in previous)
        if value is not None
    ]
    previous_valid_times = [
        float(value)
        for value in (_float_value(item.get("valid_drive_time_s")) for item in previous)
        if value is not None
    ]
    best_previous_score = min(previous_scores) if previous_scores else None
    best_previous_valid_time = max(previous_valid_times) if previous_valid_times else None
    no_launch = ready_ratio > 0.5 and max_speed < 0.5
    overfiltered_no_ready = (
        wait_ratio > 0.80
        and valid_drive_time_s < 1.0
        and max_speed < 0.5
        and binary_white_p95 < 0.025
        and binary_noisy_ratio < 0.05
    )
    long_progress_run = _is_progress_anchor(summary)
    stop_reason = str(summary.get("stop_reason") or "")
    preserve_progress_controller = long_progress_run and stop_reason == "stuck"
    unstable_lane_run = (
        not long_progress_run
        and max_speed >= 2.0
        and valid_drive_time_s >= 3.0
        and (
            (duration_s < 25.0 and (p95_offset > 0.85 or violation_08m > 0.12))
            or p95_offset > 1.15
            or violation_10m > 0.08
        )
    )
    protect_detection_envelope = long_progress_run or progress_anchor is not None
    regressed_after_anchor = (
        progress_anchor is not None
        and not long_progress_run
        and (
            stop_reason in {"out_of_lane", "lane_lost"}
            or p95_offset > 1.0
            or violation_08m > 0.10
            or violation_10m > 0.03
        )
    )

    if no_launch:
        suggestion["lc_target_kmh"] = max(float(suggestion["lc_target_kmh"]), 15.0)
        suggestion["lc_tune_speed"] = max(float(suggestion["lc_tune_speed"]), 15.0)
        notes.append(
            "Vehicle was ready but did not launch; raising target speed to restore launch throttle."
        )
        if max_throttle < 0.4:
            notes.append(
                "Max throttle stayed below 0.40; speed PI needs launch support in a later change."
            )

    if overfiltered_no_ready:
        suggestion["lc_bev_top_crop"] = max(80, int(suggestion["lc_bev_top_crop"]) - 40)
        suggestion["lc_min_blob"] = max(30, int(suggestion["lc_min_blob"]) - 40)
        suggestion["lc_shadow_filter"] = max(0, int(suggestion["lc_shadow_filter"]) - 20)
        suggestion["lc_search_ratio"] = _clamp(float(suggestion["lc_search_ratio"]) + 0.15, 0.30, 0.80)
        suggestion["lc_min_pixels"] = max(15, int(suggestion["lc_min_pixels"]) - 10)
        notes.append("WAIT-only run with low binary signal; relaxing filters to recover launch.")

    if unstable_lane_run:
        suggestion["lc_target_kmh"] = min(float(suggestion["lc_target_kmh"]), 12.0)
        suggestion["lc_tune_speed"] = min(float(suggestion["lc_tune_speed"]), 12.0)
        suggestion["lc_kp"] = _clamp(float(suggestion["lc_kp"]) - 0.15, 0.55, 0.95)
        suggestion["lc_kd"] = _clamp(float(suggestion["lc_kd"]) - 0.04, 0.08, 0.18)
        suggestion["lc_ema"] = _clamp(max(float(suggestion["lc_ema"]), 0.25), 0.05, 1.0)
        suggestion["lc_steer_rate"] = _clamp(float(suggestion["lc_steer_rate"]) - 0.05, 0.12, 0.24)
        notes.append("Unstable lane run; reducing speed and steering aggressiveness.")
        if binary_noisy_ratio < 0.10 and binary_white_p95 < 0.04:
            suggestion["lc_bev_top_crop"] = max(100, int(suggestion["lc_bev_top_crop"]) - 20)
            suggestion["lc_min_blob"] = max(50, int(suggestion["lc_min_blob"]) - 20)
            suggestion["lc_shadow_filter"] = max(0, int(suggestion["lc_shadow_filter"]) - 20)
            notes.append("Unstable run with low noise; relaxing filters to recover lane signal.")

    if binary_noise_high and not overfiltered_no_ready and not regressed_after_anchor:
        suggestion["lc_bev_top_crop"] = min(180, int(suggestion["lc_bev_top_crop"]) + 20)
        suggestion["lc_min_blob"] = min(300, int(suggestion["lc_min_blob"]) + 20)
        suggestion["lc_search_ratio"] = _clamp(float(suggestion["lc_search_ratio"]) - 0.05, 0.30, 0.90)
        notes.append("Binary noise is high; cropping top noise and raising Min Blob.")

    if shadow_noise_high and not overfiltered_no_ready and not regressed_after_anchor:
        suggestion["lc_shadow_filter"] = min(100, int(suggestion["lc_shadow_filter"]) + 20)
        notes.append("Shadow boundary noise is high; increasing Shadow Filter.")

    if no_det_ratio > 0.15:
        if overfiltered_no_ready:
            pass
        elif regressed_after_anchor:
            pass
        elif protect_detection_envelope and not binary_noise_high:
            notes.append("NO_DET is high, but a long-progress setup exists; preserving search envelope.")
        elif binary_noise_high:
            suggestion["lc_min_pixels"] = min(80, int(suggestion["lc_min_pixels"]) + 5)
            notes.append("NO_DET with noisy input; keeping search tighter and raising Min Pix.")
        else:
            suggestion["lc_search_ratio"] = _clamp(float(suggestion["lc_search_ratio"]) + 0.10, 0.10, 0.90)
            suggestion["lc_min_pixels"] = max(10, int(suggestion["lc_min_pixels"]) - 5)
            notes.append("NO_DET is high; widening search and lowering Min Pix.")
    elif no_det_ratio > 0.08:
        if overfiltered_no_ready:
            pass
        elif regressed_after_anchor:
            pass
        elif protect_detection_envelope and not binary_noise_high:
            notes.append("NO_DET is moderate, but a long-progress setup exists; preserving search envelope.")
        elif binary_noise_high:
            suggestion["lc_min_pixels"] = min(80, int(suggestion["lc_min_pixels"]) + 3)
            notes.append("NO_DET is moderate with noisy input; filtering more before widening search.")
        else:
            suggestion["lc_search_ratio"] = _clamp(float(suggestion["lc_search_ratio"]) + 0.05, 0.10, 0.90)
            notes.append("NO_DET is moderate; widening search slightly.")

    if bad_width_ratio > 0.12:
        if regressed_after_anchor:
            pass
        elif long_progress_run:
            notes.append("BAD_W is high, but this run made long progress; keeping lane filters near current values.")
        elif progress_anchor is not None and not binary_noise_high:
            notes.append("BAD_W is high, but preserving previous long-progress lane filter values.")
        else:
            suggestion["lc_min_pixels"] = max(10, int(suggestion["lc_min_pixels"]) - 5)
            suggestion["lc_min_blob"] = max(20, int(suggestion["lc_min_blob"]) - 10)
            notes.append("BAD_W is high; relaxing lane pixel/blob filters.")

    if preserve_progress_controller and (p95_offset > 1.0 or violation_08m > 0.10):
        notes.append("Long-progress run ended stuck; preserving controller gains and focusing on perception.")
    elif p95_offset > 1.0 and not unstable_lane_run and not regressed_after_anchor:
        suggestion["lc_kp"] = _clamp(float(suggestion["lc_kp"]) + 0.10, 0.0, 1.20)
        suggestion["lc_steer_rate"] = _clamp(float(suggestion["lc_steer_rate"]) + 0.03, 0.01, 0.35)
        notes.append("Offset tail is high; increasing steering response.")
    elif p95_offset > 0.75 and max_speed >= 0.5 and not unstable_lane_run and not regressed_after_anchor:
        suggestion["lc_kp"] = _clamp(float(suggestion["lc_kp"]) + 0.05, 0.0, 1.20)
        notes.append("Offset is still high; increasing Kp slightly.")

    if violation_10m > 0.10 and not unstable_lane_run and not regressed_after_anchor:
        suggestion["lc_kp"] = _clamp(float(suggestion["lc_kp"]) + 0.08, 0.0, 1.20)
        suggestion["lc_kd"] = _clamp(float(suggestion["lc_kd"]) + 0.03, 0.0, 0.50)
        suggestion["lc_steer_rate"] = _clamp(float(suggestion["lc_steer_rate"]) + 0.02, 0.01, 0.35)
        notes.append("Lane violation is high; strengthening centering and damping.")
    elif violation_08m > 0.20 and not unstable_lane_run and not regressed_after_anchor:
        suggestion["lc_kd"] = _clamp(float(suggestion["lc_kd"]) + 0.02, 0.0, 0.50)
        suggestion["lc_ema"] = _clamp(float(suggestion["lc_ema"]) - 0.03, 0.05, 1.0)
        notes.append("Lane violation is moderate; adding damping before speed-up.")

    if steer_delta > 0.12 and not regressed_after_anchor:
        if unstable_lane_run:
            suggestion["lc_kd"] = _clamp(float(suggestion["lc_kd"]) - 0.03, 0.08, 0.18)
            suggestion["lc_steer_rate"] = _clamp(float(suggestion["lc_steer_rate"]) - 0.03, 0.12, 0.24)
            suggestion["lc_ema"] = _clamp(max(float(suggestion["lc_ema"]), 0.25), 0.05, 1.0)
            notes.append("Steer changes are noisy on unstable run; reducing derivative/rate response.")
        else:
            suggestion["lc_kd"] = _clamp(float(suggestion["lc_kd"]) + 0.03, 0.0, 0.50)
            suggestion["lc_ema"] = _clamp(float(suggestion["lc_ema"]) - 0.05, 0.05, 1.0)
            notes.append("Steer changes are noisy; adding damping and smoothing.")

    speed_ready = (
        not no_launch
        and duration_s >= 30.0
        and valid_drive_ratio >= 0.70
        and no_det_ratio <= 0.15
        and bad_width_ratio <= 0.12
        and not binary_noise_high
        and p95_offset <= 1.05
        and violation_08m <= 0.20
        and violation_10m <= 0.08
        and steer_delta <= 0.13
        and max_speed >= target_kmh * 0.60
    )
    stable_run = (
        speed_ready
        and valid_drive_ratio >= 0.75
        and no_det_ratio <= 0.10
        and bad_width_ratio <= 0.10
        and p95_offset <= 0.75
        and violation_08m <= 0.10
        and violation_10m <= 0.03
        and steer_delta <= 0.12
        and max_speed >= target_kmh * 0.65
    )
    improved_run = False
    if speed_ready and score is not None:
        if best_previous_score is None or score <= best_previous_score * 0.95:
            improved_run = True
        elif (
            best_previous_valid_time is not None
            and valid_drive_time_s >= best_previous_valid_time + 5.0
            and (best_previous_score is None or score <= best_previous_score * 1.05)
        ):
            improved_run = True

    if stable_run or improved_run:
        next_speed = min(
            _MAX_AUTO_TARGET_KMH,
            max(float(suggestion["lc_target_kmh"]), float(suggestion["lc_tune_speed"]))
            + _STABLE_SPEED_STEP_KMH,
        )
        suggestion["lc_target_kmh"] = next_speed
        suggestion["lc_tune_speed"] = next_speed
        if stable_run:
            notes.append("Stable run detected; increasing target speed by 2 km/h.")
        else:
            notes.append("Improved run detected; increasing target speed by 2 km/h.")

    if progress_anchor is not None and not no_launch and not overfiltered_no_ready:
        _apply_progress_anchor_limits(suggestion, progress_anchor, notes, strict=regressed_after_anchor)
        if regressed_after_anchor and binary_upper_p95 > 0.60:
            anchor_params = dict(progress_anchor.get("params") or {})
            anchor_shadow = int(anchor_params.get("lc_shadow_filter", suggestion["lc_shadow_filter"]))
            suggestion["lc_shadow_filter"] = min(80, anchor_shadow + 20)
            notes.append(
                "Upper binary noise remains high after regression; raising only Shadow Filter above anchor."
            )

    suggestion["lc_target_kmh"] = round(float(suggestion["lc_target_kmh"]), 1)
    suggestion["lc_tune_speed"] = round(float(suggestion["lc_tune_speed"]), 1)
    for key in ("lc_kp", "lc_kd", "lc_ema", "lc_steer_rate", "lc_offset_clip", "lc_search_ratio"):
        suggestion[key] = round(float(suggestion[key]), 3)

    result = {
        "run_dir": run_dir,
        "score": summary.get("score"),
        "summary": summary,
        "telemetry_stats": stats,
        "derived_metrics": {
            "lane_violation_ratio_08m": violation_08m,
            "lane_violation_ratio_10m": violation_10m,
            "binary_white_ratio_p95": binary_white_p95,
            "binary_upper_white_share_p95": binary_upper_p95,
            "shadow_boundary_score_p95": shadow_boundary_p95,
            "binary_noisy_frame_ratio": binary_noisy_ratio,
        },
        "suggestion": suggestion,
        "notes": notes or ["No major automatic adjustment found; keeping current parameters."],
    }
    with open(os.path.join(run_dir, "suggestion.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    return result
