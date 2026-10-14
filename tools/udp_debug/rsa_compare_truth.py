#!/usr/bin/env python3
"""Compares what rsa_dummy_feed.py SENT against what the simulator RECEIVED.

This is the first half of the verification chain:

    1. --truth CSV    what was sent      (rsa_dummy_feed.py --truth)
    2. RsaLog_*.csv   what was received  (FRsaLogManager)
    3. [RSA.Summary]  what was drawn     (rsa_verify_display.py covers 2 vs 3)

Rows are joined on (Timestamp, VehicleId). Timestamp is the packet's utc_time:
the feed chose it, put it on the wire, and the simulator logged it verbatim, so
it is the same number on both sides. Wall-clock Date/Time is NOT used -- the
feed records send time and the simulator records receive time, which are
different instants.

Only the Timestamp intersection is compared, so it does not matter whether
logging started before the feed or stopped after it. Rows outside the overlap
are reported as lead-in / tail-out, not as loss.

Usage:
    python tools/udp_debug/rsa_compare_truth.py sent.csv RsaLog_20260916_135543.csv
    python tools/udp_debug/rsa_compare_truth.py sent.csv "logs/RsaLog_*.csv"     # split parts

Exit code is 1 if any row was lost, corrupted, or displayed against expectation.
"""

import argparse
import csv
import glob
import sys
from collections import Counter, defaultdict

# Fields compared verbatim between the two files. Latitude/Longitude are
# written as float32 on the wire by the feed and printed with the same %.6f
# format on both sides, so they should agree exactly; a tolerance is kept
# anyway so a formatting change does not turn into a false alarm.
NUMERIC_FIELDS = [
    ("Latitude", 1e-6),
    ("Longitude", 1e-6),
    ("Altitude", 1e-3),
    ("Speed", 1e-3),
    ("Heading", 1e-3),
]
EXACT_FIELDS = ["RegionId", "KeyType", "Class", "ClassName"]


def load(paths, label):
    rows = {}
    duplicates = 0
    files = []
    for pattern in paths:
        expanded = sorted(glob.glob(pattern))
        files.extend(expanded if expanded else [pattern])
    for path in files:
        try:
            handle = open(path, "r", newline="", encoding="utf-8", errors="replace")
        except OSError as exc:
            sys.exit("%s: cannot open %s (%s)" % (label, path, exc))
        with handle:
            reader = csv.DictReader(handle)
            missing = {"Timestamp", "VehicleId"} - set(reader.fieldnames or [])
            if missing:
                sys.exit("%s: %s is missing column(s) %s"
                         % (label, path, ", ".join(sorted(missing))))
            for raw in reader:
                try:
                    key = (int(raw["Timestamp"]), int(raw["VehicleId"]))
                except (TypeError, ValueError):
                    continue  # truncated final row
                if key in rows:
                    duplicates += 1
                rows[key] = raw
    return rows, duplicates, files


def section(title):
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def describe(label, rows, duplicates, files):
    stamps = sorted({key[0] for key in rows})
    print("  %-9s %d rows, %d packets, %d ids, %d file(s)"
          % (label + ":", len(rows), len(stamps), len({k[1] for k in rows}), len(files)))
    if stamps:
        print("            span %.1f s" % ((stamps[-1] - stamps[0]) / 1000.0))
    if duplicates:
        print("            WARNING: %d duplicate (Timestamp, VehicleId) rows -- "
              "the last one won" % duplicates)
    return stamps


