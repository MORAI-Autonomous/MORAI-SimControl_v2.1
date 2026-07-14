from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class LaneQualityMetrics:
    mean_abs_offset_m: Optional[float]
    p95_abs_offset_m: Optional[float]
    lane_violation_ratio_08m: float
    lane_violation_ratio_10m: float


@dataclass(frozen=True)
class BinaryQualityMetrics:
    mean_white_ratio: Optional[float]
    p95_white_ratio: Optional[float]
    mean_upper_white_share: Optional[float]
    p95_upper_white_share: Optional[float]
    mean_shadow_boundary_score: Optional[float]
    p95_shadow_boundary_score: Optional[float]
    noisy_frame_ratio: float


def lane_quality_from_offsets(offsets_m: Iterable[Optional[float]]) -> LaneQualityMetrics:
    values = [abs(float(value)) for value in offsets_m if value is not None]
    if not values:
        return LaneQualityMetrics(
            mean_abs_offset_m=None,
            p95_abs_offset_m=None,
            lane_violation_ratio_08m=0.0,
            lane_violation_ratio_10m=0.0,
        )

    ordered = sorted(values)
    return LaneQualityMetrics(
        mean_abs_offset_m=sum(values) / len(values),
        p95_abs_offset_m=_percentile(ordered, 0.95),
        lane_violation_ratio_08m=_ratio_above(values, 0.8),
        lane_violation_ratio_10m=_ratio_above(values, 1.0),
    )


def binary_quality_from_samples(
    white_ratios: Iterable[Optional[float]],
    upper_white_shares: Iterable[Optional[float]],
    shadow_boundary_scores: Iterable[Optional[float]] = (),
    white_ratio_threshold: float = 0.08,
    upper_share_threshold: float = 0.65,
    shadow_boundary_threshold: float = 0.025,
) -> BinaryQualityMetrics:
    white_values = [float(value) for value in white_ratios if value is not None]
    upper_values = [float(value) for value in upper_white_shares if value is not None]
    shadow_values = [float(value) for value in shadow_boundary_scores if value is not None]
    noisy_flags = []
    max_len = max(len(white_values), len(upper_values), len(shadow_values))
    for i in range(max_len):
        white_ratio = white_values[i] if i < len(white_values) else 0.0
        upper_share = upper_values[i] if i < len(upper_values) else 0.0
        shadow_score = shadow_values[i] if i < len(shadow_values) else 0.0
        noisy_flags.append(
            white_ratio > white_ratio_threshold
            or upper_share > upper_share_threshold
            or shadow_score > shadow_boundary_threshold
        )

    return BinaryQualityMetrics(
        mean_white_ratio=_mean(white_values),
        p95_white_ratio=_percentile(sorted(white_values), 0.95),
        mean_upper_white_share=_mean(upper_values),
        p95_upper_white_share=_percentile(sorted(upper_values), 0.95),
        mean_shadow_boundary_score=_mean(shadow_values),
        p95_shadow_boundary_score=_percentile(sorted(shadow_values), 0.95),
        noisy_frame_ratio=(
            sum(1 for flag in noisy_flags if flag) / len(noisy_flags)
            if noisy_flags
            else 0.0
        ),
    )


def _mean(values: list) -> Optional[float]:
    if not values:
        return None
    return float(sum(values) / len(values))


def _ratio_above(values: Iterable[float], threshold: float) -> float:
    values_list = list(values)
    if not values_list:
        return 0.0
    return sum(1 for value in values_list if value > threshold) / len(values_list)


def _percentile(ordered_values: list, pct: float) -> Optional[float]:
    if not ordered_values:
        return None
    if len(ordered_values) == 1:
        return float(ordered_values[0])
    pos = (len(ordered_values) - 1) * pct
    lo = int(pos)
    hi = min(lo + 1, len(ordered_values) - 1)
    weight = pos - lo
    return float(ordered_values[lo] * (1.0 - weight) + ordered_values[hi] * weight)
