from __future__ import annotations

"""Time mode API (0x01020001-3) check against a running, logged-in simulator with a scenario open.

Reads the setting; checks the target_rtf presets and the refusals of SetTimeMode (OUT_OF_RANGE, BUSY
while running) and of
StepSimulation (NOT_RUNNING, WRONG_MODE, OUT_OF_RANGE); runs FIXED with client stepping and checks
that each StepSimulation answer moves step_index and sim_time by exactly the steps asked for.
The setting ends as it was; the scenario is started and stopped twice.

    python tools/time_mode_check.py
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


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")


def seconds(stamp: Optional[dict]) -> float:
    # MessageToDict writes 64-bit integers as strings.
    stamp = stamp or {}
    return int(stamp.get("seconds", 0)) + int(stamp.get("nanos", 0)) / 1e9


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--fps", type=int, default=50, help="target_fps for the client-stepping run")
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        control = lambda a: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{a}"))
        set_mode = lambda c: (lambda: client.call("SetTimeMode", config=c))
        do_step = lambda n: (lambda: client.call("StepSimulation", step_count=n))

        print("[1] Read")
        got = step("GetTimeMode", lambda: client.call("GetTimeMode"))
        original = (got or {}).get("config", {})

        print("[2] Set while stopped")
        step("SetTimeMode (same setting)", set_mode(original))
        step("SetTimeMode target_fps 5", set_mode(dict(original, target_fps=5)), "OUT_OF_RANGE")
        step("SetTimeMode physics_delta_time_ms 0", set_mode(dict(original, physics_delta_time_ms=0)), "OUT_OF_RANGE")
        step("SetTimeMode mode UNSPECIFIED", set_mode(dict(original, mode="TIME_MODE_UNSPECIFIED")), "OUT_OF_RANGE")
        fixed = {"mode": "TIME_MODE_FIXED", "target_fps": 50, "physics_delta_time_ms": 10}
        for rtf in (0, 1, 2, 4, 8):
            got_rtf = (step(f"SetTimeMode FIXED target_rtf {rtf}", set_mode(dict(fixed, target_rtf=rtf))) or {}) \
                .get("config", {}).get("target_rtf", 0)  # proto3 leaves 0 out
            # Until MSVM-3077 every factor above 1 is stored, and read back, as unlimited (0).
            check(f"target_rtf {rtf} reads back as {0 if rtf != 1 else 1}", got_rtf == (0 if rtf != 1 else 1),
                  f"got {got_rtf}")
        for rtf in (0.25, 0.5, 3, 20):
            step(f"SetTimeMode FIXED target_rtf {rtf}", set_mode(dict(fixed, target_rtf=rtf)), "OUT_OF_RANGE")
        step("target_rtf 3 ignored with client_stepping",
             set_mode(dict(fixed, target_rtf=3, client_stepping=True)))
        step("StepSimulation while stopped", do_step(1), "NOT_RUNNING")

        print(f"[3] FIXED with client stepping, {args.fps} fps")
        stepping = {"mode": "TIME_MODE_FIXED", "target_fps": args.fps,
                    "physics_delta_time_ms": max(5, 1000 // args.fps // 2), "client_stepping": True}
        set_resp = step("SetTimeMode FIXED client_stepping", set_mode(stepping))
        check("answer has client_stepping", bool((set_resp or {}).get("config", {}).get("client_stepping")))
        step("SetScenarioMode PLAY", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY"))
        step("ControlScenario START", control("START"))
        step("SetTimeMode while running", set_mode(stepping), "BUSY")
        first = step("StepSimulation 1", do_step(1)) or {}
        tenth = step("StepSimulation 10", do_step(10)) or {}
        moved = int(tenth.get("step_index", 0)) - int(first.get("step_index", 0))
        check("step_index moved by 10", moved == 10, f"moved {moved}")
        sim_moved = seconds(tenth.get("sim_time")) - seconds(first.get("sim_time"))
        check(f"sim_time moved by 10 / {args.fps} s", abs(sim_moved - 10 / args.fps) < 1e-6, f"moved {sim_moved:.6f} s")
        state = (step("GetTimeMode while running", lambda: client.call("GetTimeMode")) or {}).get("state", {})
        check("state.step_index matches the last answer", state.get("step_index") == tenth.get("step_index"),
              f"{state.get('step_index')} vs {tenth.get('step_index')}")
        step("StepSimulation 0", do_step(0), "OUT_OF_RANGE")
        step("ControlScenario STOP", control("STOP"))

        print("[4] VARIABLE")
        step("SetTimeMode VARIABLE", set_mode({"mode": "TIME_MODE_VARIABLE", "target_fps": 50, "physics_delta_time_ms": 20}))
        step("ControlScenario START", control("START"))
        step("StepSimulation in VARIABLE", do_step(1), "WRONG_MODE")
        step("ControlScenario STOP", control("STOP"))

        print("[5] Restore")
        step("SetTimeMode (original)", set_mode(original))

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
