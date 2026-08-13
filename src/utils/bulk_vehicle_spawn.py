from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import List, Sequence, Tuple


PathPoint = Tuple[float, float, float]
SpawnPose = Tuple[float, float, float, float]


def load_csv_path(file_path: Path) -> List[PathPoint]:
    points: List[PathPoint] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            points.append((
                float(row["x"]),
                float(row["y"]),
                float(row.get("z") or 0.0),
            ))
    if len(points) < 2:
        raise ValueError("path CSV must contain at least two points")
    return points


def build_spawn_poses(
    points: Sequence[PathPoint],
    count: int,
    spacing: float = 8.0,
    lane_offset: float = 4.0,
) -> List[SpawnPose]:
    """Sample poses along a path, moving later laps to parallel lanes.

    The returned tuple is (x, y, z, yaw_degrees). The final-to-first gap is
    deliberately excluded: reaching the CSV end starts a new offset lane at
    the first point instead of placing vehicles across an unknown map area.
    """
    if count < 1:
        return []
    if len(points) < 2:
        raise ValueError("at least two path points are required")
    if spacing <= 0.0:
        raise ValueError("spacing must be positive")

    segments = []
    total_length = 0.0
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            continue
        segments.append((total_length, total_length + length, start, end, dx, dy, length))
        total_length += length
    if not segments:
        raise ValueError("path CSV does not contain a usable segment")

    poses: List[SpawnPose] = []
    segment_index = 0
    for vehicle_index in range(count):
        distance = vehicle_index * spacing
        lap_index = int(distance // total_length)
        path_distance = distance % total_length

        if path_distance < segments[segment_index][0]:
            segment_index = 0
        while (segment_index + 1 < len(segments)
               and path_distance > segments[segment_index][1]):
            segment_index += 1

        start_distance, _, start, end, dx, dy, length = segments[segment_index]
        ratio = (path_distance - start_distance) / length
        base_x = start[0] + dx * ratio
        base_y = start[1] + dy * ratio
        base_z = start[2] + (end[2] - start[2]) * ratio

        offset = lap_index * lane_offset
        normal_x = -dy / length
        normal_y = dx / length
        yaw = math.degrees(math.atan2(dy, dx))
        poses.append((
            base_x + normal_x * offset,
            base_y + normal_y * offset,
            base_z,
            yaw,
        ))
    return poses
