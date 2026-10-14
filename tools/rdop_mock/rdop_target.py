"""Point the simulator's RDOP interface files at the mock, dev or prod server.

  python rdop_target.py            show the current target of each file
  python rdop_target.py local      127.0.0.1:10033 (rdop_mock_server.py)
  python rdop_target.py dev        112.175.92.234:10033
  python rdop_target.py prod       10.55.22.161:10033
  python rdop_target.py 192.168.0.5:10033   any other address

The simulator repository is given by --sim-root or the MORAI_SIM_ROOT environment variable:
  python rdop_target.py local --sim-root D:/Dev/clone_morai_world_ue5.8

Only destinationAddr.ip/port is rewritten, in place, so formatting and line endings are kept.
CameraLocationPost is left alone: it goes to a separate control server, not RDOP.
The editor reads these files when a mode is entered, so re-enter the mode after switching.
"""

import argparse
import os
import re
import sys

TARGETS = {
    "local": ("127.0.0.1", 10033),
    "dev": ("112.175.92.234", 10033),
    "prod": ("10.55.22.161", 10033),
}

FILES = [
    os.path.join("Monitoring", "CameraLocationGet.json"),
    os.path.join("Traffic", "SimulationReplayGet.json"),
    os.path.join("Traffic", "SimulationStartGet.json"),
    os.path.join("Traffic", "SimulationResultPost.json"),
]

ADDR_RE = re.compile(r'("destinationAddr"\s*:\s*\{\s*"ip"\s*:\s*")([^"]*)("\s*,\s*"port"\s*:\s*)(\d+)')


def main():
    parser = argparse.ArgumentParser(description="Point the simulator's RDOP interface files at a server")
    parser.add_argument("target", nargs="?", help="|".join(TARGETS) + " or <ip>:<port>; omit to show")
    parser.add_argument("--sim-root", default=os.environ.get("MORAI_SIM_ROOT"),
                        help="simulator repository root (default: MORAI_SIM_ROOT)")
    args = parser.parse_args()

    if not args.sim_root:
        sys.exit("simulator repository not given: use --sim-root <path> or set MORAI_SIM_ROOT")
    interface_root = os.path.join(os.path.abspath(args.sim_root), "Content", "NetworkInterface")
    if not os.path.isdir(interface_root):
        sys.exit("not a simulator repository (no Content/NetworkInterface): " + args.sim_root)

    target = args.target.lower() if args.target else None
    if target is not None and target not in TARGETS:
        # Any other address as ip:port, e.g. a mock running on another PC
        ip, sep, port = target.rpartition(":")
        if not sep or not ip or not port.isdigit():
            sys.exit("usage: rdop_target.py [{}|<ip>:<port>]".format("|".join(TARGETS)))
        TARGETS[target] = (ip, int(port))

    for rel in FILES:
        path = os.path.join(interface_root, rel)
        # newline="" keeps CRLF/LF as it is in the file
        with open(path, "r", encoding="utf-8", newline="") as f:
            text = f.read()
        match = ADDR_RE.search(text)
        if match is None:
            print("{:45s} destinationAddr not found, skipped".format(rel))
            continue

        current = "{}:{}".format(match.group(2), match.group(4))
        if target is None:
            print("{:45s} {}".format(rel, current))
            continue

        ip, port = TARGETS[target]
        text = ADDR_RE.sub(lambda m: "{}{}{}{}".format(m.group(1), ip, m.group(3), port), text, count=1)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print("{:45s} {} -> {}:{}".format(rel, current, ip, port))


if __name__ == "__main__":
    main()
