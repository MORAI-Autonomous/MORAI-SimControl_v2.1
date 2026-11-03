from __future__ import annotations

"""Observation API (0x0108) check against a running, logged-in simulator with a map open.

Reads the viewpoint and checks ScreenToWorld against it, moves the camera (top_down, look_at),
takes main-view images (JPEG, PNG) and, with --camera, a camera sensor's image. With --vehicle it
also follows that vehicle while the scenario plays (START, then STOP). Images go to --out.

    python tools/observation_check.py
    python tools/observation_check.py --vehicle Car_1 --camera Camera_1

Start in SCENARIO_MODE_EDIT with the camera looking at the ground (not the sky).
"""

import argparse
import base64
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


def dist2d(a: dict, b: dict) -> float:
    (ax, ay, _), (bx, by, _) = xyz(a), xyz(b)
    return math.hypot(ax - bx, ay - by)


def shown_view(v: dict) -> str:
    cam = v.get("camera", {})
    loc, rot = xyz(cam.get("location", {})), xyz(cam.get("rotation", {}))
    center = v.get("center", {})
    hit = (f"hit ({', '.join(f'{c:.1f}' for c in xyz(center.get('location', {})))}) "
           f"{center.get('distance_m', 0.0):.1f} m {center.get('entity_id', '') or 'scenery'}"
           if center.get("hit") else "no hit")
    return (f"cam ({loc[0]:.1f}, {loc[1]:.1f}, {loc[2]:.1f}) yaw {rot[2]:.1f} pitch {rot[1]:.1f}  "
            f"fov {v.get('horizontal_fov_deg', 0.0):.1f}  {v.get('viewport_width', 0)}x{v.get('viewport_height', 0)}  "
            f"{v.get('mode', 'VIEWPOINT_MODE_UNSPECIFIED')} {v.get('target_entity_id', '')}  center: {hit}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--vehicle", help="vehicle to follow while the scenario plays")
    ap.add_argument("--camera", help="camera sensor entity for GetCameraImage")
    ap.add_argument("--out", default="observation_out", help="folder for the images")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()
        view = lambda: client.call("GetViewpoint")

        print("[1] GetViewpoint and ScreenToWorld")
        v = step("GetViewpoint", view)
        if v is None:
            return 1
        print(f"  SEEN {shown_view(v)}")
        center = v.get("center", {})
        check("center hits something", bool(center.get("hit")), "point the camera at the ground")
        aspect = (v.get("viewport_width", 0) / v["viewport_height"]) if v.get("viewport_height") else 0.0
        s = step("ScreenToWorld (0.5, 0.5)", lambda: client.call("ScreenToWorld", u=0.5, v=0.5, aspect_ratio=aspect))
        if s is not None and center.get("hit"):
            d = dist2d(s.get("hit", {}).get("location", {}), center.get("location", {}))
            check("ScreenToWorld center = GetViewpoint center", d < 0.5, f"{d:.2f} m apart")
        step("ScreenToWorld u 1.5", lambda: client.call("ScreenToWorld", u=1.5, v=0.5), "OUT_OF_RANGE")

        print("[2] SetViewpoint")
        if center.get("hit"):
            px, py, pz = xyz(center["location"])
            step(f"top_down ({px:.1f}, {py:.1f})", lambda: client.call("SetViewpoint", top_down={"x": px, "y": py}))
            t = step("GetViewpoint after top_down", view)
            if t is not None:
                print(f"  SEEN {shown_view(t)}")
                cz = t.get("camera", {}).get("location", {}).get("z", 0.0)
                check("camera above the point", cz - pz > 30.0, f"{cz - pz:.1f} m higher")
                check("mode FREE", t.get("mode") == "VIEWPOINT_MODE_FREE", t.get("mode", ""))

            look = {"point": {"x": px, "y": py, "z": pz}, "distance_m": 30.0, "yaw_deg": 90.0, "pitch_deg": 30.0}
            step("look_at the point from 30 m, yaw 90, pitch 30", lambda: client.call("SetViewpoint", look_at=look))
            time.sleep(0.2)
            la = step("GetViewpoint after look_at", view)
            if la is not None:
                print(f"  SEEN {shown_view(la)}")
                rot = la.get("camera", {}).get("rotation", {})
                check("camera yaw 90", abs(((rot.get("z", 0.0) - 90.0) + 180.0) % 360.0 - 180.0) < 2.0, f"{rot.get('z', 0.0):.1f}")
                check("camera pitch looks down 30", abs(abs(rot.get("y", 0.0)) - 30.0) < 2.0, f"{rot.get('y', 0.0):.1f}")
                lc = la.get("center", {})
                if lc.get("hit"):
                    check("center near the point", dist2d(lc.get("location", {}), center["location"]) < 2.0,
                          f"{dist2d(lc.get('location', {}), center['location']):.2f} m")
        step("look_at distance 0", lambda: client.call(
            "SetViewpoint", look_at={"point": {"x": 0, "y": 0, "z": 0}, "distance_m": 0.0}), "OUT_OF_RANGE")
        step("SetViewpoint with nothing", lambda: client.call("SetViewpoint"), "MISSING_FIELD")
        step("follow while editing", lambda: client.call("SetViewpoint", follow={"entity_id": args.vehicle or "Car_1"}),
             "WRONG_MODE")

        print("[3] CaptureMainView")
        for fmt, ext, magic, kw in (("JPEG", "jpg", b"\xff\xd8", {}),
                                    ("PNG", "png", b"\x89PNG", {"format": "IMAGE_FORMAT_PNG", "width": 320, "height": 180})):
            c = step(f"CaptureMainView {fmt}", lambda: client.call("CaptureMainView", **kw))
            if c is not None:
                data = base64.b64decode(c.get("data", ""))  # MessageToDict gives bytes as base64
                path = out / f"main_view.{ext}"
                path.write_bytes(data)
                check(f"{fmt} image", data[:len(magic)] == magic,
                      f"{c.get('width')}x{c.get('height')}, {len(data) / 1024:.0f} KB -> {path}")
        step("CaptureMainView width 8", lambda: client.call("CaptureMainView", width=8), "OUT_OF_RANGE")

        print("[4] GetCameraImage")
        step("GetCameraImage unknown entity", lambda: client.call("GetCameraImage", entity_id="obs_nobody"), "ENTITY_NOT_FOUND")
        if args.camera:
            step("SetScenarioMode PLAY", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY"))
            step("ControlScenario START", lambda: client.call("ControlScenario", action="SCENARIO_ACTION_START"))
            time.sleep(2.0)
            g = step(f"GetCameraImage {args.camera}", lambda: client.call("GetCameraImage", entity_id=args.camera))
            if g is not None:
                data = base64.b64decode(g.get("data", ""))
                path = out / "camera.jpg"
                path.write_bytes(data)
                check("camera JPEG", data[:2] == b"\xff\xd8", f"{g.get('width')}x{g.get('height')}, "
                      f"{len(data) / 1024:.0f} KB, t {g.get('time_stamp', {})} -> {path}")
            if args.vehicle:
                print("[5] Follow while playing")
                step(f"follow {args.vehicle}", lambda: client.call(
                    "SetViewpoint", follow={"entity_id": args.vehicle, "mode": "VIEWPOINT_MODE_FOCUS"}))
                time.sleep(0.5)
                f = step("GetViewpoint while following", view)
                if f is not None:
                    print(f"  SEEN {shown_view(f)}")
                    check("follows the vehicle", f.get("target_entity_id") == args.vehicle, f.get("target_entity_id", ""))
                step("follow mode FREE", lambda: client.call(
                    "SetViewpoint", follow={"entity_id": args.vehicle, "mode": "VIEWPOINT_MODE_FREE"}), "OUT_OF_RANGE")
            step("ControlScenario STOP", lambda: client.call("ControlScenario", action="SCENARIO_ACTION_STOP"))
            step("SetScenarioMode EDIT", lambda: client.call("SetScenarioMode", mode="SCENARIO_MODE_EDIT"))

    print(f"{'all OK' if failures == 0 else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