def main():
    parser = argparse.ArgumentParser(
        description="Compare a dummy-feed truth CSV against the simulator's RSA log.")
    parser.add_argument("truth", help="sent.csv from rsa_dummy_feed.py --truth")
    parser.add_argument("received", nargs="+", help="RsaLog_*.csv (globs allowed)")
    parser.add_argument("--max-examples", type=int, default=5,
                        help="how many offending rows to print per problem")
    args = parser.parse_args()

    sent, sent_dupes, sent_files = load([args.truth], "truth")
    recv, recv_dupes, recv_files = load(args.received, "received")
    if not sent:
        sys.exit("truth file has no usable rows")
    if not recv:
        sys.exit("received log has no usable rows")

    section("1. FILES")
    sent_stamps = describe("sent", sent, sent_dupes, sent_files)
    recv_stamps = describe("received", recv, recv_dupes, recv_files)

    section("2. OVERLAP - the window both files cover")
    common = set(sent_stamps) & set(recv_stamps)
    if not common:
        print("  no shared Timestamp at all.")
        print("  The feed and the log never ran at the same time, or they were")
        print("  pointed at different simulators. Nothing can be compared.")
        return 1
    low, high = min(common), max(common)
    print("  shared packets    : %d  (%.1f s)" % (len(common), (high - low) / 1000.0))
    print("  sent before start : %d packets  (log had not started yet)"
          % sum(1 for s in sent_stamps if s < low))
    print("  sent after end    : %d packets  (log had already stopped)"
          % sum(1 for s in sent_stamps if s > high))
    ring = sum(1 for s in sent_stamps if s < low)
    if ring:
        print("  -> RSA.LogWindowSec is a trailing window and the file is written")
        print("     at Stop(), so an early gap is usually the ring buffer, not loss.")

    sent_common = {k: v for k, v in sent.items() if low <= k[0] <= high}
    recv_common = {k: v for k, v in recv.items() if low <= k[0] <= high}

    section("3. ROW MATCH - was every sent row received?")
    missing = sorted(set(sent_common) - set(recv_common))
    extra = sorted(set(recv_common) - set(sent_common))
    print("  sent in overlap   : %d" % len(sent_common))
    print("  received in overlap: %d" % len(recv_common))
    print("  missing (sent, never received) : %d" % len(missing))
    print("  extra   (received, never sent) : %d" % len(extra))
    for key in missing[:args.max_examples]:
        print("      missing  ts=%d id=%d" % key)
    for key in extra[:args.max_examples]:
        print("      extra    ts=%d id=%d  (another feed on this port?)" % key)
    if missing:
        by_packet = Counter(key[0] for key in missing)
        whole = sum(1 for ts, n in by_packet.items()
                    if n == sum(1 for k in sent_common if k[0] == ts))
        print("  -> %d packet(s) lost entirely, %d partially. A whole packet is a"
              % (whole, len(by_packet) - whole))
        print("     dropped datagram; a partial one means the record loop stopped early.")

    section("4. FIELD FIDELITY - did the values survive the wire?")
    paired = [(k, sent_common[k], recv_common[k]) for k in sorted(set(sent_common) & set(recv_common))]
    print("  compared rows     : %d" % len(paired))
    field_bad = defaultdict(list)
    worst = {}
    for name, tol in NUMERIC_FIELDS:
        for key, a, b in paired:
            try:
                delta = abs(float(a[name]) - float(b[name]))
            except (KeyError, TypeError, ValueError):
                continue
            if name not in worst or delta > worst[name]:
                worst[name] = delta
            if delta > tol:
                field_bad[name].append((key, a[name], b[name], delta))
        status = "OK" if not field_bad[name] else "%d MISMATCH" % len(field_bad[name])
        print("    %-10s max delta %-12.9g tol %-8g %s"
              % (name, worst.get(name, 0.0), tol, status))
    for name in EXACT_FIELDS:
        bad = [(k, a[name], b[name]) for k, a, b in paired
               if name in a and name in b and a[name].strip() != b[name].strip()]
        if bad:
            field_bad[name] = bad
        print("    %-10s %s" % (name, "OK" if not bad else "%d MISMATCH" % len(bad)))
    for name, bad in field_bad.items():
        for entry in bad[:args.max_examples]:
            print("      %s ts=%d id=%d  sent=%s received=%s"
                  % (name, entry[0][0], entry[0][1], entry[1], entry[2]))

    section("5. DISPLAY - was the radius filter obeyed?")
    if "ExpectedDisplayed" not in (paired[0][1] if paired else {}):
        print("  truth file has no ExpectedDisplayed column - skipped")
        disagree = []
    else:
        matrix = Counter()
        disagree = []
        for key, a, b in paired:
            expected = a["ExpectedDisplayed"].strip().lower() == "true"
            actual = b["Displayed"].strip().lower() == "true"
            matrix[(expected, actual)] += 1
            if expected != actual:
                disagree.append((key, a, b))
        print("    expected  actual    rows")
        for expected in (True, False):
            for actual in (True, False):
                count = matrix[(expected, actual)]
                if count:
                    print("    %-9s %-9s %d"
                          % (str(expected).lower(), str(actual).lower(), count))
        print("  disagreements     : %d" % len(disagree))
        if disagree:
            for key, a, b in disagree[:args.max_examples]:
                print("      ts=%d id=%-6d expected=%s actual=%s  distance sent=%s received=%s"
                      % (key[0], key[1], a["ExpectedDisplayed"], b["Displayed"],
                         a["Distance"], b["Distance"]))
            print("  -> ExpectedDisplayed is computed from --camera-lat/--camera-lon and")
            print("     --view-radius. If the camera was not at the anchor, or")
            print("     RSA.ViewRadiusM differs, these are a wrong expectation rather")
            print("     than a renderer fault. Check section 6 first.")

        # Distances the simulator measured, bucketed by what it actually did.
        drawn = [float(b["Distance"]) for _, _, b in paired
                 if b["Displayed"].strip().lower() == "true"]
        hidden = [float(b["Distance"]) for _, _, b in paired
                  if b["Displayed"].strip().lower() != "true"]
        if drawn:
            print("  drawn     : %5d rows, distance max %.0f m" % (len(drawn), max(drawn)))
        if hidden:
            print("  not drawn : %5d rows, distance min %.0f m" % (len(hidden), min(hidden)))
        if drawn and hidden:
            if max(drawn) < min(hidden):
                print("  -> clean separation: no drawn vehicle is further out than any")
                print("     hidden one, so the radius filter is a pure distance cut.")
            else:
                print("  -> OVERLAP: some drawn vehicle is further out than a hidden one.")
                print("     The cut is not distance alone - worth investigating.")

    section("6. CAMERA - where the simulator thinks the camera was")
    offsets = []
    for key, a, b in paired:
        try:
            offsets.append(float(b["Distance"]) - float(a["Distance"]))
        except (KeyError, TypeError, ValueError):
            continue
    if offsets:
        offsets.sort()
        median = offsets[len(offsets) // 2]
        print("  received Distance minus sent Distance:")
        print("    median %+.1f m   min %+.1f m   max %+.1f m"
              % (median, offsets[0], offsets[-1]))
        if abs(median) < 20:
            print("  -> the camera was essentially at the anchor, so ExpectedDisplayed")
            print("     in section 5 can be trusted.")
        else:
            print("  -> the camera was NOT at the anchor. Re-run the feed with")
            print("     --camera-lat/--camera-lon set to where it actually is if you")
            print("     want ExpectedDisplayed to mean anything.")

    section("VERDICT")
    problems = []
    if missing:
        problems.append("%d sent row(s) never arrived" % len(missing))
    if extra:
        problems.append("%d received row(s) were never sent" % len(extra))
    for name, bad in field_bad.items():
        if bad:
            problems.append("%s differs on %d row(s)" % (name, len(bad)))
    if disagree:
        problems.append("%d row(s) drawn against expectation" % len(disagree))

    if not problems:
        print("  PASS - every sent row arrived intact and was displayed as expected.")
        print("  Next: run rsa_verify_display.py on the same log to close 2 vs 3.")
        return 0
    for problem in problems:
        print("  FAIL - %s" % problem)
    return 1


if __name__ == "__main__":
    sys.exit(main())
