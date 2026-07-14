from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class FrameLabel:
    """One timestamp-aligned camera/control sample."""

    frame_index: int
    timestamp_s: float
    image_path: str
    speed_kmh: float
    steer: float
    throttle: float
    brake: float
    offset_m: Optional[float] = None
    lane_detected: bool = False
    status: str = ""
    scenario: str = ""


@dataclass(frozen=True)
class RunRecord:
    """Metadata for one recorded simulator run."""

    run_dir: str
    config_path: str
    summary_path: str
    telemetry_path: str
    video_path: Optional[str] = None
    frames_dir: Optional[str] = None
    labels_path: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetRecord:
    """A dataset index entry built from one frame label."""

    dataset_name: str
    split: str
    run_dir: str
    label: FrameLabel

