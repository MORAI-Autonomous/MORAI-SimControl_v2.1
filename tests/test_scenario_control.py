from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import panels.commands as commands


class ScenarioControlResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        with commands._scenario_control_lock:
            commands._scenario_play_pending.clear()

    def tearDown(self) -> None:
        with commands._scenario_control_lock:
            commands._scenario_play_pending.clear()

    def test_failed_play_does_not_start_counters(self) -> None:
        commands._register_scenario_play(7, resume=False)

        with mock.patch.object(commands, "_start_elapsed_counter") as start_elapsed, \
                mock.patch.object(commands, "_start_sc_timer") as start_timer:
            commands.on_scenario_control_response(7, result_code=1, detail_code=10)

        start_elapsed.assert_not_called()
        start_timer.assert_not_called()

    def test_successful_play_starts_counters(self) -> None:
        commands._register_scenario_play(8, resume=False)

        with mock.patch.object(commands, "_start_elapsed_counter") as start_elapsed, \
                mock.patch.object(commands, "_start_sc_timer") as start_timer:
            commands.on_scenario_control_response(8, result_code=0, detail_code=0)

        start_elapsed.assert_called_once_with(resume=False)
        start_timer.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
