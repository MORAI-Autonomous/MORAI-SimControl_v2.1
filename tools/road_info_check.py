from __future__ import annotations

"""Map API (0x0109) check against a running, logged-in simulator with a map that has road data.

Reads the lanes and junctions around a point (by default what the main camera looks at), then walks
one lane's connections and checks they agree with each other: a successor names the lane among its
predecessors, a lane change to the left lands one lane nearer the center line, a junction's entry
lanes lead into it. Refusals (range, unknown lane) are checked too.

    python tools/road_info_check.py
    python tools/road_info_check.py --x 120.5 --y -830.0 --radius 80

Point the camera at a road first (or give --x --y in the map frame).
"""

import argparse
import math
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
    print(f"  {'OK  ' if ok else 'FAIL'} {label}  ({time.time() - start:.1f}s)" + ("" if ok else f"  expected {expect_reason}"))
    return resp if resp is not None else {}


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")


def xyz(v: dict) -> tuple[float, float, float]:
    return v.get("x", 0.0), v.get("y", 0.0), v.get("z", 0.0)


def shown_lane(lane: dict) -> str:
    pts = lane.get("center_line", [])
    kph = lane.get("max_speed_mps", 0.0) * 3.6
    return (f"{lane.get('link_id')} road {lane.get('road_id', '')} lane {lane.get('lane_number', 0)} "
            f"(ego {lane.get('ego_lane', 0)})  {lane.get('length_m', 0.0):.1f} m  {kph:.0f} km/h  "
            f"{len(pts)} pts  {lane.get('distance_m', 0.0):.1f} m away  "
            f"<{len(lane.get('predecessor_ids', []))} >{len(lane.get('successor_ids', []))}  "
            f"L {lane.get('left_link_id', '') or '-'} R {lane.get('right_link_id', '') or '-'}  "
            f"J {lane.get('junction_id', '') or '-'}")


