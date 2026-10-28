from __future__ import annotations

"""GetObjectCatalog (0x01070002) check against a running, logged-in simulator.

1. Lists every object model and prints the count per type and sub-category.
2. Checks each item: name and type set, details case matching the type.
3. Asks for vehicles only: every item must be a vehicle, and the count must match step 1.

    python tools/catalog_check.py            # summary
    python tools/catalog_check.py --dump     # every item as JSON
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402

# Which details case each type carries. SENSOR has none yet (MSVM-3048).
DETAILS_BY_TYPE = {
    "ENTITY_TYPE_VEHICLE": "vehicle",
    "ENTITY_TYPE_AERIAL_VEHICLE": "aerial_vehicle",
    "ENTITY_TYPE_ROBOT": "robot",
    "ENTITY_TYPE_PEDESTRIAN": "pedestrian",
    "ENTITY_TYPE_OBSTACLE": "obstacle",
    "ENTITY_TYPE_SENSOR": None,
}
DETAILS_CASES = {case for case in DETAILS_BY_TYPE.values() if case}


def check_item(item: dict) -> list[str]:
    problems = []
    if not item.get("name"):
        problems.append("name is empty")
    type_name = item.get("type")
    if type_name not in DETAILS_BY_TYPE:
        problems.append(f"unexpected type {type_name}")
        return problems
    cases = [case for case in DETAILS_CASES if case in item]
    expected = DETAILS_BY_TYPE[type_name]
    # A details message whose fields are all default is dropped by MessageToDict, so a missing
    # case is fine; a wrong one is not.
    if any(case != expected for case in cases):
        problems.append(f"details {cases} do not match {type_name}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--dump", action="store_true", help="print every item")
    args = ap.parse_args()

    failed = False
    with ProtoClient(args.ip, args.port) as client:
        client.load_schema()

        print("[1] GetObjectCatalog (all types)")
        try:
            objects = client.call("GetObjectCatalog").get("objects", [])
        except ProtoCallError as e:
            print(f"  FAIL {e}")
            return 1
        per_type = Counter(item.get("type") for item in objects)
        per_sub = Counter((item.get("type"), item.get("sub_category")) for item in objects)
        print(f"  {len(objects)} models")
        for type_name, count in per_type.items():
            subs = ", ".join(f"{sub}={n}" for (t, sub), n in per_sub.items() if t == type_name)
            print(f"    {type_name}: {count}  ({subs})")

        print("[2] Item checks")
        bad = 0
        for item in objects:
            for problem in check_item(item):
                bad += 1
                print(f"  FAIL {item.get('name')}: {problem}")
        print(f"  {'OK' if bad == 0 else f'{bad} problem(s)'}")
        failed |= bad > 0

        print("[3] GetObjectCatalog types=[VEHICLE]")
        vehicles = client.call("GetObjectCatalog", types=["ENTITY_TYPE_VEHICLE"]).get("objects", [])
        others = [item["name"] for item in vehicles if item.get("type") != "ENTITY_TYPE_VEHICLE"]
        expected = per_type.get("ENTITY_TYPE_VEHICLE", 0)
        ok = not others and len(vehicles) == expected
        print(f"  {'OK' if ok else 'FAIL'}  {len(vehicles)} vehicles (expected {expected})"
              + (f", not vehicles: {others}" if others else ""))
        failed |= not ok

        if args.dump:
            print(json.dumps(objects, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
