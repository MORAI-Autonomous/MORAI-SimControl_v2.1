from __future__ import annotations

"""FindPlacement (0x01090003) check against a running, logged-in simulator with a map that has road data.

Asks for places in every mode and checks they lie on the lane they name: near what the camera looks
at, in the 1st lane, from latitude and longitude, at random (the same seed gives the same place), at
the nearest junction, and with --entity from a vehicle on a road (ahead, behind, beside). Refusals
are checked too. Nothing is placed.

    python tools/placement_check.py
    python tools/placement_check.py --entity Car_1

Point the camera at a road first.
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


def xy(v: dict) -> tuple[float, float]:
    return v.get("x", 0.0), v.get("y", 0.0)


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def shown(p: dict) -> str:
    loc, rot = p.get("pose", {}).get("location", {}), p.get("pose", {}).get("rotation", {})
    return (f"({loc.get('x', 0):.1f}, {loc.get('y', 0):.1f}, {loc.get('z', 0):.2f}) yaw {rot.get('z', 0):.1f}  "
            f"{p.get('link_id')} lane {p.get('lane_number', 0)} J {p.get('junction_id', '') or '-'}  "
            f"{p.get('distance_m', 0):.1f} m away  nearest {p.get('nearest_entity_id', '') or '-'} {p.get('clearance_m', 0):.1f} m")


def off_line(client: ProtoClient, p: dict) -> tuple[float, float]:
    """How far the pose is from its lane's center line, and how far its yaw is from the lane's there."""
    lane = client.call("GetLinkConnections", link_id=p["link_id"], simplify_tolerance_m=0.01)["lane"]
    pts = [xy(q) for q in lane["center_line"]]
    at = xy(p["pose"]["location"])
    best = (float("inf"), 0.0)
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((at[0] - ax) * dx + (at[1] - ay) * dy) / l2))
        d = math.hypot(ax + dx * t - at[0], ay + dy * t - at[1])
        if d < best[0]:
            best = (d, math.degrees(math.atan2(dy, dx)))
    yaw = p["pose"].get("rotation", {}).get("z", 0.0)
    return best[0], abs((yaw - best[1] + 180.0) % 360.0 - 180.0)


def on_lane(client: ProtoClient, label: str, p: Optional[dict]) -> None:
    if p is None:
        return
    print(f"  SEEN {shown(p)}")
    d, turn = off_line(client, p)
    check(f"{label} on its lane, facing its way", d < 0.05 and turn < 1.0, f"{d:.3f} m off, {turn:.2f} deg")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--entity", help="a vehicle on a road, for relative places")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        find = lambda **mode: (lambda: client.call("FindPlacement", **mode))

        print("[1] Near what the camera looks at")
        hit = client.call("GetViewpoint").get("center", {})
        if not hit.get("hit"):
            print("  the camera looks at nothing: point it at a road")
            return 1
        at = hit["location"]
        p = step("near_point at the view's middle", find(near_point={"point": {"location": at}}))
        on_lane(client, "near_point", p)
        v = step("in_view", find(in_view={}))
        if p is not None and v is not None:
            check("in_view = near_point there", v.get("link_id") == p.get("link_id"), f"{v.get('link_id')} / {p.get('link_id')}")
        one = step("in_view lane 1", find(in_view={"lane_number": 1}))
        on_lane(client, "in_view lane 1", one)
        if one is not None:
            check("lane 1, outside junctions", one.get("lane_number") == 1 and not one.get("junction_id"),
                  f"lane {one.get('lane_number')} {one.get('junction_id', '') or 'outside'}")

        print("[2] Latitude and longitude")
        origin = client.call("GetSimulatorSummary").get("map_origin", {})
        geo = origin.get("geographic") or {}
        if geo.get("latitude") is not None:
            g = step("near_point at the map origin's latitude / longitude", find(near_point={
                "point": {"geographic": {"latitude": geo["latitude"], "longitude": geo["longitude"]}}}), None)
            m = step("near_point at the map origin (0, 0)", find(near_point={"point": {"location": {"x": 0, "y": 0, "z": 0}}}))
            if g is not None and m is not None:
                dg = dist(xy(g["pose"]["location"]), xy(m["pose"]["location"]))
                check("both give the same place", dg < 1.0, f"{dg:.2f} m apart")
        else:
            print("  map origin has no latitude / longitude: skipped")

        print("[3] Random")
        r1 = step("random seed 7", find(random={"seed": 7}))
        r2 = step("random seed 7 again", find(random={"seed": 7}))
        on_lane(client, "random", r1)
        if r1 is not None and r2 is not None:
            check("same seed, same place", r1["pose"] == r2["pose"])
            check("outside junctions", not r1.get("junction_id"))
            rd = dist(xy(r1["pose"]["location"]), xy(at))
            check("within the default 100 m of the view's middle", rd <= 100.0, f"{rd:.1f} m")

        print("[4] Nearest junction")
        j = step("near_junction", find(near_junction={"point": {"location": at}}))
        if j is not None:
            print(f"  SEEN {shown(j)}")
            jc = j.get("junction", {})
            dj = dist(xy(j["pose"]["location"]), xy(jc.get("center", {})))
            check("on a lane of that junction, near its middle",
                  bool(jc.get("junction_id")) and j.get("junction_id") == jc.get("junction_id") and dj < 5.0,
                  f"{jc.get('junction_id')} {dj:.2f} m from the middle")
            on_lane(client, "near_junction", j)

        if args.entity:
            print(f"[5] From {args.entity}")
            here = client.call("GetEntityState", entity_id=args.entity)["transform"]["location"]
            own = step("its own lane (ahead 0)", find(relative={"entity_id": args.entity}))
            on_lane(client, "own", own)
            ahead = step("10 m ahead", find(relative={"entity_id": args.entity, "ahead_m": 10}))
            on_lane(client, "ahead", ahead)
            if ahead is not None:
                d = dist(xy(here), xy(ahead["pose"]["location"]))
                check("about 10 m away (straight line, so a bend shortens it)", 7.0 < d < 10.5, f"{d:.1f} m")
                check("the entity itself not counted as nearest", ahead.get("nearest_entity_id") != args.entity)
            behind = step("10 m behind", find(relative={"entity_id": args.entity, "ahead_m": -10}))
            on_lane(client, "behind", behind)
            for side, name in ((-1, "left"), (1, "right")):
                # The 1st lane has no lane on its left (the center line); the outermost none on its right
                none_left = side < 0 and own is not None and own.get("lane_number") == 1
                b = step(f"lane on the {name}", find(relative={"entity_id": args.entity, "lane_offset": side}),
                         "PLACEMENT_NOT_FOUND" if none_left else None)
                if b is not None and b:
                    on_lane(client, name, b)
                    if own is not None:
                        check(f"{name} lane number", b.get("lane_number") == own.get("lane_number") + side,
                              f"{own.get('lane_number')} -> {b.get('lane_number')}")

        print("[6] Refusals")
        step("no mode", find(), "MISSING_FIELD")
        step("near_point without a point", find(near_point={}), "MISSING_FIELD")
        step("lane 99", find(near_point={"point": {"location": at}, "lane_number": 99}), "PLACEMENT_NOT_FOUND")
        step("random radius 301", find(random={"radius_m": 301}), "OUT_OF_RANGE")
        step("lane_offset 4", find(relative={"entity_id": args.entity or "x", "lane_offset": 4}), "OUT_OF_RANGE")
        step("relative unknown entity", find(relative={"entity_id": "placement_check_nobody"}), "ENTITY_NOT_FOUND")

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