def shown_junction(j: dict) -> str:
    c = xyz(j.get("center", {}))
    return (f"{j.get('junction_id')} at ({c[0]:.1f}, {c[1]:.1f})  {j.get('distance_m', 0.0):.1f} m away  "
            f"in {len(j.get('entry_link_ids', []))} out {len(j.get('exit_link_ids', []))}  "
            f"controllers {j.get('intersection_controller_ids', [])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--x", type=float, help="map frame x (default: what the camera looks at)")
    ap.add_argument("--y", type=float, help="map frame y")
    ap.add_argument("--radius", type=float, default=50.0)
    ap.add_argument("--show", type=int, default=10, help="lanes to print")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        lane_of = lambda link_id, **kw: client.call("GetLinkConnections", link_id=link_id, **kw)

        print("[1] Where")
        if args.x is not None and args.y is not None:
            at = {"x": args.x, "y": args.y, "z": 0.0}
        else:
            v = step("GetViewpoint", lambda: client.call("GetViewpoint"))
            center = (v or {}).get("center", {})
            if not center.get("hit"):
                print("  the camera looks at nothing: point it at a road or give --x --y")
                return 1
            at = center["location"]
        print(f"  AT ({at.get('x', 0.0):.1f}, {at.get('y', 0.0):.1f})")

        print("[2] GetRoadsNearby")
        r = step(f"GetRoadsNearby radius {args.radius:g}", lambda: client.call("GetRoadsNearby", location=at, radius_m=args.radius))
        if r is None:
            return 1
        lanes, junctions = r.get("lanes", []), r.get("junctions", [])
        print(f"  {len(lanes)} lanes, {len(junctions)} junctions, truncated {r.get('truncated', False)}, partial {r.get('partial', False)}")
        for lane in lanes[:args.show]:
            print(f"  LANE {shown_lane(lane)}")
        for j in junctions:
            print(f"  JUNC {shown_junction(j)}")
        check("lanes found", len(lanes) > 0, "point at a road")
        if not lanes:
            return 1
        dists = [lane.get("distance_m", 0.0) for lane in lanes]
        check("nearest first", dists == sorted(dists))
        check("all within the radius", max(dists) <= args.radius + 0.01, f"farthest {max(dists):.1f} m")
        check("center lines have 2+ points", all(len(lane.get("center_line", [])) >= 2 for lane in lanes))
        check("lane numbers from 1", all(lane.get("lane_number", 0) >= 1 for lane in lanes),
              str(sorted({lane.get('lane_number', 0) for lane in lanes})))

        if len(lanes) > 1:
            one = step("max_lanes 1", lambda: client.call("GetRoadsNearby", location=at, radius_m=args.radius, max_lanes=1))
            if one is not None:
                check("1 lane, truncated", len(one.get("lanes", [])) == 1 and one.get("truncated", False))

        print("[3] GetLinkConnections")
        first = lanes[0]
        c = step(f"GetLinkConnections {first['link_id']}", lambda: lane_of(first["link_id"]))
        if c is not None:
            lane = c.get("lane", {})
            check("same lane", lane.get("link_id") == first["link_id"] and lane.get("road_id") == first.get("road_id"))
            check("same connections", sorted(lane.get("successor_ids", [])) == sorted(first.get("successor_ids", []))
                  and sorted(lane.get("predecessor_ids", [])) == sorted(first.get("predecessor_ids", [])))
            fine = step("simplify_tolerance_m 0.01", lambda: lane_of(first["link_id"], simplify_tolerance_m=0.01))
            if fine is not None:
                n0, n1 = len(lane.get("center_line", [])), len(fine.get("lane", {}).get("center_line", []))
                check("finer tolerance keeps as many points or more", n1 >= n0, f"{n0} -> {n1}")

        # Each lane found: its successors name it among their predecessors
        checked = 0
        for lane in lanes[:args.show]:
            for succ_id in lane.get("successor_ids", [])[:2]:
                s = step(f"successor {succ_id} of {lane['link_id']}", lambda: lane_of(succ_id))
                if s is not None:
                    check("  names it back", lane["link_id"] in s.get("lane", {}).get("predecessor_ids", []))
                    checked += 1
            if checked >= 4:
                break

        # A lane change to the left lands one lane nearer the center line, on the same road
        for lane in lanes:
            left = lane.get("left_link_id", "")
            if not left:
                continue
            l = step(f"left of {lane['link_id']}: {left}", lambda: lane_of(left))
            if l is not None:
                ll = l.get("lane", {})
                same_road = ll.get("road_id") == lane.get("road_id")
                check("  one lane nearer the center line" if same_road else "  left lane found (another road)",
                      not same_road or ll.get("lane_number", 0) == lane.get("lane_number", 0) - 1,
                      f"lane {lane.get('lane_number')} -> {ll.get('lane_number')}")
            break

        print("[4] Junctions")
        if not junctions:
            print("  none here (the map may have no junction data, or none lies this close)")
        for j in junctions[:2]:
            entries = j.get("entry_link_ids", [])
            check(f"{j['junction_id']} has entries and exits", bool(entries) and bool(j.get("exit_link_ids")))
            if entries:
                e = step(f"entry {entries[0]}", lambda: lane_of(entries[0]))
                if e is not None:
                    inside = []
                    for succ_id in e.get("lane", {}).get("successor_ids", []):
                        s = step(f"  its successor {succ_id}", lambda: lane_of(succ_id))
                        if s is not None:
                            inside.append(s.get("lane", {}).get("junction_id", ""))
                    check("  leads into the junction", j["junction_id"] in inside, str(inside))

        print("[5] Refusals")
        step("radius 301", lambda: client.call("GetRoadsNearby", location=at, radius_m=301.0), "OUT_OF_RANGE")
        step("max_lanes 201", lambda: client.call("GetRoadsNearby", location=at, max_lanes=201), "OUT_OF_RANGE")
        step("simplify_tolerance_m -1", lambda: client.call("GetRoadsNearby", location=at, simplify_tolerance_m=-1.0), "OUT_OF_RANGE")
        step("GetLinkConnections unknown", lambda: lane_of("road_check_nobody"), "LINK_NOT_FOUND")
        step("GetLinkConnections empty", lambda: client.call("GetLinkConnections"), "MISSING_FIELD")

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
