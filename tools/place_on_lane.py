from __future__ import annotations

"""Places a vehicle on a lane near what the main camera looks at (Map API 0x0109 + CreateEntity).

Takes the center of the view (or --x --y) and reads the lanes around it (GetRoadsNearby). By default
the vehicle goes on the nearest lane, at the point of it nearest to the center: inside a junction too,
facing along that lane. With --lane N ("put a car in the 1st lane of what I see") it takes the nearest
lane N outside junctions instead.

    python tools/place_on_lane.py
    python tools/place_on_lane.py --lane 2 --ahead 15 --model "<vehicle from GetObjectCatalog>"

Needs SCENARIO_MODE_EDIT (or PLAY for this run only) and a map with road data.
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402


def xy(v: dict) -> tuple[float, float]:
    return v.get("x", 0.0), v.get("y", 0.0)


def point_on_line(points: list[dict], at: tuple[float, float], ahead: float) -> tuple[dict, float]:
    """The foot of at on the polyline, moved ahead along it; and the heading there (deg, map frame)."""
    best = (float("inf"), 0, 0.0)  # distance, segment, fraction
    for i in range(len(points) - 1):
        (ax, ay), (bx, by) = xy(points[i]), xy(points[i + 1])
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((at[0] - ax) * dx + (at[1] - ay) * dy) / length2))
        d = math.hypot(ax + dx * t - at[0], ay + dy * t - at[1])
        if d < best[0]:
            best = (d, i, t)

    _, seg, t = best
    remaining = ahead
    while True:
        a, b = points[seg], points[seg + 1]
        (ax, ay), (bx, by) = xy(a), xy(b)
        length = math.hypot(bx - ax, by - ay)
        left = (1.0 - t) * length
        if remaining <= left or seg + 2 >= len(points):
            t = min(1.0, t + (remaining / length if length > 0 else 0.0))
            break
        remaining -= left
        seg, t = seg + 1, 0.0

    a, b = points[seg], points[seg + 1]
    (ax, ay), (bx, by) = xy(a), xy(b)
    az, bz = a.get("z", 0.0), b.get("z", 0.0)
    location = {"x": ax + (bx - ax) * t, "y": ay + (by - ay) * t, "z": az + (bz - az) * t}
    return location, math.degrees(math.atan2(by - ay, bx - ax))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--x", type=float, help="map frame x (default: what the camera looks at)")
    ap.add_argument("--y", type=float, help="map frame y")
    ap.add_argument("--lane", type=int, help="lane_number (1 is next to the center line); default: the nearest lane")
    ap.add_argument("--ahead", type=float, default=0.0, help="metres further along the lane")
    ap.add_argument("--radius", type=float, default=50.0)
    ap.add_argument("--model", help="vehicle model (default: the first vehicle in GetObjectCatalog)")
    ap.add_argument("--name", default="", help="entity name (empty: generated)")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        try:
            if args.x is not None and args.y is not None:
                at = (args.x, args.y)
            else:
                center = client.call("GetViewpoint").get("center", {})
                if not center.get("hit"):
                    print("The camera looks at nothing: point it at a road or give --x --y")
                    return 1
                at = xy(center["location"])
            print(f"At ({at[0]:.1f}, {at[1]:.1f})")

            lanes = client.call("GetRoadsNearby", location={"x": at[0], "y": at[1], "z": 0.0},
                                radius_m=args.radius).get("lanes", [])
            if args.lane is None:
                pick = lanes[0] if lanes else None  # nearest first
                if pick is None:
                    print(f"No lane within {args.radius:g} m")
                    return 1
            else:
                wanted = [lane for lane in lanes if lane.get("lane_number") == args.lane]
                outside = [lane for lane in wanted if not lane.get("junction_id")]
                pick = (outside or wanted or [None])[0]
                if pick is None:
                    found = sorted({lane.get("lane_number") for lane in lanes})
                    print(f"No lane {args.lane} within {args.radius:g} m (lane numbers here: {found})")
                    return 1
            print(f"Lane {pick['link_id']}  road {pick.get('road_id')}  lane {pick.get('lane_number')}  "
                  f"{pick.get('distance_m', 0.0):.1f} m away" + (f"  in junction {pick['junction_id']}" if pick.get("junction_id") else ""))

            line = client.call("GetLinkConnections", link_id=pick["link_id"], simplify_tolerance_m=0.05)
            points = line.get("lane", {}).get("center_line", [])
            location, yaw = point_on_line(points, at, args.ahead)
            print(f"Place at ({location['x']:.2f}, {location['y']:.2f}, {location['z']:.2f}) yaw {yaw:.1f}")

            model = args.model
            if not model:
                vehicles = client.call("GetObjectCatalog", types=["ENTITY_TYPE_VEHICLE"]).get("objects", [])
                if not vehicles:
                    print("No vehicle in GetObjectCatalog")
                    return 1
                model = vehicles[0]["name"]
            created = client.call("CreateEntity", entity_id=args.name, model_name=model,
                                  initial_transform={"location": location, "rotation": {"x": 0.0, "y": 0.0, "z": yaw}})
            print(f"Created {created.get('entity_id', args.name)} ({model})")
            return 0
        except ProtoCallError as e:
            print(f"Refused: {e.reason_name} {e.message}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
