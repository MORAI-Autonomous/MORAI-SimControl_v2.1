from __future__ import annotations

"""Vehicle settings API (SetEntitySettings / GetEntitySettings, CreateEntity vehicle_config) check
against a running, logged-in simulator with a scenario open.

Creates two vehicles in the editing mode, changes their role, driving mode and dynamics values,
checks the refusals, switches to PLAY and back to check that the settings stay with the scenario,
then deletes them. The scenario is changed in memory only; nothing is saved.

    python tools/vehicle_settings_check.py --vehicle gv_car_hdioniq5_2023 --x -670 --y 65

--vehicle must support the DYNAMICS driving mode (GetObjectCatalog driving_modes).
Pick a free spot on the map for --x/--y (UTM metres); the vehicles go 10 m apart from there.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402

failures = 0


def fail(text: str) -> None:
    global failures
    failures += 1
    print(f"  FAIL {text}")


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
    print(f"  {'OK  ' if ok else 'FAIL'} {label}  ({time.time() - start:.1f}s)"
          + ("" if ok else f"  expected {expect_reason}"))
    return resp


def transform(x: float, y: float) -> dict:
    return {"location": {"x": x, "y": y, "z": 0.0}, "rotation": {"x": 0.0, "y": 0.0, "z": 0.0}}


def settings_of(resp: Optional[dict]) -> dict:
    """The VehicleConfig of a Set/GetEntitySettings response, settings_json parsed."""
    config = dict((resp or {}).get("vehicle_config", {}))
    config["settings"] = json.loads(config["settings_json"]) if config.get("settings_json") else {}
    return config


def show(name: str, config: dict) -> None:
    s = config["settings"]
    setup, axle1 = s.get("vehicleSetup", {}), s.get("axle1", {})
    print(f"    {name}: {config.get('role')} {config.get('driving_mode')}"
          + (f" mass={setup.get('mass')} axle1.trackWidth={axle1.get('trackWidth')}" if s else " (no dynamics values)"))


def expect(label: str, actual, wanted) -> None:
    if actual != wanted:
        fail(f"{label}: {actual!r}, expected {wanted!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--vehicle", required=True, help="vehicle model with the DYNAMICS driving mode")
    ap.add_argument("--x", type=float, required=True, help="free spot on the map, UTM x (m)")
    ap.add_argument("--y", type=float, required=True, help="free spot on the map, UTM y (m)")
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        mode = lambda m: (lambda: client.call("SetScenarioMode", mode=f"SCENARIO_MODE_{m}"))
        get = lambda name: settings_of(client.call("GetEntitySettings", entity_id=name))
        set_ = lambda name, **config: (lambda: client.call("SetEntitySettings", entity_id=name, vehicle_config=config))
        create = lambda name, x, y, **config: (lambda: client.call(
            "CreateEntity", entity_id=name, model_name=args.vehicle, initial_transform=transform(x, y),
            **({"vehicle_config": config} if config else {})))

        print("[1] Editing mode: create with settings")
        step("SetScenarioMode EDIT", mode("EDIT"))
        resp = step("CreateEntity vs_a DYNAMICS, mass 1800",
                    create("vs_a", args.x, args.y, driving_mode="VEHICLE_DRIVING_MODE_DYNAMICS",
                           settings_json=json.dumps({"vehicleSetup": {"mass": 1800}})))
        created = json.loads(resp["settings_json"]) if resp and resp.get("settings_json") else {}
        expect("CreateEntity settings_json mass", created.get("vehicleSetup", {}).get("mass"), 1800)
        step("CreateEntity settings_json without DYNAMICS",
             create("vs_x", args.x, args.y + 20, settings_json=json.dumps({"vehicleSetup": {"mass": 1}})),
             "MALFORMED_REQUEST")
        step("CreateEntity unknown settings_json key",
             create("vs_x", args.x, args.y + 20, driving_mode="VEHICLE_DRIVING_MODE_DYNAMICS",
                    settings_json=json.dumps({"vehicleSetup": {"noSuchKey": 1}})),
             "MALFORMED_REQUEST")
        step("GetEntitySettings vs_x (refused creates nothing)",
             lambda: client.call("GetEntitySettings", entity_id="vs_x"), "ENTITY_NOT_FOUND")
        step("CreateEntity vs_b (no settings)", create("vs_b", args.x, args.y + 10))

        print("[2] Read and change dynamics values")
        a = get("vs_a")
        show("vs_a", a)
        expect("vs_a role", a.get("role"), "VEHICLE_ROLE_NPC")
        expect("vs_a driving_mode", a.get("driving_mode"), "VEHICLE_DRIVING_MODE_DYNAMICS")
        expect("vs_a mass", a["settings"].get("vehicleSetup", {}).get("mass"), 1800)
        track = a["settings"].get("axle1", {}).get("trackWidth", 0) + 10
        resp = step(f"SetEntitySettings vs_a axle1.trackWidth {track:.1f} (cm)",
                    set_("vs_a", settings_json=json.dumps({"axle1": {"trackWidth": track}})))
        a = settings_of(resp)
        show("vs_a", a)
        if abs(a["settings"].get("axle1", {}).get("trackWidth", 0) - track) > 0.01:
            fail("axle1.trackWidth was not applied")
        expect("vs_a mass kept", a["settings"].get("vehicleSetup", {}).get("mass"), 1800)
        step("SetEntitySettings unknown key", set_("vs_a", settings_json=json.dumps({"axle3": {"mass": 1}})),
             "MALFORMED_REQUEST")
        step("SetEntitySettings wrong type", set_("vs_a", settings_json=json.dumps({"vehicleSetup": {"mass": "heavy"}})),
             "MALFORMED_REQUEST")
        step("SetEntitySettings not JSON", set_("vs_a", settings_json="mass=1"), "MALFORMED_REQUEST")
        step("SetEntitySettings unknown entity", set_("__nobody__", driving_mode="VEHICLE_DRIVING_MODE_DYNAMICS"),
             "ENTITY_NOT_FOUND")

        print("[3] Role and driving mode")
        b = get("vs_b")
        show("vs_b", b)
        if b.get("driving_mode") == "VEHICLE_DRIVING_MODE_KINEMATICS":
            step("SetEntitySettings vs_b settings_json while KINEMATICS",
                 set_("vs_b", settings_json=json.dumps({"vehicleSetup": {"mass": 1}})), "MALFORMED_REQUEST")
        else:
            print("  skip settings_json refusal: vs_b did not start in KINEMATICS")
        a = settings_of(step("SetEntitySettings vs_a role EGO", set_("vs_a", role="VEHICLE_ROLE_EGO")))
        show("vs_a", a)
        expect("vs_a role", a.get("role"), "VEHICLE_ROLE_EGO")
        expect("vs_a driving_mode (EGO -> DYNAMICS)", a.get("driving_mode"), "VEHICLE_DRIVING_MODE_DYNAMICS")
        b = settings_of(step("SetEntitySettings vs_b role EGO + DYNAMICS + mass 1500",
                             set_("vs_b", role="VEHICLE_ROLE_EGO", driving_mode="VEHICLE_DRIVING_MODE_DYNAMICS",
                                  settings_json=json.dumps({"vehicleSetup": {"mass": 1500}}))))
        show("vs_b", b)
        expect("vs_b role", b.get("role"), "VEHICLE_ROLE_EGO")
        expect("vs_b mass", b["settings"].get("vehicleSetup", {}).get("mass"), 1500)
        a = get("vs_a")
        show("vs_a", a)
        expect("vs_a role (one EGO per scenario)", a.get("role"), "VEHICLE_ROLE_NPC")
        a = settings_of(step("SetEntitySettings vs_a back to DYNAMICS", set_("vs_a", driving_mode="VEHICLE_DRIVING_MODE_DYNAMICS")))
        show("vs_a", a)

        print("[4] Playing mode")
        step("SetScenarioMode PLAY", mode("PLAY"))
        for name, mass in (("vs_a", 1800), ("vs_b", 1500)):
            c = get(name)
            show(name, c)
            expect(f"{name} mass after the switch to PLAY", c["settings"].get("vehicleSetup", {}).get("mass"), mass)
        expect("vs_b role after the switch to PLAY", get("vs_b").get("role"), "VEHICLE_ROLE_EGO")
        step("SetEntitySettings while playing", set_("vs_a", driving_mode="VEHICLE_DRIVING_MODE_DYNAMICS"), "WRONG_MODE")
        step("CreateEntity with a role while playing",
             create("vs_p", args.x, args.y + 20, role="VEHICLE_ROLE_NPC"), "WRONG_MODE")
        resp = step("CreateEntity vs_p DYNAMICS, mass 1200 while playing",
                    create("vs_p", args.x, args.y + 20, driving_mode="VEHICLE_DRIVING_MODE_DYNAMICS",
                           settings_json=json.dumps({"vehicleSetup": {"mass": 1200}})))
        created = json.loads(resp["settings_json"]) if resp and resp.get("settings_json") else {}
        expect("vs_p mass", created.get("vehicleSetup", {}).get("mass"), 1200)
        step("DeleteEntity vs_p", lambda: client.call("DeleteEntity", entity_id="vs_p"))

        print("[5] Editing mode: settings kept, clean up")
        step("SetScenarioMode EDIT (keep edits)", mode("EDIT"))
        for name, mass in (("vs_a", 1800), ("vs_b", 1500)):
            c = get(name)
            show(name, c)
            expect(f"{name} mass after the round trip", c["settings"].get("vehicleSetup", {}).get("mass"), mass)
        for name in ("vs_a", "vs_b"):
            step(f"DeleteEntity {name}", lambda name=name: client.call("DeleteEntity", entity_id=name))

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    print("The scenario now holds the edits in memory; reopen the suite to discard them.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
