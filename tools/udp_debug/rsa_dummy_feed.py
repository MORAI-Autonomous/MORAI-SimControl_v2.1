#!/usr/bin/env python3
"""Dummy RSA (RoadSideAlert) UDP feed for the simulator.

Two modes:

  fixed (default)  One vehicle per class, parked in a row. Answers "does each
                   class draw at all?" and nothing else.

  --population N   N vehicles around the anchor that drift, expire and are
                   replaced, plus optional traffic deliberately placed beyond
                   RSA.ViewRadiusM. Exercises the parts a static row never
                   touches: the keep-alive expiry sweep, slot recycling in
                   FreeSlotsByClass, and the radius filter.

The wire format mirrors
Content/NetworkInterface/Monitoring/RoadSideAlertMessageTemplate.tmpl exactly;
see WIRE FORMAT below.

Default target is 127.0.0.1:16002 -- the RoadSideAlert interface. Note that
16001 is ProbeVehicleData, a different feed.

Usage:
    python tools/udp_debug/rsa_dummy_feed.py                       # one vehicle per class
    python tools/udp_debug/rsa_dummy_feed.py --population 30 --truth sent.csv
    python tools/udp_debug/rsa_dummy_feed.py --population 30 --outside 10
    python tools/udp_debug/rsa_dummy_feed.py --once --dump-hex     # single packet, print bytes

VERIFYING THAT WHAT IS DRAWN IS WHAT WAS SENT

  Three records have to agree, and each pair catches a different failure:

    1. --truth CSV        what this script SENT
    2. RsaLog_*.csv       what the simulator RECEIVED   (FRsaLogManager)
    3. [RSA.Summary]      what the renderer DREW        (RSA.LogSummary 1)

  1 vs 2 catches losses and corruption on the wire and in the parser: a
  dropped datagram, a misread field, a class code that changed meaning.
  Row counts should match exactly, and the Distance column should agree to
  within the ~0.4 m the float32 lat/lon costs.

  2 vs 3 is what rsa_verify_display.py already reports -- it
  replays the renderer's own liveness rule over the received log and prints
  the live set to compare against the simulator's occupied-instance count.

  Running only 2 vs 3 proves the renderer is faithful to its input but says
  nothing about whether the input was complete. The --truth file closes that
  half. Both halves are needed because they fail independently.

  The ExpectedDisplayed column is computed from --camera-lat/--camera-lon and
  --view-radius, so it is only meaningful if those match where the camera
  actually is and what RSA.ViewRadiusM is set to.

WIRE FORMAT (all little-endian, no padding)

  Header, 5 bytes:
    uint16  total_size     whole datagram length
    uint8   type
    uint16  count          number of records

  None of the three is mapped to a protobuf field, so the simulator ignores
  their values -- but it does consume the 5 bytes. The record count is derived
  as (remaining bytes / 35), so the payload must be an exact multiple of 35
  with no trailing padding.

  Record, 35 bytes each:
    +0   int64    utc_time      unix milliseconds
    +8   uint16   region_id
    +10  int32    vehicle_id
    +14  float32  speed         m/s
    +18  uint16   heading       integer degrees, 0=N clockwise; 360 = "unknown"
    +20  float32  latitude      WGS84 degrees  (float32 on the wire: ~0.4 m)
    +24  float32  longitude     WGS84 degrees
    +28  float32  altitude      metres
    +32  uint8    key_type
    +33  uint16   vehicle_type  transmission code, see CLASS_NAMES

  latitude/longitude are declared FLOAT in the template even though the
  protobuf field is double, so they go on the wire as 4-byte floats. That
  costs about 0.4 m of position resolution and is the upstream's design, not
  a shortcut taken here -- sending doubles would misalign every later field.

RENDERING PRECONDITIONS

  - RSA.ViewRadiusM (default 1000) filters by distance from the MainCamera,
    so the camera must be within ~1 km of --lat/--lon or nothing is drawn.
  - RSA.HismKeepAliveSec (default 1.0) frees a vehicle's slot after one second
    without a refresh, so --hz must stay above 1. Default 10 is comfortable.
  - Without a GeoReferencingSystem in the level no lat/lon can be resolved at
    all; the simulator logs "[RSA] ... GeoReferencingSystem=MISSING" in that
    case and draws nothing.
"""

import argparse
import datetime
import math
import random
import socket
import struct
import sys
import time

