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

from molit8_parser_pvd import FileLogger, Packet, PayloadV2


class PvdCsvLoggerTests(unittest.TestCase):
    def test_writes_parsed_and_display_data(self) -> None:
        packet = Packet(
            total_size=50,
            type=2,
            count=1,
            payloads=[
                PayloadV2(
                    id="Car_42",
                    timestamp=123456789,
                    key_type=3,
                    lat=37.1234567,
                    lon=126.7654321,
                    alt=15.75,
                    speed=12.25,
                    heading=91,
                    vehicle_class=2,
                )
            ],
        )

        with tempfile.TemporaryDirectory() as directory:
            logger = FileLogger(directory=directory)
            logger.write_packet(packet)
            path = logger.path
            logger.close()

            with path.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][10:12], ["", "Display Data"])
        self.assertEqual(rows[1][12:], rows[1][1:2] + rows[1][3:10])


if __name__ == "__main__":
    unittest.main()
