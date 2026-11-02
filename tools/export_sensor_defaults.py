from __future__ import annotations

"""Writes the default settings of every sensor model to morai-sim's
Content/JsonData/Sensor/SensorDefaults.json, which GetObjectCatalog returns as
SensorCatalogDetails.default_settings_json (MSVM-3048).

A sensor's settings come from the sensor itself, not from the data table, so each model is mounted
on a temporary vehicle in a running simulator, read back with GetEntitySettings and removed. Run it
when a sensor BP or SensorTable changes (CI warns: UtilityTools/check_sensor_defaults.py), then
commit the file.

Needs a running, logged-in simulator with a suite open; it switches to the editing mode and
removes everything it creates. The scenario is changed in memory only.

    python tools/export_sensor_defaults.py --project D:/Dev/morai-sim --vehicle gv_car_hdioniq5_2023 --x -670 --y 65

Each model also records its BP's SVN last-changed revision, so CI can tell when the file is stale.

--skip leaves models out, e.g. ones whose BP is not finished: they are not mounted, so a broken BP
cannot take the simulator down, and CI keeps warning that they are missing until they are exported.
"""

import argparse
import csv
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402

DEFAULTS_PATH = Path("Content/JsonData/Sensor/SensorDefaults.json")
SENSOR_TABLE = Path("Content/Resource/SimData/DataTables/SensorTable.csv")


def read_csv(path: Path) -> list[dict]:
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def bp_file(project: Path, bp_path: str) -> Optional[Path]:
    """/Game/3DENV/.../BP_X.BP_X_C -> <project>/Content/3DENV/.../BP_X.uasset"""
    if not bp_path.startswith("/Game/"):
        return None
    package = bp_path.split(".")[0][len("/Game/"):]
    return project / "Content" / f"{package}.uasset"


def svn_revision(path: Path) -> Optional[int]:
    try:
        out = subprocess.run(["svn", "info", "--show-item", "last-changed-revision", str(path)],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip().isdigit() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, type=Path, help="morai-sim checkout the file is written into")
    ap.add_argument("--vehicle", required=True, help="vehicle model to mount the sensors on")
    ap.add_argument("--x", type=float, required=True, help="free spot on the map, UTM x (m)")
    ap.add_argument("--y", type=float, required=True, help="free spot on the map, UTM y (m)")
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--timeout", type=float, default=310.0)
    ap.add_argument("--skip", nargs="*", default=[], help="model names to leave out (BP not finished)")
    args = ap.parse_args()

    table = {row["OptionName"]: row for row in read_csv(args.project / SENSOR_TABLE) if row.get("OptionName")}
    models: dict[str, dict] = {}
    failed: list[str] = []
    holder = "__sensor_defaults_holder"

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        catalog = client.call("GetObjectCatalog", types=["ENTITY_TYPE_SENSOR"]).get("objects", [])
        print(f"{len(catalog)} sensor models in GetObjectCatalog")
        client.call("SetScenarioMode", mode="SCENARIO_MODE_EDIT")
        client.call("CreateEntity", entity_id=holder, model_name=args.vehicle,
                    initial_transform={"location": {"x": args.x, "y": args.y, "z": 0.0}},
                    vehicle_config={"driving_mode": "VEHICLE_DRIVING_MODE_DYNAMICS"})
        try:
            for item in catalog:
                name = item["name"]
                if name in args.skip:
                    print(f"  SKIP {name}")
                    continue
                sensor = f"{holder}_sensor"
                try:
                    client.call("CreateEntity", entity_id=sensor, model_name=name,
                                sensor_config={"parent_entity_id": holder})
                    config = client.call("GetEntitySettings", entity_id=sensor).get("sensor_config", {})
                    client.call("DeleteEntity", entity_id=sensor)
                except ProtoCallError as e:
                    print(f"  FAIL {name}: {e.reason_name} {e.message}")
                    failed.append(name)
                    continue
                row = table.get(name, {})
                bp = bp_file(args.project, row.get("BpPath", ""))
                models[name] = {
                    "sensorType": item.get("sub_category", ""),
                    "bp": bp.relative_to(args.project).as_posix() if bp else "",
                    "bpRevision": svn_revision(bp) if bp else None,
                    "settings": json.loads(config["settings_json"]) if config.get("settings_json") else {},
                }
                print(f"  OK   {name}: {len(models[name]['settings'])} keys, BP r{models[name]['bpRevision']}")
        finally:
            client.call("DeleteEntity", entity_id=holder)

    out = args.project / DEFAULTS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "description": "Default settings of each sensor model (GetObjectCatalog SensorCatalogDetails). "
                       "Written by SimControl tools/export_sensor_defaults.py; do not edit by hand.",
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models": dict(sorted(models.items())),
    }
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(models)} models to {out}" + (f"; {len(failed)} failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