# Transmission codes, per RoadSideAlertSetCommand::VehicleClassFromInt.
# These are NOT the datamodel VehicleClass enum values -- the proto enum calls
# 1 "PASSENGER" and 2 "BUS", while the wire uses 1=Bus and 2=Car. The command's
# mapping is the authoritative one.
CLASS_NAMES = {
    0: "Other",
    1: "Bus",
    2: "Car",
    3: "Truck",
    4: "Bicycle",
    5: "Pedestrian",
}

# Rough share of each class in a real capture, used to populate --population
# with a plausible mix rather than a uniform one. Car dominates, Other is the
# upstream catch-all and is the next largest.
CLASS_WEIGHTS = {0: 22, 1: 6, 2: 55, 3: 11, 4: 2, 5: 4}

HEADER_FMT = "<HBH"
RECORD_FMT = "<qHifHfffBH"
RECORD_SIZE = struct.calcsize(RECORD_FMT)  # 35
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 5

# Mirrors FRsaLogManager::GetCsvHeader so a --truth file lines up column for
# column with the simulator's own RsaLog_*.csv. Displayed becomes
# ExpectedDisplayed: this script knows where it put a vehicle, but only the
# simulator knows where the camera was.
TRUTH_HEADER = ("Date,Time,VehicleId,Timestamp,RegionId,Latitude,Longitude,Altitude,"
                "Speed,Heading,KeyType,Class,ClassName,ExpectedDisplayed,Distance")

# Anchors are real road links from the Hwaseong network
# (Content/Scenario/Maps/DigitalTwin_Maps/R_KR_PR_Hwaseong-si/network.xml),
# converted from UTM 52N (EPSG:32652) to WGS84. Vehicles laid along a real road
# sit on a lane, so ground and yaw snapping behave as they would with real
# traffic instead of landing in a field.
#
# The conversion was checked against the project's own UTM/lat-lon pairs in
# DataSavefile/SimData/MapTiledata.csv and agrees to eight decimal places.
ANCHORS = {
    # 249 m from Hwaseong City Hall, which is where the camera starts, so
    # vehicles spawned here are in view without moving the camera.
    # network.xml link 1348, node 341->258, 211 m long.
    "cityhall": (37.1990850, 126.8275694, 52.6, 51.1),
    # Near the centre of the network. link 1507->1509, 253 m long.
    "center": (37.2207301, 126.8061479, 41.5, 292.3),
}
DEFAULT_ANCHOR = "cityhall"

HEADING_UNKNOWN = 360  # upstream sentinel; not a bearing

METRES_PER_DEG_LAT = 111320.0


def metres_per_deg_lon(lat):
    return METRES_PER_DEG_LAT * math.cos(math.radians(lat))


def offset_metres(lat, lon, bearing_deg, distance_m):
    """Point `distance_m` from (lat, lon) along `bearing_deg`.

    Flat-earth approximation. Errors are well under a centimetre at the few
    hundred metres this script spreads vehicles over, which is far below the
    0.4 m the float32 wire fields cost anyway.
    """
    bearing = math.radians(bearing_deg)
    dlat = distance_m * math.cos(bearing) / METRES_PER_DEG_LAT
    dlon = distance_m * math.sin(bearing) / metres_per_deg_lon(lat)
    return lat + dlat, lon + dlon


def distance_metres(lat1, lon1, lat2, lon2):
    dlat = (lat2 - lat1) * METRES_PER_DEG_LAT
    dlon = (lon2 - lon1) * metres_per_deg_lon(lat1)
    return math.hypot(dlat, dlon)


def build_packet(vehicles, now_ms):
    """One datagram holding every vehicle in `vehicles`."""
    records = b"".join(
        struct.pack(
            RECORD_FMT,
            now_ms,
            v["region_id"],
            v["vehicle_id"],
            v["speed"],
            v["heading"],
            v["lat"],
            v["lon"],
            v["alt"],
            v["key_type"],
            v["vehicle_type"],
        )
        for v in vehicles
    )
    total = HEADER_SIZE + len(records)
    return struct.pack(HEADER_FMT, total, 0, len(vehicles)) + records


# ---------------------------------------------------------------------------
# fixed mode -- one vehicle per class, in a row
# ---------------------------------------------------------------------------

def make_row(args, classes):
    vehicles = []
    for i, code in enumerate(classes):
        lat, lon = offset_metres(args.lat, args.lon, args.heading, i * args.spacing)
        vehicles.append({
            "vehicle_id": args.base_id + i,
            "region_id": args.region,
            "speed": args.speed,
            "heading": args.heading_code,
            "lat": lat,
            "lon": lon,
            "alt": args.alt,
            "key_type": 0,
            "vehicle_type": code,
        })
    return vehicles


