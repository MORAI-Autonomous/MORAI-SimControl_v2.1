from __future__ import annotations

import argparse
import sys
from typing import Dict, Optional, Sequence

from demo import DemoSession, DemoSessionError, ScenarioStatus
from demo.batch_config import DEFAULT_CONFIG_PATH, load_config


_SCENARIO_STATE_NAMES: Dict[int, str] = {
    1: "PLAY",
    2: "PAUSE",
    3: "STOP",
    4: "COMPLETED",
}

_COMMAND_HELP = """
Scenario controls
  play, p       Play scenario
  pause, a      Pause scenario
  stop, s       Stop scenario
  previous, b   Select previous scenario
  next, n       Select next scenario
  status, i     Get current scenario status
  help, h       Show this help
  quit, q       Close the session
""".strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load a MORAI suite and control its scenarios.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Configuration JSON path (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser
def _format_status(status: ScenarioStatus) -> str:
    state = _SCENARIO_STATE_NAMES.get(status.state, f"UNKNOWN({status.state})")
    return state if not status.name else f"{state} ({status.name})"


def _print_status_notification(status: ScenarioStatus) -> None:
    print(f"\n[STATUS] {_format_status(status)}")


def _execute_command(session: DemoSession, command: str, scenario_name: str) -> bool:
    normalized = command.strip().lower()
    if normalized in ("quit", "q", "exit"):
        return False
    if normalized in ("help", "h", "?"):
        print(_COMMAND_HELP)
        return True
    if normalized in ("status", "i"):
        print(f"[STATUS] {_format_status(session.get_scenario_status())}")
        return True

    actions = {
        "play": session.play,
        "p": session.play,
        "pause": session.pause,
        "a": session.pause,
        "stop": session.stop,
        "s": session.stop,
        "previous": session.previous,
        "prev": session.previous,
        "b": session.previous,
        "next": session.next,
        "n": session.next,
    }
    action = actions.get(normalized)
    if action is None:
        print(f"[WARN] Unknown command: {command!r}. Enter 'help' to see commands.")
        return True

    action(scenario_name)
    print(f"[OK] {normalized} command accepted")
    return True


def run_interactive(session: DemoSession, scenario_name: str) -> None:
    print()
    print(_COMMAND_HELP)
    print()
    while session.is_connected:
        try:
            command = input("scenario> ")
        except EOFError:
            break
        try:
            if not _execute_command(session, command, scenario_name):
                break
        except DemoSessionError as exc:
            print(f"[ERROR] {exc}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if not config.suite_path:
        print(
            f"[ERROR] Set 'suite_path' in {args.config} before using the CLI.",
            file=sys.stderr,
        )
        return 2

    session = DemoSession(
        host=config.host,
        port=config.port,
        request_timeout=config.request_timeout,
        connect_timeout=config.connect_timeout,
    )
    session.add_scenario_status_listener(_print_status_notification)

    try:
        print(f"[INFO] Connecting to MORAI at {config.host}:{config.port}...")
        session.connect()
        print("[OK] Connected")
        print(f"[INFO] Loading suite: {config.suite_path}")
        session.load_suite(config.suite_path, timeout=config.load_timeout)
        print("[OK] Suite loaded")
        if config.scenario_name:
            print(f"[INFO] Scenario: {config.scenario_name}")
        run_interactive(session, config.scenario_name)
        return 0
    except (DemoSessionError, OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted")
        return 130
    finally:
        session.close()
        print("[INFO] Disconnected")


if __name__ == "__main__":
    raise SystemExit(main())
