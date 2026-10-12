from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from receivers.camera_bbox_receiver import (
    CameraBBoxReceiver,
    bbox_id_label,
    draw_bbox_2d_canvas,
    draw_bbox_3d_canvas,
    packed_rgb24_to_bgr,
)

_TPL_DIR = ROOT / "templates" / "camera"
_HEADER = struct.Struct("<64sqi")
_RED = 0xFF0000
_GREEN = 0x00FF00


def _header() -> bytes:
    return _HEADER.pack(b"cam_front", 12, 345)


class CameraBBoxReceiverTests(unittest.TestCase):
    def test_2d_packet_parses_boxes_and_annotation_colors(self):
        receiver = CameraBBoxReceiver(tmpl_path=str(_TPL_DIR / "Camera Bounding Box 2D.tmpl"))
        rows = struct.pack("<ffffII", 10, 20, 110, 220, _RED, _GREEN)
        rows += struct.pack("<ffffII", 1, 2, 3, 4, 0, 0)

        packet = receiver._parse_payload(_header() + rows)

        self.assertEqual(packet["camera_id"], "cam_front")
        self.assertEqual(packet["object_count"], 2)
        first = packet["objects"][0]
        self.assertEqual(first["bounding_box_2d.max.y"], 220.0)
        self.assertEqual(first["class_id"], _RED)
        self.assertEqual(first["instance_id"], _GREEN)

    def test_3d_packet_projects_all_eight_corners(self):
        receiver = CameraBBoxReceiver(tmpl_path=str(_TPL_DIR / "Camera Bounding Box 3D.tmpl"))
        corners = []
        for z in (10.0, 14.0):
            for x, y in ((1, -1), (1, 1), (-1, 1), (-1, -1)):
                corners += [x, y, z]
        row = struct.pack("<24fII", *corners, _RED, 0)

        packet = receiver._parse_payload(_header() + row)
        canvas, drawn = draw_bbox_3d_canvas(packet["objects"])

        self.assertEqual(packet["object_count"], 1)
        self.assertEqual(drawn, 1)
        self.assertTrue(canvas.any())

    def test_3d_box_with_corner_behind_camera_is_skipped(self):
        obj = {}
        for i in range(1, 9):
            prefix = f"bounding_box_3D8_points.corner_points_{i}"
            obj[f"{prefix}.x"] = 1.0
            obj[f"{prefix}.y"] = 1.0
            obj[f"{prefix}.z"] = -2.0 if i == 5 else 10.0

        _canvas, drawn = draw_bbox_3d_canvas([obj])

        self.assertEqual(drawn, 0)

    def test_2d_canvas_skips_degenerate_boxes(self):
        good = {"bounding_box_2d.min.x": 0.0, "bounding_box_2d.min.y": 0.0,
                "bounding_box_2d.max.x": 50.0, "bounding_box_2d.max.y": 50.0, "class_id": _RED}
        flat = dict(good, **{"bounding_box_2d.max.x": 0.0})

        _canvas, drawn = draw_bbox_2d_canvas([good, flat])

        self.assertEqual(drawn, 1)

    def test_label_shows_24bit_semantic_and_instance_codes(self):
        self.assertEqual(bbox_id_label({"class_id": 10485760, "instance_id": 15269888}),
                         "S:A00000 I:E90000")

    def test_label_leads_with_subclass_name_from_tagging_rule(self):
        from receivers.camera_bbox_receiver import bbox_label

        self.assertEqual(bbox_label({"class_id": 0xA00000, "instance_id": 0xE90000}),
                         "Car\nS:A00000\nI:E90000")
        self.assertEqual(bbox_label({"class_id": 0x010203, "instance_id": 0}).split("\n")[0], "Unknown")

    def test_code_to_subclass_accepts_int_and_hex_text(self):
        from utils.tagging_rule import code_to_subclass, code_to_tag

        self.assertEqual(code_to_subclass(0xA00000), "Car")
        self.assertEqual(code_to_subclass("#A00000"), "Car")
        self.assertEqual(code_to_subclass(0x101010), "Paved")
        self.assertEqual(code_to_tag(0x101010), "road_automobile_paved")
        self.assertIsNone(code_to_subclass(0x010203))
        self.assertEqual(code_to_subclass(0x010203, default="?"), "?")

    def test_labels_of_stacked_boxes_do_not_overlap(self):
        import numpy as np
        from receivers.camera_bbox_receiver import _put_label

        canvas = np.zeros((480, 640, 3), dtype=np.uint8)
        placed = []
        for _ in range(3):
            _put_label(canvas, "Car\nS:A00000\nI:E90000", 100, 150, placed)

        for i, (ax, ay, aw, ah) in enumerate(placed):
            for bx, by, bw, bh in placed[i + 1:]:
                self.assertTrue(ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)

    def test_packed_color_is_rgb_to_bgr(self):
        self.assertEqual(packed_rgb24_to_bgr(0x112233), (0x33, 0x22, 0x11))
        self.assertEqual(packed_rgb24_to_bgr(0), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