def advance_row(vehicles, heading_deg, distance_m):
    for v in vehicles:
        v["lat"], v["lon"] = offset_metres(v["lat"], v["lon"], heading_deg, distance_m)


# ---------------------------------------------------------------------------
# population mode -- drifting traffic with churn
# ---------------------------------------------------------------------------

class Population(object):
    """A set of vehicles that move, expire and are replaced.

    Ids are handed out monotonically and never reused, which is what a
    well-behaved upstream does. --reuse-ids turns that off to reproduce the
    known upstream behaviour where an id comes back on a different vehicle:
    the renderer keys one instance per (region, id), so a reused id does not
    add an instance, it teleports the existing one.
    """

    def __init__(self, args, classes, rng):
        self.args = args
        self.classes = classes
        self.rng = rng
        self.next_id = args.base_id
        self.retired_ids = []
        self.vehicles = []
        self.weights = [CLASS_WEIGHTS.get(c, 10) for c in classes]

        # Seed one of each class before filling the rest from the weighted mix,
        # so a class never goes missing just because it drew badly -- Bicycle
        # and Pedestrian are only a few percent of the real distribution and
        # would otherwise be absent from a small population.
        for index in range(args.population):
            forced = classes[index] if index < len(classes) else None
            self.vehicles.append(self._spawn(inside=True, cls=forced))
        for _ in range(args.outside):
            self.vehicles.append(self._spawn(inside=False))

    def _take_id(self):
        if self.args.reuse_ids and self.retired_ids and self.rng.random() < 0.5:
            return self.retired_ids.pop(self.rng.randrange(len(self.retired_ids)))
        vehicle_id = self.next_id
        self.next_id += 1
        return vehicle_id

    def _spawn(self, inside, cls=None):
        args = self.args
        rng = self.rng
        bearing = rng.uniform(0.0, 360.0)
        if inside:
            # sqrt keeps the placement uniform over the disc instead of
            # clustering everything near the anchor
            radius = args.spread * math.sqrt(rng.random())
        else:
            radius = rng.uniform(args.outside_dist, args.outside_dist * 1.5)
        lat, lon = offset_metres(args.lat, args.lon, bearing, radius)

        stationary = rng.random() < args.stationary_frac
        heading = rng.uniform(0.0, 360.0)
        return {
            "vehicle_id": self._take_id(),
            "region_id": args.region,
            "speed": 0.0 if stationary else rng.uniform(3.0, args.speed or 14.0),
            "heading": HEADING_UNKNOWN if args.unknown_heading else int(round(heading)) % 360,
            "true_heading": heading,
            "lat": lat,
            "lon": lon,
            "alt": args.alt,
            "key_type": 0,
            "vehicle_type": cls if cls is not None else rng.choices(self.classes, self.weights)[0],
            "inside": inside,
        }

    def tick(self, dt):
        """Move everything, then replace a slice of the population."""
        for v in self.vehicles:
            if v["speed"]:
                v["lat"], v["lon"] = offset_metres(
                    v["lat"], v["lon"], v["true_heading"], v["speed"] * dt)

        # Churn is expressed per second so it stays the same whatever --hz is.
        # Each replacement retires one vehicle and spawns a fresh one, which is
        # what makes the renderer free a slot and allocate another.
        expected = self.args.churn * dt
        count = int(expected) + (1 if self.rng.random() < (expected % 1.0) else 0)
        for _ in range(min(count, len(self.vehicles))):
            index = self.rng.randrange(len(self.vehicles))
            retired = self.vehicles.pop(index)
            if self.args.reuse_ids:
                self.retired_ids.append(retired["vehicle_id"])
            self.vehicles.append(self._spawn(inside=retired["inside"]))


# ---------------------------------------------------------------------------

