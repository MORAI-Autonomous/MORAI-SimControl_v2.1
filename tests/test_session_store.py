from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from demo.session_store import clear_session, load_session, save_session


class SessionStoreTest(unittest.TestCase):
    def test_windows_dpapi_round_trip(self) -> None:
        session = {
            "email": "user@example.com",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "user_id": "user-id",
            "product_uid": "S00001",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.dat"
            save_session(session, path)

            self.assertEqual(load_session(path), session)
            self.assertNotIn(b"access-token", path.read_bytes())

            clear_session(path)
            self.assertIsNone(load_session(path))

    def test_invalid_session_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.dat"
            path.write_bytes(b"not a DPAPI payload")

            self.assertIsNone(load_session(path))


if __name__ == "__main__":
    unittest.main()
