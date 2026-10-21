from __future__ import annotations

"""OpenMap (0x01010003) check against a running simulator.

1. Opens --map and waits until the simulator answers (it answers only once the map is Ready).
2. Opens the same map again: already open, so the answer should be immediate.
3. Opens a map that does not exist: expects InvalidParam.

    python tools/openmap_check.py --map pangyo
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto                       # noqa: E402
from transport.proto_client import ProtoCallError, ProtoClient  # noqa: E402


def timed_open(client: ProtoClient, map_name: str) -> None:
    start = time.time()
    try:
        resp = client.call("OpenMap", map_name=map_name)
        print(f"  OK   {resp}  ({time.time() - start:.1f}s)")
    except ProtoCallError as e:
        print(f"  FAIL {e}  ({time.time() - start:.1f}s)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--map", required=True, help="map name as listed by GetMapCatalog")
    ap.add_argument("--timeout", type=float, default=310.0, help="response timeout (s); server gives up at 300")
    args = ap.parse_args()

    with ProtoClient(args.ip, args.port, timeout=args.timeout) as client:
        client.load_schema()

        print(f"[1] OpenMap {args.map} (waits until Ready)")
        timed_open(client, args.map)

        print(f"[2] OpenMap {args.map} again (expect immediate OK)")
        timed_open(client, args.map)

        print("[3] OpenMap __no_such_map__ (expect InvalidParam)")
        timed_open(client, "__no_such_map__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
