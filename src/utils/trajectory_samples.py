from __future__ import annotations

from typing import Tuple

TrajectoryPoint = Tuple[float, float, float, float]
TrajectorySample = Tuple[str, Tuple[TrajectoryPoint, ...]]

TRAJECTORY_FOLLOW_MODE_ITEMS = (
    (1, "POSITION"),
    (2, "FOLLOW"),
)

TRAJECTORY_SAMPLES: Tuple[TrajectorySample, ...] = (
    (
        "Route_1 Lane Change",
        (
            (237.4360, -299.4899, 0.0210, 2.0),
            (199.6393, -280.8129, 0.1524, 4.0),
        ),
    ),
    (
        "Route_1 Short Forward",
        (
            (267.5667, -299.4991, 0.0522, 2.0),
            (247.5667, -299.4991, 0.0522, 4.0),
        ),
    ),
)


def sample_names() -> list[str]:
    return [name for name, _ in TRAJECTORY_SAMPLES]


def get_sample(name: str) -> Tuple[TrajectoryPoint, ...]:
    for sample_name, points in TRAJECTORY_SAMPLES:
        if sample_name == name:
            return points
    return TRAJECTORY_SAMPLES[0][1]
