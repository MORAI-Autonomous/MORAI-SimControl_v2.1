from __future__ import annotations

"""Fidelity API (0x01010005-8) check against a running, logged-in simulator with a scenario open.

Reads the setting, the decision state and the overlap statistics; sends the same setting back; then
checks the refusals: a value out of range (OUT_OF_RANGE) and a change while a scenario runs (BUSY).
The setting ends as it was; the scenario is started and stopped once.

    python tools/fidelity_check.py
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        control = lambda a: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{a}"))

        print("[1] Read")
        got = step("GetFidelityConfig", lambda: client.call("GetFidelityConfig"))
        state = step("GetFidelityState", lambda: client.call("GetFidelityState"))
        step("GetOverlapStats", lambda: client.call("GetOverlapStats"))
        if state and state.get("entities"):
            first = state["entities"][0]
            print(f"  SEEN first entity keys: {sorted(first.keys())}")
            if "entity_id" not in first:
                print("  FAIL FidelityEntityState has no entity_id")
                globals()["failures"] += 1
        config = (got or {}).get("config", {})

        print("[2] Set while stopped")
        step("SetFidelityConfig (same setting)", lambda: client.call("SetFidelityConfig", config=config))
        bad = dict(config, precision_radius=10.0, release_radius=5.0)
        step("SetFidelityConfig release_radius < precision_radius", lambda: client.call("SetFidelityConfig", config=bad),
             "OUT_OF_RANGE")

        print("[3] Set while running")
        step("SetScenarioMode PLAY", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY"))
        step("ControlScenario START", control("START"))
        step("SetFidelityConfig while running", lambda: client.call("SetFidelityConfig", config=config), "BUSY")
        step("ControlScenario STOP", control("STOP"))

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
