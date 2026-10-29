from __future__ import annotations

"""Entity API (0x0104xxxx) check against a running, logged-in simulator with a scenario open.

Editing mode: creates entities (vehicle with a name, a duplicate name, an obstacle), moves one,
lists, inspects and deletes them, then ClearEntities. Playing mode: adds a temporary vehicle and
deletes it. The scenario is changed in memory only; nothing is saved.

    python tools/entity_check.py --vehicle gv_car_hdioniq5_2023 --obstacle <obstacle model> --x 250 --y -300

Pick a free spot on the map for --x/--y (UTM metres, as GetEntityState / the property panel show).
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


def transform(x: float, y: float, yaw: float = 0.0) -> dict:
    return {"location": {"x": x, "y": y, "z": 0.0}, "rotation": {"x": 0.0, "y": 0.0, "z": yaw}}


def print_list(client: ProtoClient) -> list[dict]:
    entities = client.call("ListEntities").get("entities", [])
    for e in entities:
        loc = e.get("transform", {}).get("location", {})
        parent = f" on {e['parent_id']}" if e.get("parent_id") else ""
        print(f"    {e.get('entity_id')} {e.get('type')} {e.get('model_name')}"
              f" ({loc.get('x', 0):.1f}, {loc.get('y', 0):.1f}) persistent={e.get('persistent', False)}{parent}")
    return entities


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--vehicle", required=True, help="vehicle model name from GetObjectCatalog")
    ap.add_argument("--obstacle", help="obstacle model name from GetObjectCatalog")
    ap.add_argument("--x", type=float, required=True, help="free spot on the map, UTM x (m)")
    ap.add_argument("--y", type=float, required=True, help="free spot on the map, UTM y (m)")
    ap.add_argument("--timeout", type=float, default=310.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        mode = lambda m: (lambda: client.call("SetScenarioMode", mode=f"SCENARIO_MODE_{m}"))

        print("[1] Editing mode: create")
        step("SetScenarioMode EDIT", mode("EDIT"))
        step("CreateEntity ego_test", lambda: client.call(
            "CreateEntity", entity_id="ego_test", model_name=args.vehicle,
            initial_transform=transform(args.x, args.y)))
        step("CreateEntity same name", lambda: client.call(
            "CreateEntity", entity_id="ego_test", model_name=args.vehicle,
            initial_transform=transform(args.x + 10, args.y)), "NAME_IN_USE")
        step("CreateEntity unknown model", lambda: client.call(
            "CreateEntity", model_name="__no_such_model__", initial_transform=transform(args.x, args.y)),
            "MODEL_NOT_FOUND")
        if args.obstacle:
            step("CreateEntity obstacle (auto name)", lambda: client.call(
                "CreateEntity", model_name=args.obstacle, initial_transform=transform(args.x + 10, args.y + 5)))

        print("[2] Move, list, state")
        step("SetEntityTransform ego_test +5 m, yaw 90", lambda: client.call(
            "SetEntityTransform", entity_id="ego_test", transform=transform(args.x + 5, args.y, 90.0)))
        time.sleep(0.5)  # the move is applied on the next frames
        print_list(client)
        step("GetEntityState ego_test", lambda: client.call("GetEntityState", entity_id="ego_test"))
        step("GetEntityState unknown", lambda: client.call("GetEntityState", entity_id="__nobody__"),
             "ENTITY_NOT_FOUND")

        print("[3] Delete")
        step("DeleteEntity ego_test", lambda: client.call("DeleteEntity", entity_id="ego_test"))
        step("DeleteEntity again", lambda: client.call("DeleteEntity", entity_id="ego_test"), "ENTITY_NOT_FOUND")

        print("[4] Playing mode: temporary vehicle")
        step("SetScenarioMode PLAY", mode("PLAY"))
        step("ClearEntities while playing", lambda: client.call("ClearEntities"), "WRONG_MODE")
        if args.obstacle:
            step("CreateEntity obstacle while playing", lambda: client.call(
                "CreateEntity", model_name=args.obstacle, initial_transform=transform(args.x, args.y)), "WRONG_MODE")
        step("CreateEntity net_test", lambda: client.call(
            "CreateEntity", entity_id="net_test", model_name=args.vehicle,
            initial_transform=transform(args.x, args.y + 10)))
        listed = print_list(client)
        # ego_test was deleted in [3]; the switch to playing must not have saved it back
        if any(e.get("entity_id") == "ego_test" for e in listed):
            print("  FAIL ego_test came back after the switch to PLAY")
            globals()["failures"] += 1
        step("DeleteEntity net_test", lambda: client.call("DeleteEntity", entity_id="net_test"))

        print("[5] Editing mode: clear")
        step("SetScenarioMode EDIT (keep edits)", mode("EDIT"))
        step("ClearEntities", lambda: client.call("ClearEntities"))
        left = print_list(client)
        if left:
            print(f"  FAIL {len(left)} entities left after ClearEntities")
            globals()["failures"] += 1

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    print("The scenario now holds the edits in memory; reopen the suite to discard them.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
