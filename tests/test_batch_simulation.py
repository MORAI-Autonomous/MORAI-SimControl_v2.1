from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from batch_simulation_main import _execute_command, _format_status, build_parser
from demo import ScenarioStatus
from demo.batch_config import load_config, save_config


class BatchSimulationTests(unittest.TestCase):
    def test_missing_config_is_created_with_gui_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config" / "batch_simulation.json"
            config = load_config(str(config_path))

            self.assertTrue(config_path.is_file())
            self.assertEqual(config.suite_path, "")
            self.assertGreater(config.port, 0)
            self.assertGreater(config.load_timeout, 0)

    def test_saved_preferences_are_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "batch_simulation.json"
            default_config = load_config(str(config_path))
            expected = replace(
                default_config,
                suite_path=str(Path("C:/Demo/Customer.msuite").resolve()),
                host="127.0.0.1",
                time_mode="Fixed",
                target_fps=120,
                physics_delta_time=20,
                rtf=2,
                user_control=True,
                simulator_path="C:/MORAI/Windows/MoraiSimulator.exe",
            )
            save_config(str(config_path), expected)
            restored = load_config(str(config_path))

        self.assertEqual(restored, expected)

    def test_parser_uses_config_argument(self) -> None:
        args = build_parser().parse_args(["--config", "customer.json"])
        self.assertEqual(args.config, "customer.json")

    def test_load_config_reads_suite_scenario_and_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "batch.json"
            config_path.write_text(
                """{
  "suite_path": "Customer.msuite",
  "scenario_name": "HighwayDemo",
  "server": {"host": "127.0.0.1", "port": 20001},
  "timeouts": {"connect": 3, "request": 4, "load_suite": 90}
}""",
                encoding="utf-8",
            )
            config = load_config(str(config_path))

        self.assertEqual(config.suite_path, str((Path(temp_dir) / "Customer.msuite").resolve()))
        self.assertEqual(config.scenario_name, "HighwayDemo")
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 20001)
        self.assertEqual(config.load_timeout, 90.0)

    def test_play_command_uses_configured_scenario(self) -> None:
        session = Mock()
        should_continue = _execute_command(session, "p", "HighwayDemo")
        self.assertTrue(should_continue)
        session.play.assert_called_once_with("HighwayDemo")

    def test_quit_command_stops_loop(self) -> None:
        self.assertFalse(_execute_command(Mock(), "q", ""))

    def test_status_label_includes_scenario_name(self) -> None:
        self.assertEqual(
            _format_status(ScenarioStatus(1, "HighwayDemo")),
            "PLAY (HighwayDemo)",
        )


if __name__ == "__main__":
    unittest.main()
