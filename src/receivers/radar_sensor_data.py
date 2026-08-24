from __future__ import annotations

import math
from typing import Any, Dict, List


def build_object_view(parsed: Dict[str, Any]) -> Dict[str, Any]:
    objects: List[Dict[str, Any]] = []
    for row in parsed.get("repeat_rows", []):
        fields = row.get("fields", {})
        objects.append({
            "object_id": _as_int(fields.get("object_id")),
            "classification_color_hash_rgba": _as_int(
                fields.get("classification_color_hash_rgba")
            ),
            "center_x_meters": _as_float(fields.get("center_x_meters")),
            "center_y_meters": _as_float(fields.get("center_y_meters")),
            "center_z_meters": _as_float(fields.get("center_z_meters")),
            "velocity_x_meters_per_second": _as_float(
                fields.get("velocity_x_meters_per_second")
            ),
            "velocity_y_meters_per_second": _as_float(
                fields.get("velocity_y_meters_per_second")
            ),
            "velocity_z_meters_per_second": _as_float(
                fields.get("velocity_z_meters_per_second")
            ),
            "acceleration_x_meters_per_second_squared": _as_float(
                fields.get("acceleration_x_meters_per_second_squared")
            ),
            "acceleration_y_meters_per_second_squared": _as_float(
                fields.get("acceleration_y_meters_per_second_squared")
            ),
            "acceleration_z_meters_per_second_squared": _as_float(
                fields.get("acceleration_z_meters_per_second_squared")
            ),
        })

    fields = parsed.get("fields", {})
    return {
        "seconds": _as_int(fields.get("seconds")),
        "nanos": _as_int(fields.get("nanos")),
        "reported_count": _as_int(fields.get("object_count")),
        "objects": objects,
        "plot_x": [item["center_x_meters"] for item in objects],
        "plot_y": [item["center_y_meters"] for item in objects],
    }


def build_detection_view(parsed: Dict[str, Any]) -> Dict[str, Any]:
    detections: List[Dict[str, Any]] = []
    for row in parsed.get("repeat_rows", []):
        fields = row.get("fields", {})
        range_meters = _as_float(fields.get("range_meters"))
        azimuth_radians = _as_float(fields.get("azimuth_radians"))
        elevation_radians = _as_float(fields.get("elevation_radians"))
        horizontal_range = range_meters * math.cos(elevation_radians)
        detections.append({
            "detection_id": _as_int(fields.get("detection_id")),
            "range_meters": range_meters,
            "azimuth_radians": azimuth_radians,
            "elevation_radians": elevation_radians,
            "doppler_velocity_meters_per_second": _as_float(
                fields.get("doppler_velocity_meters_per_second")
            ),
            "radar_cross_section_square_meters": _as_float(
                fields.get("radar_cross_section_square_meters")
            ),
            "lateral_meters": horizontal_range * math.sin(azimuth_radians),
            "forward_meters": horizontal_range * math.cos(azimuth_radians),
            "height_meters": range_meters * math.sin(elevation_radians),
        })

    fields = parsed.get("fields", {})
    return {
        "seconds": _as_int(fields.get("seconds")),
        "nanos": _as_int(fields.get("nanos")),
        "reported_count": _as_int(fields.get("detection_count")),
        "detections": detections,
        "plot_x": [item["lateral_meters"] for item in detections],
        "plot_y": [item["forward_meters"] for item in detections],
        "plot_z": [item["height_meters"] for item in detections],
    }


def format_object_list(objects: List[Dict[str, Any]]) -> str:
    if not objects:
        return "(0 objects)"

    lines = [f"({len(objects)} objects)"]
    for item in objects:
        lines.append(
            "ID {object_id:>4}  class=0x{classification_color_hash_rgba:08X}  "
            "pos=({center_x_meters:8.2f}, {center_y_meters:8.2f}, "
            "{center_z_meters:7.2f}) m  vel=({velocity_x_meters_per_second:7.2f}, "
            "{velocity_y_meters_per_second:7.2f}, "
            "{velocity_z_meters_per_second:7.2f}) m/s  "
            "acc=({acceleration_x_meters_per_second_squared:7.2f}, "
            "{acceleration_y_meters_per_second_squared:7.2f}, "
            "{acceleration_z_meters_per_second_squared:7.2f}) m/s^2".format(**item)
        )
    return "\n".join(lines)


def format_detection_list(detections: List[Dict[str, Any]]) -> str:
    if not detections:
        return "(0 detections)"

    lines = [f"({len(detections)} detections)"]
    for item in detections:
        lines.append(
            "ID {detection_id:>4}  range={range_meters:8.2f} m  "
            "az={azimuth_radians:8.4f} rad  el={elevation_radians:8.4f} rad  "
            "doppler={doppler_velocity_meters_per_second:8.2f} m/s  "
            "RCS={radar_cross_section_square_meters:8.2f} m^2".format(**item)
        )
    return "\n".join(lines)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
