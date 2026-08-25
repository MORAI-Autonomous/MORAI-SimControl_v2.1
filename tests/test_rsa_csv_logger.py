from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UDP_DEBUG_DIR = ROOT / "tools" / "udp_debug"
if str(UDP_DEBUG_DIR) not in sys.path:
    sys.path.insert(0, str(UDP_DEBUG_DIR))

from molit8_parser_rsa import FileLogger, Packet, Payload


class RsaCsvLoggerTests(unittest.TestCase):
    def test_writes_one_row_per_parsed_payload(self) -> None:
        packet = Packet(
            total_size=45,
            type=1,
            count=1,
            payloads=[
                Payload(
                    timestamp=123456789,
                    region_id=10,
                    vehicle_id=42,
                    key_type=3,
                    speed=12.25,
                    heading=91.5,
                    lat=37.1234567,
                    lon=126.7654321,
                    alt=15.75,
                    vehicle_class=2,
                )
            ],
        )

        with tempfile.TemporaryDirectory() as directory:
            logger = FileLogger(mode="csv", directory=directory)
            logger.write_packet(packet, ("127.0.0.1", 16002))
            path = logger.path
            logger.close()

            with path.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0],
            [
                "recv_time_iso",
                "timestamp",
                "region_id",
                "vehicle_id",
                "key_type",
                "speed",
                "heading",
                "lat",
                "lon",
                "alt",
                "vehicle_class",
                "",
                "Display Data",
                "vehicle_id",
                "key_type",
                "speed",
                "heading",
                "lat",
                "lon",
                "alt",
                "vehicle_class",
            ],
        )
        self.assertEqual(rows[1][3:11], [
            "42", "3", "12.25", "91.5", "37.1234567", "126.7654321", "15.75", "2",
        ])
        self.assertEqual(rows[1][11:13], ["", "Display Data"])
        self.assertEqual(rows[1][13:], rows[1][3:11])


if __name__ == "__main__":
    unittest.main()
