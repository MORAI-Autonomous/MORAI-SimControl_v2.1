#!/usr/bin/env python3
"""Offline verifier for the RSA display path.

Answers one question: is what the simulator draws exactly what it received?

The simulator writes one CSV row per received vehicle per packet (RsaLog_*.csv,
see FRsaLogManager). That log is a complete record of the input, so the set of
vehicles that *should* be on screen at any instant can be reconstructed from it
without touching the renderer, and compared against what the renderer reports.

The reconstruction mirrors ARSAInstancedRenderer exactly:
  - a vehicle is drawn if Displayed=true (inside RSA.ViewRadius),
  - it stays drawn until KeepAliveSec elapses without a refresh
    (the expiry sweep at the top of ARSAInstancedRenderer::Tick),
  - one instance per VehicleId, so a repeated id is one vehicle, not two.

Usage:
    python tools/udp_debug/rsa_verify_display.py <RsaLog.csv> [--keepalive 1.0] [--cell 20]
"""

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict

# Mirrors ARSAInstancedRenderer::MaxPlausibleSpeedMps - a jump faster than this is
# treated by the renderer as the upstream reusing an id for a different vehicle.
MAX_PLAUSIBLE_SPEED_MPS = 50.0

CLASS_NAMES = {0: "Other", 1: "Bus", 2: "Car", 3: "Truck",
               4: "Bicycle", 5: "Pedestrian", 90: "VRU", 91: "Bicycle(91)"}


def parse_time(time_str):
    """Seconds since midnight. The date is checked separately so a midnight
    rollover is reported rather than silently folding time backwards."""
    hour, minute, rest = time_str.split(":")
    return int(hour) * 3600 + int(minute) * 60 + float(rest)


def percentile(sorted_values, fraction):
    if not sorted_values:
        return float("nan")
    return sorted_values[min(len(sorted_values) - 1, int(fraction * len(sorted_values)))]


def load(path):
    rows = []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        if "VehicleId" not in (reader.fieldnames or []):
            sys.exit("not an RSA log: header is %r" % (reader.fieldnames,))
        for raw in reader:
            try:
                rows.append({
                    "t": parse_time(raw["Time"]),
                    "date": raw["Date"],
                    "id": int(raw["VehicleId"]),
                    "region": int(raw["RegionId"]),
                    "cls": int(raw["Class"]),
                    "lat": float(raw["Latitude"]),
                    "lon": float(raw["Longitude"]),
                    "shown": raw["Displayed"].strip().lower() == "true",
                    "dist": float(raw["Distance"]),
                })
            except (KeyError, ValueError):
                continue  # a truncated final row, if the file was cut mid-write
    rows.sort(key=lambda row: row["t"])
    return rows


def report_feed(rows):
    print("=" * 74)
    print("1. FEED - what actually arrived")
    print("=" * 74)
    span = rows[-1]["t"] - rows[0]["t"]
    packets = sorted({row["t"] for row in rows})
    dates = sorted({row["date"] for row in rows})
    if len(dates) > 1:
        print("  WARNING: log spans %s - times below fold at midnight" % ", ".join(dates))
    print("  rows              : %d" % len(rows))
    print("  span              : %.1f s  (%s)" % (span, dates[0]))
    print("  packets           : %d  (%.1f Hz)" % (len(packets), len(packets) / span if span else 0))
    print("  rows per packet   : %.1f avg" % (len(rows) / len(packets)))
    print("  distinct ids      : %d" % len({row["id"] for row in rows}))

    by_class = Counter(row["cls"] for row in rows)
    shown_by_class = Counter(row["cls"] for row in rows if row["shown"])
    print("  class mix (received -> displayed):")
    for cls, count in by_class.most_common():
        print("    %-12s %8d  %5.1f%%   displayed %8d" % (
            CLASS_NAMES.get(cls, "code %d" % cls), count,
            100.0 * count / len(rows), shown_by_class.get(cls, 0)))
    shown = sum(shown_by_class.values())
    print("  displayed rows    : %d / %d  (%.1f%% - the rest were outside RSA.ViewRadius)"
          % (shown, len(rows), 100.0 * shown / len(rows)))
    return packets


