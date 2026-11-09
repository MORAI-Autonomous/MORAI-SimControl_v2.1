from __future__ import annotations

"""Checks that a scenario plays the same every time (MSVM-3077).

Plays the open scenario several times up to the same simulation time and compares the simulator's
state logs (statelog.csv: position, velocity, rotation of every entity, by simulation time) row by
row, text to text, so equal means bit for bit.

Two ways to play, because a command sent over the network lands on whichever tick is running when it
arrives, which changes from run to run:

- --stepped: client stepping. The script advances one tick at a time and sends the vehicles' inputs
  (ManualControl) before each tick, so every input lands on the same tick in every run. Checks the
  physics itself: repeats, and the physics substep count (odd counts too).
- free running (default): the FIXED (or VARIABLE) mode at a target_rtf. The inputs are sent once,
  right after the start, and kept. Checks that how fast it plays does not change the result.

Tables:
- Repeat: the same settings played again. Any differing row means the run is not deterministic.
- Across target RTF: the same physics played at different speeds. Must be equal in FIXED.

The vehicles must be driven over the network (control source EXTERNAL_AD), with no other client
sending commands meanwhile. Nothing is saved; the scenario is left stopped in FIXED at 1x.

    python tools/determinism_check.py --vehicles Car_1 Car_2 --stepped --pdt 20 14 10 8 7
    python tools/determinism_check.py --vehicles Car_1 Car_2 --rtf 1 0 --repeat 2
    python tools/determinism_check.py --vehicles Car_1 Car_2 --mode variable --repeat 2

--pdt sets physics_delta_time_ms (builds before MSVM-3077); the substeps it gives at --fps are shown
(ceil(tick / pdt)). --substeps sets the physics substep count, on builds that take it.

Inputs, by simulation time t: throttle 0.4 from the start; from 5 s steering 0.2 x sin(2 pi (t - 5) / 4);
from 15 s throttle 0 and brake 0.5. Free running sends only the value at t = 0.
"""

import argparse
import csv
import glob
import math
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402

COMPARED = ["PositionX (m)", "PositionY (m)", "PositionZ (m)", "VelocityX (km/h)", "VelocityY (km/h)",
            "VelocityZ (km/h)", "RotationX (deg)", "RotationY (deg)", "RotationZ (deg)"]


def inputs_at(t: float) -> Tuple[float, float, float]:
    """throttle, brake, steering at simulation time t."""
    if t >= 15.0:
        return 0.0, 0.5, 0.0
    steering = 0.2 * math.sin(2 * math.pi * (t - 5.0) / 4.0) if t >= 5.0 else 0.0
    return 0.4, 0.0, steering


def seconds(stamp: Optional[dict]) -> float:
    if not stamp:
        return 0.0
    return int(stamp.get("seconds", 0)) + int(stamp.get("nanos", 0)) / 1e9


def stop(client: ProtoClient) -> None:
    try:
        client.call("ControlScenario", action="SCENARIO_ACTION_STOP")
    except ProtoCallError:
        pass
    time.sleep(1.0)


def drive(client: ProtoClient, vehicles: List[str], t: float) -> None:
    throttle, brake, steering = inputs_at(t)
    for v in vehicles:
        client.call("ManualControl", entity_id=v, throttle=throttle, brake=brake, steering=steering)


def find_statelog(log_roots: List[str], after: float, wait_s: float = 10.0) -> Optional[str]:
    deadline = time.time() + wait_s
    while time.time() < deadline:
        found = [p for root in log_roots for p in glob.glob(os.path.join(root, "*", "simulation_*", "*statelog.csv"))
                 if os.path.getmtime(p) >= after]
        if found:
            return max(found, key=os.path.getmtime)
        time.sleep(0.5)
    return None


