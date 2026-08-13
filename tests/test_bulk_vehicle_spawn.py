from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.bulk_vehicle_spawn import build_spawn_poses, load_csv_path


class BulkVehicleSpawnTests(unittest.TestCase):
    def test_samples_path_at_requested_spacing(self) -> None:
        points = [(0.0, 0.0, 1.0), (20.0, 0.0, 1.0)]
        poses = build_spawn_poses(points, count=3, spacing=8.0, lane_offset=4.0)
        self.assertEqual(poses, [
            (0.0, 0.0, 1.0, 0.0),
            (8.0, 0.0, 1.0, 0.0),
            (16.0, 0.0, 1.0, 0.0),
        ])

    def test_moves_next_lap_to_parallel_lane(self) -> None:
        points = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
        poses = build_spawn_poses(points, count=3, spacing=6.0, lane_offset=4.0)
        self.assertEqual(poses[2], (2.0, 4.0, 0.0, 0.0))

    def test_loads_supported_map_csv_files(self) -> None:
        map_dir = SRC / "autonomous_driving" / "config" / "map"
        for map_name in ("Sangam_Track", "Virtual_TestBed_ 01"):
            with self.subTest(map_name=map_name):
                points = load_csv_path(map_dir / map_name / "path_link.csv")
                self.assertGreater(len(points), 100)
                self.assertEqual(len(points[0]), 3)


if __name__ == "__main__":
    unittest.main()
