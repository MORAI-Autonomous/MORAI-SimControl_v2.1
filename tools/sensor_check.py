from __future__ import annotations

"""Sensor API check (MSVM-3048): mounting sensors on a vehicle with CreateEntity, moving them with
SetEntityTransform, and Set/GetEntitySettings with sensor_config, against a running, logged-in
simulator with a scenario open.

Mounts in the editing mode (kept in the scenario) and while playing (this run only), and checks that
a STOP while playing drops what the run changed. The scenario is changed in memory only.

    python tools/sensor_check.py --vehicle gv_car_hdioniq5_2023 --camera <camera model> [--lidar <lidar model>] --x -670 --y 65

Model names are OptionNames from GetObjectCatalog (ENTITY_TYPE_SENSOR rows).
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

ANY = "ANY"  # any failure reason
failures = 0


def fail(text: str) -> None:
    global failures
    failures += 1
    print(f"  FAIL {text}")


def step(label: str, call: Callable[[], dict], expect_reason: Optional[str] = None) -> Optional[dict]:
    """Runs one call. expect_reason: the failure reason name the call must answer with (ANY: any)."""
    global failures
    start = time.time()
    try:
        resp = call()
    except ProtoCallError as e:
        ok = expect_reason is not None and (expect_reason == ANY or e.reason_name == expect_reason)
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {label}: {e.reason_name} {e.message}  ({time.time() - start:.1f}s)")
        return None
    ok = expect_reason is None
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}  ({time.time() - start:.1f}s)" + ("" if ok else f"  expected {expect_reason}"))
    return resp


def transform(x: float, y: float, z: float = 0.0, yaw: float = 0.0) -> dict:
    return {"location": {"x": x, "y": y, "z": z}, "rotation": {"x": 0.0, "y": 0.0, "z": yaw}}


def sensor_of(resp: Optional[dict]) -> dict:
    """The SensorConfig of a Set/GetEntitySettings response, settings_json parsed."""
    config = dict((resp or {}).get("sensor_config", {}))
    config["settings"] = json.loads(config["settings_json"]) if config.get("settings_json") else {}
    return config


def mount_of(config: dict) -> tuple[float, float, float, float]:
    t = config.get("mount_transform", {})
    loc, rot = t.get("location", {}), t.get("rotation", {})
    return (loc.get("x", 0.0), loc.get("y", 0.0), loc.get("z", 0.0), rot.get("z", 0.0))


def show(name: str, config: dict, keys: tuple[str, ...]) -> None:
    x, y, z, yaw = mount_of(config)
    values = " ".join(f"{k}={config['settings'].get(k)}" for k in keys)
    print(f"    {name} on {config.get('parent_entity_id')}: mount=({x:.2f}, {y:.2f}, {z:.2f}) yaw={yaw:.1f}  {values}")


def expect(label: str, actual, wanted) -> None:
    if actual != wanted:
        fail(f"{label}: {actual!r}, expected {wanted!r}")


def expect_near(label: str, actual: float, wanted: float, tol: float = 0.01) -> None:
    if abs(actual - wanted) > tol:
        fail(f"{label}: {actual:.3f}, expected {wanted:.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--vehicle", required=True, help="vehicle model with the DYNAMICS driving mode")
    ap.add_argument("--camera", required=True, help="camera sensor model")
    ap.add_argument("--lidar", help="lidar sensor model (optional)")
    ap.add_argument("--x", type=float, required=True, help="free spot on the map, UTM x (m)")
    ap.add_argument("--y", type=float, required=True, help="free spot on the map, UTM y (m)")
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        mode = lambda m: (lambda: client.call("SetScenarioMode", mode=f"SCENARIO_MODE_{m}"))
        control = lambda a: (lambda: client.call("ControlScenario", action=f"SCENARIO_ACTION_{a}"))
        get = lambda name: sensor_of(client.call("GetEntitySettings", entity_id=name))
        mount = lambda name, model, parent, pose, settings=None: (lambda: client.call(
            "CreateEntity", entity_id=name, model_name=model, initial_transform=pose,
            sensor_config={"parent_entity_id": parent, **({"settings_json": json.dumps(settings)} if settings else {})}))
        set_ = lambda name, settings: (lambda: client.call(
            "SetEntitySettings", entity_id=name, sensor_config={"settings_json": json.dumps(settings)}))
        cam_keys = ("resolutionX", "resolutionY", "frameRate")

        print("[0] Catalog defaults (SensorDefaults.json, written by tools/export_sensor_defaults.py)")
        objects = client.call("GetObjectCatalog", types=["ENTITY_TYPE_SENSOR"]).get("objects", [])
        camera = next((o for o in objects if o.get("name") == args.camera), None)
        defaults = (camera or {}).get("sensor", {}).get("default_settings_json", "")
        if camera is None:
            fail(f"{args.camera} is not in GetObjectCatalog")
        elif not defaults:
            fail(f"{args.camera} has no default_settings_json; run tools/export_sensor_defaults.py")
        else:
            print(f"  OK   {args.camera} defaults: {len(json.loads(defaults))} keys, resolutionX={json.loads(defaults).get('resolutionX')}")
        without = [o["name"] for o in objects if not o.get("sensor", {}).get("default_settings_json")]
        print(f"    {len(objects)} sensor models, {len(without)} without defaults{': ' + ', '.join(without) if without else ''}")

        print("[1] Editing mode: mount")
        step("SetScenarioMode EDIT", mode("EDIT"))
        step("CreateEntity ss_car (DYNAMICS)", lambda: client.call(
            "CreateEntity", entity_id="ss_car", model_name=args.vehicle, initial_transform=transform(args.x, args.y),
            vehicle_config={"driving_mode": "VEHICLE_DRIVING_MODE_DYNAMICS"}))
        step("CreateEntity ss_kin (KINEMATICS)", lambda: client.call(
            "CreateEntity", entity_id="ss_kin", model_name=args.vehicle, initial_transform=transform(args.x, args.y + 10),
            vehicle_config={"driving_mode": "VEHICLE_DRIVING_MODE_KINEMATICS"}))
        step("CreateEntity ss_kcam on ss_kin (KINEMATICS)", mount("ss_kcam", args.camera, "ss_kin", transform(1.0, 0.0, 1.5)))
        resp = step("CreateEntity ss_cam on ss_car, mount (1.5, 0, 1.6), resolutionX 1280",
                    mount("ss_cam", args.camera, "ss_car", transform(1.5, 0.0, 1.6), {"resolutionX": 1280}))
        created = json.loads(resp["settings_json"]) if resp and resp.get("settings_json") else {}
        expect("CreateEntity settings_json resolutionX", created.get("resolutionX"), 1280)
        step("CreateEntity camera without a parent", lambda: client.call(
            "CreateEntity", model_name=args.camera, initial_transform=transform(args.x, args.y),
            sensor_config={}), ANY)
        step("CreateEntity camera on an unknown parent", mount("ss_x", args.camera, "__nobody__", transform(0, 0)),
             "ENTITY_NOT_FOUND")
        step("CreateEntity camera with an unknown key", mount("ss_x", args.camera, "ss_car", transform(0, 0),
                                                              {"noSuchKey": 1}), "MALFORMED_REQUEST")
        step("GetEntitySettings ss_x (refused mounts nothing)",
             lambda: client.call("GetEntitySettings", entity_id="ss_x"), "ENTITY_NOT_FOUND")
        cam = get("ss_cam")
        show("ss_cam", cam, cam_keys)
        expect("ss_cam parent", cam.get("parent_entity_id"), "ss_car")
        x, y, z, _ = mount_of(cam)
        expect_near("ss_cam mount x", x, 1.5)
        expect_near("ss_cam mount z", z, 1.6)
        if args.lidar:
            resp = step("CreateEntity ss_lidar on ss_car, mount (0, 0, 2)",
                        mount("ss_lidar", args.lidar, "ss_car", transform(0.0, 0.0, 2.0)))
            if resp:
                lidar = get("ss_lidar")
                print(f"    ss_lidar keys: {sorted(lidar['settings'])[:12]} ...")

        print("[2] Move and change")
        step("SetEntityTransform ss_cam -> mount (1.0, 0.2, 2.0), yaw 10",
             lambda: client.call("SetEntityTransform", entity_id="ss_cam", transform=transform(1.0, 0.2, 2.0, 10.0)))
        cam = get("ss_cam")
        show("ss_cam", cam, cam_keys)
        x, y, z, yaw = mount_of(cam)
        expect_near("ss_cam mount x", x, 1.0)
        expect_near("ss_cam mount y (left)", y, 0.2)
        expect_near("ss_cam mount z", z, 2.0)
        expect_near("ss_cam mount yaw", yaw, 10.0, 0.1)
        cam = sensor_of(step("SetEntitySettings ss_cam resolutionY 720", set_("ss_cam", {"resolutionY": 720})))
        show("ss_cam", cam, cam_keys)
        expect("ss_cam resolutionY", cam["settings"].get("resolutionY"), 720)
        expect("ss_cam resolutionX kept", cam["settings"].get("resolutionX"), 1280)
        step("SetEntitySettings wrong type", set_("ss_cam", {"resolutionX": "big"}), "MALFORMED_REQUEST")
        step("SetEntitySettings with mount_transform", lambda: client.call(
            "SetEntitySettings", entity_id="ss_cam",
            sensor_config={"mount_transform": transform(0, 0, 3)}), "MALFORMED_REQUEST")
        step("SetEntitySettings vehicle_config on a sensor", lambda: client.call(
            "SetEntitySettings", entity_id="ss_cam",
            vehicle_config={"driving_mode": "VEHICLE_DRIVING_MODE_DYNAMICS"}), "MALFORMED_REQUEST")

        print("[3] Playing mode: kept settings, temporary changes")
        step("SetScenarioMode PLAY", mode("PLAY"))
        cam = get("ss_cam")
        show("ss_cam", cam, cam_keys)
        expect("ss_cam resolutionX after PLAY", cam["settings"].get("resolutionX"), 1280)
        expect_near("ss_cam mount z after PLAY", mount_of(cam)[2], 2.0)
        expect("ss_kcam after PLAY", get("ss_kcam").get("parent_entity_id"), "ss_kin")
        # A KINEMATICS NPC may be held without an actor while playing; the sensor gets it one.
        resp = step("CreateEntity ss_tmp on ss_kin (KINEMATICS) while playing", mount("ss_tmp", args.camera, "ss_kin", transform(0, 0, 1.0)))
        if resp is not None:
            expect("ss_tmp persistent", resp.get("persistent", False), False)
        step("SetEntitySettings ss_cam resolutionX 800 while playing", set_("ss_cam", {"resolutionX": 800}))
        step("START", control("START"))
        step("STOP (rebuilds the scenario)", control("STOP"))
        step("GetEntitySettings ss_tmp after STOP (gone)",
             lambda: client.call("GetEntitySettings", entity_id="ss_tmp"), "ENTITY_NOT_FOUND")
        cam = get("ss_cam")
        show("ss_cam", cam, cam_keys)
        expect("ss_cam resolutionX after STOP (run change dropped)", cam["settings"].get("resolutionX"), 1280)

        print("[4] Editing mode: clean up")
        step("SetScenarioMode EDIT", mode("EDIT"))
        step("GetEntitySettings ss_tmp in EDIT (not saved)",
             lambda: client.call("GetEntitySettings", entity_id="ss_tmp"), "ENTITY_NOT_FOUND")
        cam = get("ss_cam")
        expect("ss_cam resolutionX in EDIT", cam["settings"].get("resolutionX"), 1280)
        step("DeleteEntity ss_car (sensors go with it)", lambda: client.call("DeleteEntity", entity_id="ss_car"))
        step("DeleteEntity ss_kin", lambda: client.call("DeleteEntity", entity_id="ss_kin"))
        step("GetEntitySettings ss_cam after the car is gone",
             lambda: client.call("GetEntitySettings", entity_id="ss_cam"), "ENTITY_NOT_FOUND")

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    print("The scenario now holds the edits in memory; reopen the suite to discard them.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