def write_truth_rows(handle, vehicles, now, now_ms, args):
    stamp = datetime.datetime.fromtimestamp(now)
    date = stamp.strftime("%Y-%m-%d")
    clock = "%02d:%02d:%02d.%03d" % (stamp.hour, stamp.minute, stamp.second,
                                     stamp.microsecond // 1000)
    for v in vehicles:
        # float32 is what actually goes on the wire, so record the value the
        # simulator will see rather than the double this script computed with.
        lat = struct.unpack("<f", struct.pack("<f", v["lat"]))[0]
        lon = struct.unpack("<f", struct.pack("<f", v["lon"]))[0]
        dist = distance_metres(args.camera_lat, args.camera_lon, lat, lon)
        expected = "true" if dist <= args.view_radius else "false"
        handle.write("%s,%s,%d,%d,%d,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%d,%s,%s,%.2f\n" % (
            date, clock, v["vehicle_id"], now_ms, v["region_id"], lat, lon,
            v["alt"], v["speed"], v["heading"], v["key_type"], v["vehicle_type"],
            CLASS_NAMES.get(v["vehicle_type"], "Other"), expected, dist))


def parse_classes(raw):
    codes = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            code = int(token)
        except ValueError:
            sys.exit("bad class code %r -- expected integers such as 0,1,2,3,4,5" % token)
        if code not in CLASS_NAMES:
            print("warning: class %d is not a known transmission code; it will "
                  "draw as Other" % code, file=sys.stderr)
        codes.append(code)
    if not codes:
        sys.exit("--classes selected nothing")
    return codes


def build_parser():
    parser = argparse.ArgumentParser(
        description="Send dummy RoadSideAlert packets to the simulator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=16004,
                        help="RoadSideAlert UDP port (16001 is ProbeVehicleData)")

    where = parser.add_argument_group("where")
    where.add_argument("--anchor", choices=sorted(ANCHORS), default=DEFAULT_ANCHOR,
                       help="named spawn point; overridden by any of "
                            "--lat/--lon/--alt/--heading given explicitly")
    where.add_argument("--lat", type=float)
    where.add_argument("--lon", type=float)
    where.add_argument("--alt", type=float)
    where.add_argument("--heading", type=float,
                       help="bearing the row is laid along and the vehicles face")

    what = parser.add_argument_group("what to send")
    what.add_argument("--classes", default="0,1,2,3,4,5",
                      help="transmission codes to draw from")
    what.add_argument("--spacing", type=float, default=15.0,
                      help="fixed mode: metres between vehicles")
    what.add_argument("--speed", type=float, default=0.0,
                      help="fixed mode: reported speed in m/s. population mode: "
                           "upper bound of the random speed (0 means 14)")
    what.add_argument("--drive", action="store_true",
                      help="fixed mode: move the row forward at --speed each tick")
    what.add_argument("--unknown-heading", action="store_true",
                      help="transmit 360 (the upstream 'no heading' sentinel) "
                           "instead of a bearing, to exercise the yaw-snap path")

    pop = parser.add_argument_group("population mode")
    pop.add_argument("--population", type=int, default=0,
                     help="number of vehicles inside the radius; 0 uses fixed mode")
    pop.add_argument("--spread", type=float, default=300.0,
                     help="metres around the anchor the population is scattered over")
    pop.add_argument("--churn", type=float, default=0.5,
                     help="vehicles retired and replaced per second; with "
                          "--population 30 the default gives a 60 s mean lifetime")
    pop.add_argument("--stationary-frac", type=float, default=0.3,
                     help="fraction of the population that reports speed 0 and "
                          "holds position")
    pop.add_argument("--outside", type=int, default=0,
                     help="extra vehicles placed BEYOND --view-radius; these "
                          "must be received and logged but never drawn")
    pop.add_argument("--outside-dist", type=float, default=2000.0,
                     help="metres from the anchor the --outside vehicles start at")
    pop.add_argument("--reuse-ids", action="store_true",
                     help="hand retired ids back out, reproducing the known "
                          "upstream id-reuse behaviour")
    pop.add_argument("--seed", type=int, help="make the run reproducible")

    verify = parser.add_argument_group("verification")
    verify.add_argument("--truth", metavar="FILE",
                        help="write every sent row to this CSV, in the same "
                             "column order as the simulator's RsaLog_*.csv")
    verify.add_argument("--camera-lat", type=float,
                        help="where the camera is, for the ExpectedDisplayed "
                             "and Distance columns (default: the anchor)")
    verify.add_argument("--camera-lon", type=float)
    verify.add_argument("--view-radius", type=float, default=1000.0,
                        help="must match RSA.ViewRadiusM in the simulator")

    run = parser.add_argument_group("run")
    run.add_argument("--hz", type=float, default=10.0,
                     help="packets per second; must exceed 1 to beat "
                          "RSA.HismKeepAliveSec")
    run.add_argument("--duration", type=float,
                     help="stop after this many seconds")
    run.add_argument("--region", type=int, default=1)
    run.add_argument("--base-id", type=int, default=9000,
                     help="first vehicle id; ids count up from here")
    run.add_argument("--once", action="store_true", help="send one packet and exit")
    run.add_argument("--dump-hex", action="store_true",
                     help="print the first packet as hex")
    return parser


def main():
    args = build_parser().parse_args()

    anchor_lat, anchor_lon, anchor_alt, anchor_heading = ANCHORS[args.anchor]
    if args.lat is None:
        args.lat = anchor_lat
    if args.lon is None:
        args.lon = anchor_lon
    if args.alt is None:
        args.alt = anchor_alt
    if args.heading is None:
        args.heading = anchor_heading
    if args.camera_lat is None:
        args.camera_lat = args.lat
    if args.camera_lon is None:
        args.camera_lon = args.lon

    if args.hz <= 0:
        sys.exit("--hz must be positive")
    if not args.once and args.hz <= 1.0:
        print("warning: --hz %.2f is at or below RSA.HismKeepAliveSec (1.0 s); "
              "vehicles will blink out between packets" % args.hz, file=sys.stderr)
    if args.population <= 0 and args.outside > 0:
        sys.exit("--outside needs --population")
    if args.outside and args.outside_dist <= args.view_radius:
        print("warning: --outside-dist %.0f is inside --view-radius %.0f, so the "
              "'outside' vehicles will be drawn after all"
              % (args.outside_dist, args.view_radius), file=sys.stderr)

    args.heading_code = HEADING_UNKNOWN if args.unknown_heading else int(round(args.heading)) % 360

    classes = parse_classes(args.classes)
    rng = random.Random(args.seed)
    population = None
    if args.population > 0:
        population = Population(args, classes, rng)
        vehicles = population.vehicles
    else:
        vehicles = make_row(args, classes)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    truth = open(args.truth, "w", encoding="utf-8") if args.truth else None
    if truth:
        truth.write(TRUTH_HEADER + "\n")

    print("RSA dummy feed -> %s:%d" % (args.host, args.port))
    print("  anchor '%s'  lat=%.7f lon=%.7f alt=%.1f heading=%s"
          % (args.anchor, args.lat, args.lon, args.alt,
             "360 (unknown)" if args.unknown_heading else "%.1f" % args.heading))
    if population:
        print("  population mode: %d inside (spread %.0f m) + %d outside (%.0f m), "
              "churn %.2f/s%s"
              % (args.population, args.spread, args.outside, args.outside_dist,
                 args.churn, ", ids reused" if args.reuse_ids else ""))
        print("  %d vehicles/packet, %.1f Hz, seed %s"
              % (len(vehicles), args.hz, args.seed if args.seed is not None else "random"))
        if args.outside:
            print("  the %d outside vehicles must appear in RsaLog_*.csv with "
                  "Displayed=false and never be drawn" % args.outside)
    else:
        print("  fixed mode: %d vehicles, %d bytes/packet, %.1f Hz%s"
              % (len(vehicles), HEADER_SIZE + len(vehicles) * RECORD_SIZE,
                 args.hz, " (single shot)" if args.once else ""))
        for v in vehicles:
            print("    id=%-5d %-11s lat=%.7f lon=%.7f"
                  % (v["vehicle_id"], CLASS_NAMES.get(v["vehicle_type"], "?"),
                     v["lat"], v["lon"]))
    if truth:
        print("  ground truth -> %s" % args.truth)
    print("  the MainCamera must be within RSA.ViewRadiusM (default 1000 m) of "
          "the anchor")

    period = 1.0 / args.hz
    started = time.time()
    sent = 0
    rows = 0
    try:
        while True:
            now = time.time()
            now_ms = int(now * 1000)
            vehicles = population.vehicles if population else vehicles

            packet = build_packet(vehicles, now_ms)
            if args.dump_hex and sent == 0:
                print("  first packet (%d bytes):\n    %s" % (len(packet), packet.hex()))
            sock.sendto(packet, (args.host, args.port))
            sent += 1
            rows += len(vehicles)
            if truth:
                write_truth_rows(truth, vehicles, now, now_ms, args)

            if args.once:
                break
            if args.duration and now - started >= args.duration:
                break

            if population:
                population.tick(period)
            elif args.drive and args.speed:
                advance_row(vehicles, args.heading, args.speed * period)

            if sent % max(1, int(args.hz)) == 0:
                live = len(vehicles)
                extra = ""
                if population:
                    extra = "  ids %d..%d" % (args.base_id, population.next_id - 1)
                print("\r  sent %d packets, %d rows, %d vehicles live%s"
                      % (sent, rows, live, extra), end="", flush=True)
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        if truth:
            truth.close()
        print("\n  stopped after %d packet%s, %d rows"
              % (sent, "" if sent == 1 else "s", rows))
        if args.truth:
            print("  ground truth written to %s" % args.truth)
            print("  compare against the simulator's RsaLog_*.csv, then run")
            print("    python tools/udp_debug/rsa_verify_display.py <RsaLog.csv>")


if __name__ == "__main__":
    main()
