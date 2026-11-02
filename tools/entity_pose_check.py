from __future__ import annotations

"""How the simulator treats the pose an entity is given (0x0104xxxx), for the API spec.

Prints what it sees rather than judging it (SEEN lines):
  [A] Editing: a vehicle created in the air and tilted - is the pose kept as given?
  [B] Editing: SetEntityTransform - does GetEntityState right after the answer show the new pose?
  [C] Playing, stopped: temporary Kinematics and Dynamics vehicles created in the air and tilted.
  [D] Running: the same vehicles after START - do they settle on the ground?
  [E] Running: SetEntityTransform on a running vehicle - where is it right after, and a second later?
The scenario is changed in memory only; nothing is saved.

    python tools/entity_pose_check.py --vehicle gv_car_hdioniq5_2023 --x 250 --y -300

Pick a free, flat spot on the map for --x/--y (map frame metres, as the property panel shows).
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


def step(label: str, call: Callable[[], dict]) -> Optional[dict]:
    global failures
    start = time.time()
    try:
        resp = call()
    except ProtoCallError as e:
        failures += 1
        print(f"  FAIL {label}: {e.reason_name} {e.message}  ({time.time() - start:.1f}s)")
        return None
    print(f"  OK   {label}  ({time.time() - start:.1f}s)")
    return resp


def transform(x: float, y: float, z: float = 0.0, roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0) -> dict:
    return {"location": {"x": x, "y": y, "z": z}, "rotation": {"x": roll, "y": pitch, "z": yaw}}


def pose(client: ProtoClient, name: str) -> str:
    try:
        s = client.call("GetEntityState", entity_id=name)
    except ProtoCallError as e:
        return f"{e.reason_name}"
    loc = s.get("transform", {}).get("location", {})
    rot = s.get("transform", {}).get("rotation", {})
    return (f"xyz ({loc.get('x', 0):.2f}, {loc.get('y', 0):.2f}, {loc.get('z', 0):.2f})"
            f"  rpy ({rot.get('x', 0):.1f}, {rot.get('y', 0):.1f}, {rot.get('z', 0):.1f})"
            f"  speed {s.get('speed_mps', 0):.2f}")


def seen(label: str, client: ProtoClient, name: str) -> None:
    print(f"  SEEN {label:<34} {name}: {pose(client, name)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--vehicle", required=True, help="vehicle model name with both driving modes")
    ap.add_argument("--x", type=float, required=True, help="free, flat spot, map x (m)")
    ap.add_argument("--y", type=float, required=True, help="free, flat spot, map y (m)")
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()
    x, y = args.x, args.y

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        mode = lambda m: (lambda: client.call("SetScenarioMode", mode=f"SCENARIO_MODE_{m}"))
        control = lambda a: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{a}"))

        print("[A] Editing: created 3 m up, roll 10, pitch 5, yaw 30")
        step("SetScenarioMode EDIT", mode("EDIT"))
        step("CreateEntity pose_edit", lambda: client.call(
            "CreateEntity", entity_id="pose_edit", model_name=args.vehicle,
            initial_transform=transform(x, y, 3.0, 10.0, 5.0, 30.0)))
        seen("right after the answer", client, "pose_edit")
        time.sleep(1.0)
        seen("1 s later", client, "pose_edit")

        print("[B] Editing: SetEntityTransform to x+5, z 0, level, yaw 90")
        step("SetEntityTransform pose_edit", lambda: client.call(
            "SetEntityTransform", entity_id="pose_edit", transform=transform(x + 5, y, 0.0, 0.0, 0.0, 90.0)))
        seen("right after the answer", client, "pose_edit")
        time.sleep(0.5)
        seen("0.5 s later", client, "pose_edit")
        step("DeleteEntity pose_edit", lambda: client.call("DeleteEntity", entity_id="pose_edit"))

        print("[C] Playing, stopped: created 3 m up, roll 10, pitch 5, yaw 30")
        step("SetScenarioMode PLAY", mode("PLAY"))
        step("CreateEntity pose_kin (KINEMATICS)", lambda: client.call(
            "CreateEntity", entity_id="pose_kin", model_name=args.vehicle,
            initial_transform=transform(x, y + 10, 3.0, 10.0, 5.0, 30.0),
            vehicle_config={"driving_mode": "VEHICLE_DRIVING_MODE_KINEMATICS"}))
        step("CreateEntity pose_dyn (DYNAMICS)", lambda: client.call(
            "CreateEntity", entity_id="pose_dyn", model_name=args.vehicle,
            initial_transform=transform(x, y + 20, 3.0, 10.0, 5.0, 30.0),
            vehicle_config={"driving_mode": "VEHICLE_DRIVING_MODE_DYNAMICS"}))
        seen("right after the answer", client, "pose_kin")
        seen("right after the answer", client, "pose_dyn")
        time.sleep(2.0)
        seen("2 s later, stopped", client, "pose_kin")
        seen("2 s later, stopped", client, "pose_dyn")

        print("[D] Running")
        step("ControlScenario START", control("START"))
        seen("right after START", client, "pose_kin")
        seen("right after START", client, "pose_dyn")
        time.sleep(3.0)
        seen("3 s after START", client, "pose_kin")
        seen("3 s after START", client, "pose_dyn")

        print("[E] Running: SetEntityTransform to y+30, z 0, level, yaw 0")
        step("SetEntityTransform pose_kin", lambda: client.call(
            "SetEntityTransform", entity_id="pose_kin", transform=transform(x, y + 30, 0.0, 0.0, 0.0, 0.0)))
        seen("right after the answer", client, "pose_kin")
        time.sleep(1.0)
        seen("1 s later", client, "pose_kin")

        step("ControlScenario STOP", control("STOP"))
        names = [e.get("entity_id") for e in client.call("ListEntities").get("entities", [])]
        print(f"  SEEN after STOP, pose_kin/pose_dyn listed: {'pose_kin' in names}/{'pose_dyn' in names}")

    print(f"{'all calls OK' if failures == 0 else f'{failures} call(s) failed'} - read the SEEN lines")
    print("The scenario now holds the edits in memory; reopen the suite to discard them.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
