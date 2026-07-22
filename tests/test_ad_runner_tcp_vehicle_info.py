from __future__ import annotations

import threading
import unittest
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runners.ad_runner import AdRunner
from runners.step_ad_runner import StepAdRunner


class _RequestIds:
    def __init__(self, value: int) -> None:
        self.value = value

    def next(self) -> int:
        return self.value


def _tcp_runner() -> AdRunner:
    runner = AdRunner.__new__(AdRunner)
    runner._tcp_sock = object()
    runner._entity_id = "Car_1"
    runner._request_id_ref = _RequestIds(42)
    runner._lock = threading.Lock()
    runner._vi_event = threading.Event()
    runner._pending_vi_request_ids = set()
    runner._latest = None
    runner._vi_response = None
    runner._log = mock.Mock()
    return runner


class AdRunnerTcpVehicleInfoTests(unittest.TestCase):
    def test_routes_only_owned_response(self) -> None:
        runner = _tcp_runner()
        runner._pending_vi_request_ids.add(42)
        parsed = {"result_code": 0, "entity_id": "Car_1"}

        self.assertFalse(runner.handle_vehicle_info_response(41, parsed))
        self.assertTrue(runner.handle_vehicle_info_response(42, parsed))
        self.assertIs(runner._latest, parsed)
        self.assertTrue(runner._vi_event.is_set())

    def test_request_waits_for_matching_tcp_response(self) -> None:
        runner = _tcp_runner()
        parsed = {"result_code": 0, "entity_id": "Car_1"}

        def send(_sock, request_id, entity_id):
            self.assertEqual((request_id, entity_id), (42, "Car_1"))
            runner.handle_vehicle_info_response(request_id, parsed)

        with mock.patch("runners.ad_runner.tcp.send_get_vehicle_info", side_effect=send):
            self.assertIs(runner._request_vehicle_info(), parsed)

    def test_failure_response_is_not_reused_as_vehicle_state(self) -> None:
        runner = _tcp_runner()
        runner._latest = {"result_code": 0, "entity_id": "old"}

        def send(_sock, request_id, _entity_id):
            runner.handle_vehicle_info_response(
                request_id, {"result_code": 102, "detail_code": 0}
            )

        with mock.patch("runners.ad_runner.tcp.send_get_vehicle_info", side_effect=send):
            self.assertIsNone(runner._request_vehicle_info())


class StepAdRunnerTcpVehicleInfoTests(unittest.TestCase):
    def test_routes_response_to_matching_vehicle_context(self) -> None:
        runner = StepAdRunner.__new__(StepAdRunner)
        runner._tcp_vi_lock = threading.Lock()
        runner._tcp_vi_requests = {}
        runner._log = mock.Mock()
        ctx = SimpleNamespace(
            entity_id="Car_2",
            lock=threading.Lock(),
            latest=None,
            last_vi_monotonic=None,
            last_vi_timeout_log_monotonic=1.0,
            vi_event=threading.Event(),
        )
        runner._tcp_vi_requests[77] = ctx
        parsed = {"result_code": 0, "entity_id": "Car_2"}

        self.assertTrue(runner.handle_vehicle_info_response(77, parsed))
        self.assertIs(ctx.latest, parsed)
        self.assertGreaterEqual(ctx.last_vi_monotonic, time.monotonic() - 1.0)
        self.assertTrue(ctx.vi_event.is_set())
        self.assertFalse(runner.handle_vehicle_info_response(77, parsed))


if __name__ == "__main__":
    unittest.main()
