from __future__ import annotations

"""Scenario operation (0x0105xxxx) check against a running, logged-in simulator.

Opens --suite, then walks through selecting, switching modes and running:

    python tools/scenario_check.py --suite "D:/Suites/Demo/Demo.msuite"
    python tools/scenario_check.py                      # uses the suite that is already open
    python tools/scenario_check.py --suite ... --save-as "D:/Suites/DemoCopy"   # also writes a copy

Each step prints OK when the simulator answered as expected (success, or the expected failure
reason), FAIL otherwise. A scenario is started, paused, resumed and stopped, so pick a suite whose
first scenario is safe to run.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402

failures = 0


def step(label: str, call: Callable[[], dict], expect_reason: Optional[str] = None) -> Optional[dict]:
    """Runs one call. expect_reason: the failure reason name the call must answer with."""
    global failures
    start = time.time()
    try:
        resp = call()
    except ProtoCallError as e:
        ok = expect_reason is not None and e.reason_name == expect_reason
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {label}: {e.reason_name} {e.message}  ({time.time() - start:.1f}s)")
        return None
    ok = expect_reason is None
    failures += 0 if ok else 1
    shown = f" {resp}" if resp else ""
    print(f"  {'OK  ' if ok else 'FAIL'} {label}:{shown}  ({time.time() - start:.1f}s)"
          + ("" if ok else f"  expected {expect_reason}"))
    return resp


def print_status(client: ProtoClient) -> dict:
    status = client.call("GetScenarioStatus")
    suite = status.get("suite", {})
    print(f"  suite {suite.get('name', '-')}  path={suite.get('path', '')}")
    for project in suite.get("projects", []):
        print(f"    {project.get('name')} [{project.get('map_name', '?')}]: {project.get('scenarios', [])}")
    print(f"  selected {status.get('project_name', '-')} / {status.get('scenario_name', '-')}"
          f"  mode={status.get('mode', 'SCENARIO_MODE_UNSPECIFIED')}"
          f"  state={status.get('state', 'SCENARIO_STATE_UNSPECIFIED')}")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--suite", help=".msuite path on the simulator PC (omit to use the open suite)")
    ap.add_argument("--save-as", help="also save the suite as a new one at this absolute path (folder is created)")
    ap.add_argument("--save", action="store_true", help="also save the suite over its own file")
    ap.add_argument("--timeout", type=float, default=310.0, help="response timeout (s); server gives up at 300")
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        control = lambda action: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{action}"))
        mode = lambda m, **kw: (lambda: client.call("SetScenarioMode", mode=f"SCENARIO_MODE_{m}", **kw))

        if args.suite:
            print(f"[1] OpenSuite {args.suite} (waits until Ready)")
            step("OpenSuite", lambda: client.call("OpenSuite", path=args.suite))
            step("OpenSuite missing file", lambda: client.call("OpenSuite", path=args.suite + ".missing"),
                 "FILE_NOT_FOUND")

        print("[2] GetScenarioStatus")
        status = print_status(client)
        projects = status.get("suite", {}).get("projects", [])
        if not projects:
            print("  no suite open; pass --suite")
            return 1

        print("[3] SelectScenario")
        first = projects[0]
        step("first scenario of the first project",
             lambda: client.call("SelectScenario", project_name=first["name"]))
        step("unknown project", lambda: client.call("SelectScenario", project_name="__no_such_project__"),
             "ENTITY_NOT_FOUND")
        step("unknown scenario", lambda: client.call("SelectScenario", scenario_name="__no_such_scenario__"),
             "ENTITY_NOT_FOUND")

        print("[4] Play mode, run controls")
        step("SetScenarioMode PLAY", mode("PLAY"))
        step("PAUSE while stopped", control("PAUSE"), "NOT_RUNNING")
        step("START", control("START"))
        step("START again", control("START"), "BUSY")
        step("PAUSE", control("PAUSE"))
        step("RESUME", control("RESUME"))
        step("STOP", control("STOP"))

        print("[5] Edit mode")
        step("SetScenarioMode EDIT", mode("EDIT"))
        step("START in edit mode", control("START"), "WRONG_MODE")
        step("SetScenarioMode PLAY (keep edits)", mode("PLAY"))

        print("[6] SaveSuite")
        step("START", control("START"))
        step("SaveSuite while running", lambda: client.call("SaveSuite", path=args.save_as or ""), "BUSY")
        step("STOP", control("STOP"))
        step("SaveSuite relative path", lambda: client.call("SaveSuite", path="relative/Suite"),
             "MALFORMED_REQUEST")
        if args.save_as:
            step(f"SaveSuite as {args.save_as}", lambda: client.call("SaveSuite", path=args.save_as))
        if args.save:
            step("SaveSuite (overwrite)", lambda: client.call("SaveSuite"))

        print("[7] GetScenarioStatus")
        print_status(client)

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