def read_statelog(path: str, until_s: float) -> Dict[Tuple[str, str], List[str]]:
    """(time, entity) -> compared values, as written."""
    rows: Dict[Tuple[str, str], List[str]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        index = [header.index(c) for c in COMPARED if c in header]
        t_col, e_col = header.index("time (sec)"), header.index("Entry")
        for row in reader:
            if len(row) <= max(index + [t_col, e_col]):
                continue
            if float(row[t_col]) > until_s:
                break
            rows[(row[t_col], row[e_col])] = [row[i] for i in index]
    return rows


def compare(a: Dict, b: Dict) -> Tuple[int, int, float, Optional[str]]:
    """Rows compared, rows that differ, largest difference, first differing time."""
    common = sorted(set(a) & set(b), key=lambda k: (float(k[0]), k[1]))
    differing, largest, first = 0, 0.0, None
    for key in common:
        if a[key] != b[key]:
            differing += 1
            first = first or key[0]
            for x, y in zip(a[key], b[key]):
                try:
                    largest = max(largest, abs(float(x) - float(y)))
                except ValueError:
                    pass
    return len(common), differing, largest, first


def run_once(client: ProtoClient, args, base: dict, rtf: float, pdt: Optional[int], substeps: Optional[int]) -> dict:
    stop(client)
    fixed = args.mode == "fixed"
    config = dict(base, mode="TIME_MODE_FIXED" if fixed else "TIME_MODE_VARIABLE", target_fps=args.fps,
                  client_stepping=fixed and args.stepped, target_rtf=rtf if fixed and not args.stepped else 1)
    if pdt is not None:
        config["physics_delta_time_ms"] = pdt
    if substeps is not None:
        config["physics_substeps"] = substeps
    try:
        client.call("SetTimeMode", config=config)
    except Exception as e:  # refused, or a field this build does not know
        return {"error": str(e)}
    started = time.time()
    client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY")
    client.call("ControlScenario", action="SCENARIO_ACTION_START")
    if fixed and args.stepped:
        ticks = int(round((args.sim_seconds + 0.5) * args.fps))
        for i in range(ticks):
            if args.vehicles:
                drive(client, args.vehicles, i / args.fps)
            client.call("StepSimulation", step_count=1)
    else:
        if args.vehicles:
            drive(client, args.vehicles, 0.0)
        while seconds(client.call("GetTimeMode").get("state", {}).get("sim_time")) < args.sim_seconds + 0.5:
            time.sleep(0.2)
    stop(client)
    path = find_statelog(args.log_root, started)
    if path is None:
        return {"error": "no statelog written"}
    return {"path": path, "rows": read_statelog(path, args.sim_seconds), "wall_s": time.time() - started}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--mode", choices=["fixed", "variable"], default="fixed")
    ap.add_argument("--stepped", action="store_true", help="client stepping, inputs on exact ticks (FIXED only)")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--pdt", type=int, nargs="*", default=[], help="physics_delta_time_ms values")
    ap.add_argument("--substeps", type=int, nargs="*", default=[], help="physics substep counts")
    ap.add_argument("--rtf", type=float, nargs="+", default=[1.0], help="free running FIXED only; 0 is unlimited")
    ap.add_argument("--vehicles", nargs="*", default=[], help="entities to send ManualControl to")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--sim-seconds", type=float, default=20.0)
    # The simulator writes under its working directory: the project when launched from it, the engine
    # folder when the editor is launched from the engine
    ap.add_argument("--log-root", nargs="+", default=[r"D:\Dev\clone_morai_world_ue5.8\SimulationLogs",
                                                     r"C:\Program Files\Epic Games\UE_5.8\SimulationLogs"])
    ap.add_argument("--out", help="also write the tables to this Markdown file (a bare name goes to measurements/determinism/)")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    if args.mode == "variable" or args.stepped:
        args.rtf = [1.0]

    physics = [("pdt", v) for v in args.pdt] + [("substeps", v) for v in args.substeps] or [("pdt", None)]
    tick_ms = 1000.0 / args.fps
    runs: Dict[Tuple, List[dict]] = {}
    with ProtoClient(args.ip, args.port, timeout=30) as client:
        client.load_schema()
        scenario = client.call("GetScenarioStatus").get("scenario_name")
        base = client.call("GetTimeMode").get("config", {})
        base.setdefault("physics_delta_time_ms", 10)
        how = "stepped" if args.stepped else ("free running" if args.mode == "fixed" else "variable")
        print(f"scenario: {scenario}, {args.mode} {args.fps} fps, {how}, {args.sim_seconds:g} s, vehicles {args.vehicles}")
        for kind, value in physics:
            for rtf in args.rtf:
                for i in range(args.repeat):
                    r = run_once(client, args, base, rtf, value if kind == "pdt" else None, value if kind == "substeps" else None)
                    runs.setdefault((kind, value, rtf), []).append(r)
                    what = f"{kind} {value}" if value is not None else "physics as set"
                    print(f"  {what}, rtf {rtf:g}, run {i + 1}: "
                          + (r["error"] if "error" in r else f"{len(r['rows'])} rows, {r['wall_s']:.1f} s wall"))
        stop(client)
        client.call("SetTimeMode", config=dict(base, mode="TIME_MODE_FIXED", client_stepping=False, target_rtf=1))

    def name(kind, value):
        if value is None:
            return "as set"
        if kind == "pdt":
            n = math.ceil(tick_ms / value - 1e-9)
            return f"PDT {value} ms ({n} x {tick_ms / n:.3f} ms)"
        if value == 0:
            n = math.ceil(tick_ms / 10 - 1e-9)  # automatic: steps of 10 ms at most
            return f"auto ({n} x {tick_ms / n:.3f} ms)"
        return f"{value} substeps ({tick_ms / value:.3f} ms)"

    def rtf_name(rtf):
        if args.mode == "variable":
            return "variable"
        if args.stepped:
            return "stepped"
        return "unlimited" if rtf == 0 else f"{rtf:g}x"

    lines = [f"### {args.label or 'Determinism'} ({time.strftime('%Y-%m-%d %H:%M')}, scenario {scenario}, "
             f"{args.mode} {args.fps} FPS, {how}, {args.sim_seconds:g} s, vehicles {', '.join(args.vehicles) or '-'})", "",
             "Repeat: the same settings played again", "",
             "| physics | play | runs | rows | differing rows | largest difference | first differing time (s) |",
             "|---|---|---|---|---|---|---|"]
    for (kind, value, rtf), rs in runs.items():
        ok = [r for r in rs if "error" not in r]
        if len(ok) < 2:
            lines.append(f"| {name(kind, value)} | {rtf_name(rtf)} | {len(ok)} | - | - | - | {rs[0].get('error', '')} |")
            continue
        worst = max((compare(ok[0]["rows"], r["rows"]) for r in ok[1:]), key=lambda c: c[1])
        lines.append(f"| {name(kind, value)} | {rtf_name(rtf)} | {len(ok)} | {worst[0]} | {worst[1]} | "
                     f"{worst[2]:.6g} | {worst[3] or '-'} |")

    if len(args.rtf) > 1:
        lines += ["", "Across target RTF: same physics played at different speeds (must be equal)", "",
                  "| physics | compared | rows | differing rows | largest difference | first differing time (s) |",
                  "|---|---|---|---|---|---|"]
        for kind, value in physics:
            firsts = [(rtf, runs[(kind, value, rtf)][0]) for rtf in args.rtf if "error" not in runs[(kind, value, rtf)][0]]
            for (rtf_a, a), (rtf_b, b) in zip(firsts, firsts[1:]):
                c = compare(a["rows"], b["rows"])
                lines.append(f"| {name(kind, value)} | {rtf_name(rtf_a)} vs {rtf_name(rtf_b)} | {c[0]} | {c[1]} | "
                             f"{c[2]:.6g} | {c[3] or '-'} |")

    print()
    print(chr(10).join(lines))
    if args.out:
        out = Path(args.out)
        if out.parent == Path("."):
            # A bare file name goes to measurements/determinism/ (git-ignored: results differ per PC)
            out = Path(__file__).resolve().parents[1] / "measurements" / "determinism" / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
