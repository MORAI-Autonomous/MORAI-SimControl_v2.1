from __future__ import annotations

import json
import math
import struct
from typing import Dict, List, Tuple

import cv2
import numpy as np

from receivers.camera_sensor_receiver import CameraSensorReceiver, _TYPE_MAP
from utils.camera3d import focal_length
from utils.tagging_rule import code_to_subclass

# The 3D template carries camera-frame corners only, so intrinsics are assumed.
_BBOX_3D_FOV_DEG = 90.0
_MIN_CANVAS_W = 640
_MIN_CANVAS_H = 480
_NEAR_Z_M = 0.1
# The panel downsizes the canvas (~0.6x), so the label font must start large.
_LABEL_SCALE = 0.7
_EDGES_3D = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)


class CameraBBoxReceiver(CameraSensorReceiver):
    """Receives image-less `Camera Bounding Box 2D/3D` packets (FIELDS header + REPEAT rows)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._header_fmt = self._load_header_fmt()
        self._header_size = struct.calcsize(self._header_fmt)

    def _load_header_fmt(self) -> str:
        with open(self._tmpl_path, "r", encoding="utf-8") as fp:
            raw = json.load(fp)

        fmt = "<"
        for seg in raw.get("messageTemplate", {}).get("segmentList", []):
            if str(seg.get("type", "")).upper() != "FIELDS":
                continue
            for field in seg.get("fieldList", []):
                var_type = str(field.get("variableType", "FLOAT")).upper()
                if var_type == "STRING":
                    fmt += f"{int(field.get('length', 0))}s"
                elif var_type in _TYPE_MAP:
                    fmt += _TYPE_MAP[var_type][0]
                else:
                    raise ValueError(f"Unsupported header field type: {var_type}")
        return fmt

    def _parse_payload(self, payload: bytes):
        if len(payload) < self._header_size:
            self._debug(f"payload too short: {len(payload)} bytes", key="short", interval_sec=1.0)
            return None

        header = struct.unpack_from(self._header_fmt, payload, 0)
        camera_id = ""
        if header and isinstance(header[0], bytes):
            camera_id = header[0].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        rows = self._parse_repeat_rows(payload[self._header_size:])
        return {
            "camera_id": camera_id,
            "objects": rows,
            "object_count": len(rows),
            "raw_size": len(payload),
        }


def packed_rgb24_to_bgr(packed: int) -> Tuple[int, int, int]:
    """Convert a packed 0x00RRGGBB annotation color to a BGR tuple (white when unset)."""
    value = int(packed)
    if value == 0:
        return (255, 255, 255)
    return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


def bbox_id_label(obj: dict) -> str:
    """Label with the 24-bit semantic/instance segmentation color codes (hex RRGGBB)."""
    return f"S:{int(obj.get('class_id', 0)):06X} I:{int(obj.get('instance_id', 0)):06X}"


def bbox_label(obj: dict) -> str:
    """Multi-line label: semantic SubClass name (from the Tagging Rule) above the 24-bit codes."""
    subclass = code_to_subclass(obj.get("class_id", 0), default="Unknown")
    return "\n".join([subclass, *bbox_id_label(obj).split(" ")])


def _put_label(canvas: np.ndarray, text: str, x: int, y: int, placed: List[Tuple[int, int, int, int]]) -> None:
    """Draw a multi-line label ending at `y` (above the box); shift down past labels already placed."""
    lines = text.split("\n")
    sizes = [cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, _LABEL_SCALE, 1) for line in lines]
    text_w = max(size[0][0] for size in sizes)
    text_h, baseline = sizes[0][0][1], sizes[0][1]
    line_h = text_h + baseline + 2
    w, h = text_w + 6, line_h * len(lines) + 4
    x = min(max(x, 0), max(0, canvas.shape[1] - w))
    top = y - h if y - h >= 0 else y
    while any(x < px + pw and px < x + w and top < py + ph and py < top + h for px, py, pw, ph in placed):
        top += h
    top = min(top, max(0, canvas.shape[0] - h))
    placed.append((x, top, w, h))
    cv2.rectangle(canvas, (x, top), (x + w, top + h), (40, 40, 40), -1)
    for i, line in enumerate(lines):
        cv2.putText(canvas, line, (x + 3, top + (i + 1) * line_h - baseline),
                    cv2.FONT_HERSHEY_SIMPLEX, _LABEL_SCALE, (255, 255, 255), 1, cv2.LINE_AA)


def draw_bbox_2d_canvas(objects: List[dict]) -> Tuple[np.ndarray, int]:
    """Draw 2D boxes on a black canvas, colored by the semantic annotation color."""
    boxes = []
    for obj in objects:
        try:
            x0, y0, x1, y1 = (
                float(obj["bounding_box_2d.min.x"]),
                float(obj["bounding_box_2d.min.y"]),
                float(obj["bounding_box_2d.max.x"]),
                float(obj["bounding_box_2d.max.y"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
            continue
        boxes.append((obj, int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))))

    width = max([_MIN_CANVAS_W] + [b[3] + 1 for b in boxes])
    height = max([_MIN_CANVAS_H] + [b[4] + 1 for b in boxes])
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    placed: List[Tuple[int, int, int, int]] = []
    for obj, x0, y0, x1, y1 in boxes:
        color = packed_rgb24_to_bgr(obj.get("class_id", 0))
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color, 2)
        _put_label(canvas, bbox_label(obj), x0, y0 - 2, placed)
    return canvas, len(boxes)


def draw_bbox_3d_canvas(objects: List[dict]) -> Tuple[np.ndarray, int]:
    """Project camera-frame 3D corners (x right, y down, z forward) onto a black canvas."""
    canvas = np.zeros((_MIN_CANVAS_H, _MIN_CANVAS_W, 3), dtype=np.uint8)
    focal = focal_length(_BBOX_3D_FOV_DEG, _MIN_CANVAS_H)
    placed: List[Tuple[int, int, int, int]] = []
    drawn = 0
    for obj in objects:
        points: List[Tuple[int, int]] = []
        for i in range(1, 9):
            prefix = f"bounding_box_3D8_points.corner_points_{i}"
            try:
                x, y, z = (float(obj[f"{prefix}.x"]), float(obj[f"{prefix}.y"]), float(obj[f"{prefix}.z"]))
            except (KeyError, TypeError, ValueError):
                break
            # A corner behind the camera cannot be projected; skip the whole box.
            if not all(math.isfinite(v) for v in (x, y, z)) or z <= _NEAR_Z_M:
                break
            points.append((int(round(_MIN_CANVAS_W * 0.5 + focal * x / z)),
                           int(round(_MIN_CANVAS_H * 0.5 + focal * y / z))))
        else:
            color = packed_rgb24_to_bgr(obj.get("class_id", 0))
            for a, b in _EDGES_3D:
                cv2.line(canvas, points[a], points[b], color, 1, cv2.LINE_AA)
            _put_label(canvas, bbox_label(obj), min(p[0] for p in points), min(p[1] for p in points) - 2, placed)
            drawn += 1
    return canvas, drawn
