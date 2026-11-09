from __future__ import annotations

"""Measures how fast the simulator actually runs for each target real-time factor (MSVM-3077).

For every target FPS and target_rtf asked for: stops the scenario, sets the FIXED time mode with that
FPS and factor, plays for a while, and compares how much simulation time passed with how much real
time passed (the answer's sim_time and real_time, and the simulator's own measured_rtf). Prints one
table; run it before and after a change to compare. Leaves the scenario stopped in the FIXED mode at
1x when done.

    python tools/rtf_check.py
    python tools/rtf_check.py --fps 50 100 --rtf 0.25 0.5 1 2 4 0 --seconds 10
    python tools/rtf_check.py --out rtf_before_sangam.md --label "before, Sangam"

target_rtf 0 means unlimited. Values the simulator refuses (for example 0.25 before MSVM-3077) are
shown as refused. Open a scenario first; it is played, nothing is saved.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402


def seconds(stamp: Optional[dict]) -> float:
    if not stamp:
        return 0.0
    return int(stamp.get("seconds", 0)) + int(stamp.get("nanos", 0)) / 1e9


def stop(client: ProtoClient) -> None:
    try:
        client.call("ControlScenario", action="SCENARIO_ACTION_STOP")
    except ProtoCallError:
        pass  # already stopped
    time.sleep(0.5)


def measure(client: ProtoClient, base: dict, fps: int, rtf: float, run_s: float, warmup_s: float) -> dict:
    stop(client)
    # SetTimeMode takes the whole config: keep the physics step and the rest as they were
    config = dict(base, mode="TIME_MODE_FIXED", target_fps=fps, client_stepping=False, target_rtf=rtf)
    try:
        client.call("SetTimeMode", config=config)
    except ProtoCallError as e:
        return {"error": f"{e.reason_name}: {e.message}"}
    client.call("SetScenarioMode", mode="SCENARIO_MODE_PLAY")
    client.call("ControlScenario", action="SCENARIO_ACTION_START")
    time.sleep(warmup_s)
    first = client.call("GetTimeMode").get("state", {})
    wall0 = time.perf_counter()
    time.sleep(run_s)
    last = client.call("GetTimeMode").get("state", {})
    wall = time.perf_counter() - wall0
    sim = seconds(last.get("sim_time")) - seconds(first.get("sim_time"))
    real = seconds(last.get("real_time")) - seconds(first.get("real_time"))
    # step_index moves only with client stepping; free running takes the ticks from the measured rate
    steps = int(last.get("step_index", 0)) - int(first.get("step_index", 0)) or int(round(real * float(last.get("measured_fps", 0.0))))
    return {
        "sim_s": sim,
        "rtf_sim_over_real": sim / real if real > 0 else 0.0,
        "rtf_sim_over_wall": sim / wall if wall > 0 else 0.0,
        "measured_rtf": float(last.get("measured_rtf", 0.0)),
        "measured_fps": float(last.get("measured_fps", 0.0)),
        "steps": steps,
        "dt_ms": 1000.0 * sim / steps if steps else 0.0,  # 1000 / target_fps when the steps are known
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--fps", type=int, nargs="+", default=[50, 100])
    ap.add_argument("--rtf", type=float, nargs="+", default=[0.25, 0.5, 1, 2, 4, 0])
    ap.add_argument("--seconds", type=float, default=10.0, help="real seconds measured per case")
    ap.add_argument("--warmup", type=float, default=2.0, help="real seconds before measuring")
    ap.add_argument("--out", help="also write the table to this Markdown file (a bare name goes to measurements/rtf/)")
    ap.add_argument("--label", default="", help="a title for the table (build, map)")
    args = ap.parse_args()

    rows = []
    with ProtoClient(args.ip, args.port, timeout=30) as client:
        client.load_schema()
        scenario = client.call('GetScenarioStatus').get('scenario_name')
        base = client.call("GetTimeMode").get("config", {})
        base.setdefault("physics_delta_time_ms", 10)
        print(f"scenario: {scenario}")
        for fps in args.fps:
            for rtf in args.rtf:
                label = "unlimited" if rtf == 0 else f"{rtf:g}x"
                r = measure(client, base, fps, rtf, args.seconds, args.warmup)
                rows.append((fps, label, rtf, r))
                if "error" in r:
                    print(f"  {fps:>4} fps  {label:>9}: refused ({r['error']})")
                else:
                    print(f"  {fps:>4} fps  {label:>9}: RTF {r['rtf_sim_over_real']:.3f} (wall {r['rtf_sim_over_wall']:.3f}, "
                          f"measured_rtf {r['measured_rtf']:.3f})  {r['measured_fps']:.1f} fps  dt {r['dt_ms']:.3f} ms")
        stop(client)
        client.call("SetTimeMode", config=dict(base, mode="TIME_MODE_FIXED", target_fps=50, client_stepping=False, target_rtf=1))

    lines = [f"### {args.label or 'RTF'} ({time.strftime('%Y-%m-%d %H:%M')}, scenario {scenario})", "",
             "| FPS | target | achieved RTF | % of target | measured_rtf | tick dt (ms) |", "|---|---|---|---|---|---|"]
    for fps, label, rtf, r in rows:
        if "error" in r:
            lines.append(f"| {fps} | {label} | refused ({r['error']}) | - | - | - |")
            continue
        pct = f"{100 * r['rtf_sim_over_real'] / rtf:.0f}%" if rtf > 0 else "-"
        lines.append(f"| {fps} | {label} | {r['rtf_sim_over_real']:.3f} | {pct} | {r['measured_rtf']:.3f} | {r['dt_ms']:.3f} |")
    print()
    print(chr(10).join(lines))
    if args.out:
        out = Path(args.out)
        if out.parent == Path("."):
            # A bare file name goes to measurements/rtf/ (git-ignored: results differ per PC)
            out = Path(__file__).resolve().parents[1] / "measurements" / "rtf" / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
