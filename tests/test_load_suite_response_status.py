from __future__ import annotations

from pathlib import Path
import sys
import unittest

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from panels.commands import _load_suite_response_status


class LoadSuiteResponseStatusTests(unittest.TestCase):
    def test_success_is_complete(self) -> None:
        text, _ = _load_suite_response_status(0, 0, 1.25)
        self.assertEqual(text, "Complete (1.2s)")

    def test_result_101_is_failed(self) -> None:
        text, _ = _load_suite_response_status(101, 0, 1.25)
        self.assertEqual(text, "Failed (101)")

    def test_detail_101_is_failed(self) -> None:
        text, _ = _load_suite_response_status(0, 101, 1.25)
        self.assertEqual(text, "Failed (101)")


if __name__ == "__main__":
    unittest.main()
