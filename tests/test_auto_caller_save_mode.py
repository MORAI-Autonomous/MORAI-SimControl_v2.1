from __future__ import annotations

from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import transport.protocol_defs as proto
from runners.auto_caller import AutoCaller


class _RequestIds:
    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


class AutoCallerSaveModeTests(unittest.TestCase):
    def test_auto_caller_sends_one_fixed_step_with_selected_save_mode(self) -> None:
        event = threading.Event()
        event.set()
        pending_pop_calls = []

        caller = AutoCaller(
            tcp_sock=object(),
            pending={},
            lock=threading.Lock(),
            request_id_ref=_RequestIds(),
            max_calls=1,
            pending_add_fn=lambda *_args: event,
            pending_pop_fn=lambda *args: pending_pop_calls.append(args),
            save_mode=proto.SAVE_MODE_FORCE,
            progress_every=0,
        )

        with mock.patch(
            "runners.auto_caller.tcp.send_fixed_step"
        ) as send_step, mock.patch(
            "runners.auto_caller.tcp.send_save_data",
            side_effect=AssertionError("SaveData must not be sent"),
        ):
            caller.run()

        send_step.assert_called_once_with(
            caller.tcp_sock,
            1,
            step_count=1,
            save_mode=proto.SAVE_MODE_FORCE,
        )
        self.assertEqual(len(pending_pop_calls), 1)

    def test_auto_caller_rejects_unknown_save_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported save mode"):
            AutoCaller(
                tcp_sock=object(),
                pending={},
                lock=threading.Lock(),
                request_id_ref=_RequestIds(),
                max_calls=1,
                pending_add_fn=lambda *_args: threading.Event(),
                pending_pop_fn=lambda *_args: None,
                save_mode=3,
            )


if __name__ == "__main__":
    unittest.main()
