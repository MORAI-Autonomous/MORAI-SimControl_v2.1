from __future__ import annotations

"""ManualControl (0x01040009) check against a running, logged-in simulator with a scenario open.

Checks the control source (VehicleConfig.control_source: a new vehicle has NONE, MANUAL is EGO
only, it cannot change while playing) and the refusals (MISSING_FIELD, OUT_OF_RANGE, NOT_RUNNING,
ENTITY_NOT_FOUND, WRONG_MODE for a kinematic vehicle and for one not driven from outside), then
drives a temporary DYNAMICS EXTERNAL_AD vehicle: throttle until it moves, steer left until it turns
left (yaw grows), brake until it stops. The vehicles are temporary (created while
playing) and gone after the stop; nothing is saved.

    python tools/manual_control_check.py --vehicle gv_car_hdioniq5_2023 --x 250 --y -300

Pick a free, straight, flat stretch of road for --x/--y (map frame metres) with room to drive about
30 m east. --other-vehicle: a vehicle of the open scenario whose control source is not EXTERNAL_AD
(e.g. an NPC driven by its agent).
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


def state(client: ProtoClient, name: str) -> dict:
    s = client.call("GetEntityState", entity_id=name)
    loc = s.get("transform", {}).get("location", {})
    rot = s.get("transform", {}).get("rotation", {})
    return {"x": loc.get("x", 0.0), "y": loc.get("y", 0.0), "yaw": rot.get("z", 0.0),
            "speed": s.get("speed_mps", 0.0)}


def shown(s: dict) -> str:
    return f"xy ({s['x']:.1f}, {s['y']:.1f})  yaw {s['yaw']:.1f}  speed {s['speed']:.2f} m/s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--vehicle", required=True, help="vehicle model name with both driving modes")
    ap.add_argument("--x", type=float, required=True, help="free road, map x (m)")
    ap.add_argument("--y", type=float, required=True, help="free road, map y (m)")
    ap.add_argument("--other-vehicle", help="scenario vehicle whose control source is not EXTERNAL_AD")
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        control = lambda a: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{a}"))
        drive = lambda name, t=0.0, b=0.0, s=0.0: (
            lambda: client.call("ManualControl", entity_id=name, throttle=t, brake=b, steering=s))

        print("[1] Refusals before a run")
        step("ManualControl without entity_id", drive(""), "MISSING_FIELD")
        step("ManualControl throttle 1.5", drive("mc_dyn", t=1.5), "OUT_OF_RANGE")
        step("ManualControl steering -2", drive("mc_dyn", s=-2.0), "OUT_OF_RANGE")
        step("SetScenarioMode PLAY", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY"))
        step("ManualControl while stopped", drive("mc_dyn", t=0.5), "NOT_RUNNING")

        print("[2] Temporary vehicles facing east, then START")
        pose = lambda dy: {"location": {"x": args.x, "y": args.y + dy}, "rotation": {"z": 0.0}}
        create = lambda name, dy, config: (lambda: client.call(
            "CreateEntity", entity_id=name, model_name=args.vehicle, initial_transform=pose(dy), vehicle_config=config))
        dyn, kin = "VEHICLE_DRIVING_MODE_DYNAMICS", "VEHICLE_DRIVING_MODE_KINEMATICS"
        ext = "VEHICLE_CONTROL_SOURCE_EXTERNAL_AD"
        step("CreateEntity MANUAL for an NPC", create("mc_manual", -20, {
            "driving_mode": dyn, "control_source": "VEHICLE_CONTROL_SOURCE_MANUAL"}), "OUT_OF_RANGE")
        step("CreateEntity mc_dyn (DYNAMICS, EXTERNAL_AD)", create("mc_dyn", 0, {"driving_mode": dyn, "control_source": ext}))
        step("CreateEntity mc_kin (KINEMATICS, EXTERNAL_AD)", create("mc_kin", 10, {"driving_mode": kin, "control_source": ext}))
        step("CreateEntity mc_none (DYNAMICS, no control source)", create("mc_none", -10, {"driving_mode": dyn}))
        step("ControlScenario START", control("START"))

        print("[3] Control source and refusals while running")
        for name, want in (("mc_dyn", ext), ("mc_none", "VEHICLE_CONTROL_SOURCE_NONE")):
            got = client.call("GetEntitySettings", entity_id=name).get("vehicle_config", {}).get("control_source")
            check(f"{name} control source", got == want, f"{got}")
        step("SetEntitySettings control source while playing", lambda: client.call(
            "SetEntitySettings", entity_id="mc_none", vehicle_config={"control_source": ext}), "WRONG_MODE")
        step("ManualControl unknown entity", drive("mc_nobody", t=0.5), "ENTITY_NOT_FOUND")
        step("ManualControl kinematic vehicle", drive("mc_kin", t=0.5), "WRONG_MODE")
        step("ManualControl vehicle with no control source", drive("mc_none", t=0.5), "WRONG_MODE")
        if args.other_vehicle:
            step(f"ManualControl {args.other_vehicle} (not EXTERNAL_AD)", drive(args.other_vehicle, t=0.5), "WRONG_MODE")

        print("[4] Drive mc_dyn")
        start = state(client, "mc_dyn")
        print(f"  SEEN start                 {shown(start)}")
        step("ManualControl throttle 0.5", drive("mc_dyn", t=0.5))
        time.sleep(3.0)
        moving = state(client, "mc_dyn")
        print(f"  SEEN after 3 s throttle    {shown(moving)}")
        check("moving after throttle", moving["speed"] > 1.0, f"{moving['speed']:.2f} m/s")

        step("ManualControl throttle 0.3, steering 0.5 (left)", drive("mc_dyn", t=0.3, s=0.5))
        time.sleep(1.5)
        turned = state(client, "mc_dyn")
        print(f"  SEEN after 1.5 s steering  {shown(turned)}")
        check("yaw grew (turned left)", turned["yaw"] - moving["yaw"] > 3.0,
              f"{moving['yaw']:.1f} -> {turned['yaw']:.1f}")

        step("ManualControl brake 1", drive("mc_dyn", b=1.0))
        time.sleep(3.0)
        stopped = state(client, "mc_dyn")
        print(f"  SEEN after 3 s brake       {shown(stopped)}")
        check("stopped after brake", stopped["speed"] < 0.5, f"{stopped['speed']:.2f} m/s")

        step("ControlScenario STOP", control("STOP"))

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
