from __future__ import annotations

from pathlib import Path
import re
import struct
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from receivers.camera_sensor_receiver import CameraSensorReceiver, draw_bbox_overlays


class BBoxVisualizerTests(unittest.TestCase):
    def test_2d_and_3d_templates_parse_and_draw(self) -> None:
        cases = (
            ("Camera 2D Bounding Box.tmpl", "drawn_2d"),
            ("Camera 3D Bounding Box.tmpl", "drawn_3d"),
        )
        for template_name, drawn_key in cases:
            with self.subTest(template=template_name):
                path = ROOT / "templates" / "camera" / template_name
                receiver = CameraSensorReceiver(tmpl_path=str(path))
                self.assertIsNone(receiver._parser.fields_segment)
                packet = receiver._parse_payload(self._make_payload(receiver))

                self.assertIsNotNone(packet)
                self.assertEqual(packet["image_size"], 0)
                self.assertEqual(packet["object_count"], 1)
                self.assertEqual(packet["objects"][0]["annotation"], "ground.car")

                overlay, stats = draw_bbox_overlays(packet["frame"], packet["objects"])
                self.assertEqual(stats[drawn_key], 1)
                self.assertTrue((overlay != packet["frame"]).any())

    def test_combined_template_parses_image_and_draws_both_boxes(self) -> None:
        path = ROOT / "templates" / "camera" / "Camera With 2D_3D Bounding Box.tmpl"
        receiver = CameraSensorReceiver(tmpl_path=str(path))
        image = np.full((48, 64, 3), 80, dtype=np.uint8)
        encoded, jpeg = cv2.imencode(".jpg", image)
        self.assertTrue(encoded)

        image_bytes = jpeg.tobytes()
        payload = struct.pack("<i", len(image_bytes)) + image_bytes + self._make_payload(receiver)
        packet = receiver._parse_payload(payload)

        self.assertIsNotNone(packet)
        self.assertEqual(packet["frame"].shape[:2], image.shape[:2])
        self.assertEqual(packet["image_size"], len(image_bytes))
        self.assertEqual(packet["object_count"], 1)

        _overlay, stats = draw_bbox_overlays(packet["frame"], packet["objects"])
        self.assertEqual(stats["drawn_2d"], 1)
        self.assertEqual(stats["drawn_3d"], 1)

    @staticmethod
    def _make_payload(receiver: CameraSensorReceiver) -> bytes:
        segment = receiver._parser.repeat_segment
        values = []
        projected = (
            (400.0, 300.0), (700.0, 300.0), (700.0, 600.0), (400.0, 600.0),
            (450.0, 250.0), (750.0, 250.0), (750.0, 550.0), (450.0, 550.0),
        )
        box_2d = {
            "bounding_box_2d.min.x": 400.0,
            "bounding_box_2d.min.y": 250.0,
            "bounding_box_2d.max.x": 750.0,
            "bounding_box_2d.max.y": 600.0,
        }
        for field in segment.fields:
            if field.is_string:
                values.append(b"ground.car".ljust(field.length, b"\x00"))
                continue
            if field.variable_name in box_2d:
                values.append(box_2d[field.variable_name])
                continue
            match = re.search(r"projected_corner_points_(\d+)\.([xy])$", field.variable_name)
            if match:
                point = projected[int(match.group(1)) - 1]
                values.append(point[0] if match.group(2) == "x" else point[1])
                continue
            values.append(0.0)
        return struct.pack(segment.build_fmt(), *values)


if __name__ == "__main__":
    unittest.main()
