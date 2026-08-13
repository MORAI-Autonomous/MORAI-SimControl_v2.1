from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import panels.object_control as object_control


class ObjectControlBulkDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        with object_control._bulk_request_lock:
            object_control._bulk_create_pending.clear()
            object_control._bulk_delete_pending.clear()
            object_control._bulk_created_ids.clear()
            object_control._bulk_created_ids.add("Car_1")
            object_control._bulk_delete_running = False
        object_control._bulk_create_running = False

    def tearDown(self) -> None:
        with object_control._bulk_request_lock:
            object_control._bulk_create_pending.clear()
            object_control._bulk_delete_pending.clear()
            object_control._bulk_created_ids.clear()
            object_control._bulk_delete_running = False

    @mock.patch("panels.object_control.threading.Thread")
    @mock.patch("panels.object_control.dpg.configure_item")
    @mock.patch("panels.object_control.log.append")
    def test_stale_delete_response_does_not_block_retry(
        self,
        append_log,
        _configure_item,
        thread_cls,
    ) -> None:
        with object_control._bulk_request_lock:
            object_control._bulk_delete_pending[77] = "Car_1"

        object_control._on_bulk_delete_objects()

        with object_control._bulk_request_lock:
            self.assertTrue(object_control._bulk_delete_running)
            self.assertEqual(object_control._bulk_delete_pending, {})
        thread_cls.assert_called_once()
        thread_cls.return_value.start.assert_called_once_with()
        messages = [call[0][0] for call in append_log.call_args_list]
        self.assertFalse(any("already running" in message for message in messages))
        self.assertTrue(any("stale response" in message for message in messages))

    @mock.patch("panels.object_control.threading.Thread")
    @mock.patch("panels.object_control.dpg.configure_item")
    @mock.patch("panels.object_control.log.append")
    def test_active_delete_is_still_rejected(
        self,
        append_log,
        _configure_item,
        thread_cls,
    ) -> None:
        with object_control._bulk_request_lock:
            object_control._bulk_delete_running = True

        object_control._on_bulk_delete_objects()

        thread_cls.assert_not_called()
        messages = [call[0][0] for call in append_log.call_args_list]
        self.assertTrue(any("already running" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