def report_duplicates(rows):
    print()
    print("=" * 74)
    print("2. UPSTREAM DUPLICATES - the same id twice in one packet")
    print("=" * 74)
    per_packet = defaultdict(list)
    for row in rows:
        per_packet[row["t"]].append(row["id"])
    dup_packets = 0
    dup_rows = 0
    for ids in per_packet.values():
        extra = len(ids) - len(set(ids))
        if extra:
            dup_packets += 1
            dup_rows += extra
    print("  packets with a repeated id : %d / %d" % (dup_packets, len(per_packet)))
    print("  duplicated rows            : %d" % dup_rows)
    print("  -> these inflate the received count but NOT the drawn count:")
    print("     UpsertVehicle is keyed by id, so a repeat moves one instance.")


def report_refresh(rows, keepalive):
    print()
    print("=" * 74)
    print("3. REFRESH RATE - is KeepAliveSec=%.2f the right length?" % keepalive)
    print("=" * 74)
    last_seen = {}
    gaps = []
    for row in rows:
        previous = last_seen.get(row["id"])
        if previous is not None and row["t"] > previous:
            gaps.append(row["t"] - previous)
        last_seen[row["id"]] = row["t"]
    gaps.sort()
    if not gaps:
        print("  no id was seen twice - cannot measure")
        return
    print("  per-id update interval: p50 %.3f s  p90 %.3f s  p99 %.3f s  max %.3f s"
          % (percentile(gaps, 0.50), percentile(gaps, 0.90),
             percentile(gaps, 0.99), gaps[-1]))
    over = sum(1 for gap in gaps if gap > keepalive)
    print("  intervals longer than keep-alive: %d / %d (%.2f%%)"
          % (over, len(gaps), 100.0 * over / len(gaps)))
    print("  -> keep-alive shorter than p99 makes live vehicles blink out;")
    print("     everything beyond p50 is how long a departed vehicle lingers.")


def report_live_set(rows, packets, keepalive):
    """Replays the renderer's own liveness rule over the log."""
    print()
    print("=" * 74)
    print("4. LIVE SET - how many vehicles should be on screen")
    print("=" * 74)
    per_packet = defaultdict(list)
    for row in rows:
        if row["shown"]:
            per_packet[row["t"]].append(row)

    last_seen = {}
    samples = []
    for time_sec in packets:
        for row in per_packet.get(time_sec, ()):
            last_seen[row["id"]] = time_sec
        live = sum(1 for seen in last_seen.values() if time_sec - seen <= keepalive)
        in_packet = len({row["id"] for row in per_packet.get(time_sec, ())})
        samples.append((time_sec, live, in_packet))

    # Skip the first keep-alive window: the live set is still filling up there.
    warm = [sample for sample in samples if sample[0] - packets[0] > keepalive] or samples
    lives = sorted(sample[1] for sample in warm)
    ratios = sorted(sample[1] / sample[2] for sample in warm if sample[2] > 0)
    print("  displayed ids in a single packet : p50 %d  max %d"
          % (percentile(sorted(sample[2] for sample in warm), 0.50),
             max(sample[2] for sample in warm)))
    print("  live set (packet + keep-alive)   : p50 %d  p99 %d  max %d"
          % (percentile(lives, 0.50), percentile(lives, 0.99), lives[-1]))
    print("  inflation from keep-alive        : p50 x%.2f  max x%.2f"
          % (percentile(ratios, 0.50), ratios[-1] if ratios else float("nan")))
    print()
    print("  -> compare 'live set' against the simulator's own occupied-instance")
    print("     count for the same wall-clock second ([RSA.Summary] liveTotal).")
    print("     Equal = the display is faithful. Renderer higher = leaked instances.")


