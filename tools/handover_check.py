from __future__ import annotations

"""Handing driving over while playing (MSVM-3083) against a running, logged-in simulator.

Uses the scenario's EGO in DYNAMICS (--ego), saved with control source EXTERNAL_AD or MANUAL. The check
plays the scenario, gets the EGO moving over the network, hands driving to MANUAL and checks the speed
is kept, then hands it back to EXTERNAL_AD and brakes. It also checks the refusals while playing and
that stopping brings back the saved control source.

    python tools/handover_check.py --ego Car_3 --npc Car_4

Start in SCENARIO_MODE_EDIT with the EGO on a free, straight road.
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
MANUAL, EXTERNAL = "VEHICLE_CONTROL_SOURCE_MANUAL", "VEHICLE_CONTROL_SOURCE_EXTERNAL_AD"


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
    print(f"  {'OK  ' if ok else 'FAIL'} {label}  ({time.time() - start:.1f}s)" + ("" if ok else f"  expected {expect_reason}"))
    return resp if resp is not None else {}


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--ego", required=True, help="the scenario's EGO in DYNAMICS")
    ap.add_argument("--npc", help="an NPC vehicle, for the refusal")
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        source_of = lambda name: client.call("GetEntitySettings", entity_id=name).get("vehicle_config", {}).get("control_source")
        speed_of = lambda name: client.call("GetEntityState", entity_id=name).get("speed_mps", 0.0)
        switch = lambda name, to: (lambda: client.call("SetEntitySettings", entity_id=name, vehicle_config={"control_source": to}))
        drive = lambda t=0.0, b=0.0: (lambda: client.call("ManualControl", entity_id=args.ego, throttle=t, brake=b, steering=0.0))
        control = lambda a: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{a}"))

        print("[1] Play")
        saved = source_of(args.ego)
        print(f"  saved control source {saved}")
        check("EGO saved as MANUAL or EXTERNAL_AD", saved in (MANUAL, EXTERNAL), str(saved))
        if client.call("GetSimulatorSummary").get("scenario_state") == "SCENARIO_STATE_PLAYING":
            print("  already running: skip START (the saved control source above may be this run's)")
        else:
            step("SetScenarioMode PLAY", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY"))
            step("ControlScenario START", control("START"))
        time.sleep(1.0)
        if source_of(args.ego) != EXTERNAL:
            step("switch to EXTERNAL_AD", switch(args.ego, EXTERNAL))

        print("[2] Network drives, then MANUAL keeps the speed")
        for _ in range(30):  # 3 s of throttle at 10 Hz
            client.call("ManualControl", entity_id=args.ego, throttle=0.5, brake=0.0, steering=0.0)
            time.sleep(0.1)
        before = speed_of(args.ego)
        r = step("switch to MANUAL", switch(args.ego, MANUAL))
        check("answer says MANUAL", (r or {}).get("vehicle_config", {}).get("control_source") == MANUAL)
        time.sleep(3.0)
        after = speed_of(args.ego)
        check("speed kept for 3 s", before > 2.0 and abs(after - before) < max(1.0, before * 0.1),
              f"{before:.2f} -> {after:.2f} m/s")
        step("ManualControl while MANUAL", drive(t=0.5), "WRONG_MODE")

        print("[3] Back to EXTERNAL_AD, the first command takes over")
        step("switch to EXTERNAL_AD", switch(args.ego, EXTERNAL))
        held = speed_of(args.ego)
        for _ in range(30):
            client.call("ManualControl", entity_id=args.ego, throttle=0.0, brake=1.0, steering=0.0)
            time.sleep(0.1)
        braked = speed_of(args.ego)
        check("braking slows it", braked < held - 1.0, f"{held:.2f} -> {braked:.2f} m/s")

        print("[4] Refusals while playing")
        step("switch to NONE", switch(args.ego, "VEHICLE_CONTROL_SOURCE_NONE"), "WRONG_MODE")
        step("role and control source together", lambda: client.call(
            "SetEntitySettings", entity_id=args.ego, vehicle_config={"role": "VEHICLE_ROLE_EGO", "control_source": MANUAL}),
            "WRONG_MODE")
        if args.npc:
            step(f"switch NPC {args.npc}", switch(args.npc, MANUAL), "WRONG_MODE")

        print("[5] Stop brings back the saved control source")
        step("ControlScenario STOP", control("STOP"))
        time.sleep(2.0)
        now = source_of(args.ego)
        check("saved control source back", now == saved, f"{now}")
        step("SetScenarioMode EDIT", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_EDIT"))

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