def report_id_reuse(rows):
    """The renderer keys one instance per VehicleId. If the upstream does not
    guarantee that VehicleId is globally unique, two real vehicles collapse into
    one instance - an under-count, plus a visible jitter as the single instance
    is dragged between the two positions."""
    print()
    print("=" * 74)
    print("5. ID UNIQUENESS - is one id standing in for several real vehicles?")
    print("=" * 74)
    previous_row = {}
    teleports = 0
    class_changes = 0
    changed_ids = set()
    far_ids = set()
    metres_per_deg_lat = 111320.0
    metres_per_deg_lon = 111320.0 * math.cos(math.radians(rows[len(rows) // 2]["lat"]))
    for row in rows:
        previous = previous_row.get(row["id"])
        if previous is not None:
            elapsed = row["t"] - previous["t"]
            north = (row["lat"] - previous["lat"]) * metres_per_deg_lat
            east = (row["lon"] - previous["lon"]) * metres_per_deg_lon
            jump = math.hypot(north, east)
            if elapsed > 1e-6 and jump / elapsed > MAX_PLAUSIBLE_SPEED_MPS:
                teleports += 1
            if jump > 100.0:
                far_ids.add(row["id"])
            if row["cls"] != previous["cls"]:
                class_changes += 1
                changed_ids.add(row["id"])
        previous_row[row["id"]] = row

    # The decisive test: the same id carried by two different RegionIds inside a
    # single packet cannot be one vehicle that moved - it is two vehicles at once.
    regions_per_id = defaultdict(set)
    for row in rows:
        regions_per_id[row["id"]].add(row["region"])
    multi_region = {i for i, regions in regions_per_id.items() if len(regions) > 1}

    per_packet = defaultdict(lambda: defaultdict(set))
    for row in rows:
        per_packet[row["t"]][row["id"]].add(row["region"])
    simultaneous = sum(1 for packet in per_packet.values()
                       for regions in packet.values() if len(regions) > 1)

    total_ids = len(regions_per_id)
    print("  distinct ids                        : %d" % total_ids)
    print("  ids seen under more than one region : %d (%.1f%%)"
          % (len(multi_region), 100.0 * len(multi_region) / total_ids))
    print("  ids that jump more than 100 m       : %d" % len(far_ids))
    print("  ...of which are multi-region        : %d" % len(far_ids & multi_region))
    print("  same id, two regions, ONE packet    : %d" % simultaneous)
    print("  implausible jumps (> %.0f m/s)        : %d" % (MAX_PLAUSIBLE_SPEED_MPS, teleports))
    print("  class changes on a live id          : %d (on %d ids)"
          % (class_changes, len(changed_ids)))
    print()
    print("  -> if the far-jumping ids are the multi-region ids, VehicleId is unique")
    print("     only WITHIN a region. UpsertVehicle keys on VehicleId alone, so those")
    print("     vehicles share one instance: fewer boxes than vehicles, and the box")
    print("     teleports between them. The same collision flips the reported class,")
    print("     and the class-change branch in UpsertVehicle frees the old slot")
    print("     without hiding it - those instances stay on screen at full size,")
    print("     counted by nothing.")


def report_density(rows, packets, keepalive, cell_m):
    print()
    print("=" * 74)
    print("6. DENSITY - is the pile-up in the data or in the renderer?")
    print("=" * 74)
    per_packet = defaultdict(list)
    for row in rows:
        if row["shown"]:
            per_packet[row["t"]].append(row)

    metres_per_deg_lat = 111320.0
    metres_per_deg_lon = 111320.0 * math.cos(math.radians(rows[len(rows) // 2]["lat"]))

    best = None
    live = {}
    for time_sec in packets:
        for row in per_packet.get(time_sec, ()):
            live[row["id"]] = row
        live = {key: row for key, row in live.items() if time_sec - row["t"] <= keepalive}
        if best is None or len(live) > len(best[1]):
            best = (time_sec, dict(live))

    time_sec, snapshot = best
    cells = Counter()
    for row in snapshot.values():
        cell_x = int(row["lat"] * metres_per_deg_lat / cell_m)
        cell_y = int(row["lon"] * metres_per_deg_lon / cell_m)
        cells[(cell_x, cell_y)] += 1
    print("  busiest instant: t=%.3f  live vehicles=%d" % (time_sec, len(snapshot)))
    print("  %d m cells occupied: %d" % (cell_m, len(cells)))
    print("  densest cells (distinct ids in one %d x %d m square):" % (cell_m, cell_m))
    for (cell_x, cell_y), count in cells.most_common(8):
        latitude = cell_x * cell_m / metres_per_deg_lat
        longitude = cell_y * cell_m / metres_per_deg_lon
        print("    %4d vehicles  at %.6f, %.6f" % (count, latitude, longitude))
    print()
    print("  -> open the densest coordinate on a map. If the received data really")
    print("     holds that many distinct ids in one square, the pile on screen is")
    print("     the feed, not a bug.")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", help="RsaLog_*.csv written by FRsaLogManager")
    parser.add_argument("--keepalive", type=float, default=1.0,
                        help="RSA.HismKeepAliveSec in force during the capture (default 1.0)")
    parser.add_argument("--cell", type=int, default=20,
                        help="density cell size in metres (default 20)")
    args = parser.parse_args()

    rows = load(args.log)
    if not rows:
        sys.exit("log is empty")

    packets = report_feed(rows)
    report_duplicates(rows)
    report_refresh(rows, args.keepalive)
    report_live_set(rows, packets, args.keepalive)
    report_id_reuse(rows)
    report_density(rows, packets, args.keepalive, args.cell)


if __name__ == "__main__":
    main()
