from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from receivers.vehicle_info_receiver import (  # noqa: E402
    VEHICLE_INFO_SIZE,
    parse_vehicle_info_payload,
)


def parse_vehicle_array(data: bytes) -> List[dict]:
    vehicles: List[dict] = []
    vehicle_count = len(data) // VEHICLE_INFO_SIZE
    for index in range(vehicle_count):
        start = index * VEHICLE_INFO_SIZE
        end = start + VEHICLE_INFO_SIZE
        parsed = parse_vehicle_info_payload(data[start:end])
        if parsed is not None:
            vehicles.append(parsed)
    return vehicles


def run(listen_ip: str, port: int, bufsize: int, print_limit: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((listen_ip, port))

    print(f"[VehicleInfoArrayTest] listening on {listen_ip}:{port}")
    print(f"[VehicleInfoArrayTest] row_size={VEHICLE_INFO_SIZE} bytes")
    print("[VehicleInfoArrayTest] Ctrl+C to quit\n")

    packet_seq = 0
    try:
        while True:
            data, addr = sock.recvfrom(bufsize)
            packet_seq += 1
            vehicles = parse_vehicle_array(data)
            remainder = len(data) % VEHICLE_INFO_SIZE
            now = time.strftime("%H:%M:%S")

            print(
                f"[{now}] packet#{packet_seq} from={addr[0]}:{addr[1]} "
                f"bytes={len(data)} vehicles={len(vehicles)} remainder={remainder}"
            )

            for idx, vehicle in enumerate(vehicles[:print_limit]):
                loc = vehicle["location"]
                vel = vehicle["local_velocity"]
                ctrl = vehicle["control"]
                print(
                    f"  [{idx}] id='{vehicle['id']}' "
                    f"loc=({loc['x']:.3f}, {loc['y']:.3f}, {loc['z']:.3f}) "
                    f"vel=({vel['x']:.3f}, {vel['y']:.3f}, {vel['z']:.3f}) "
                    f"ctrl=(thr={ctrl['throttle']:.3f}, brk={ctrl['brake']:.3f}, "
                    f"steer={ctrl['steer_angle']:.3f})"
                )

            if len(vehicles) > print_limit:
                print(f"  ... {len(vehicles) - print_limit} more vehicles")
            print("")
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Receive a UDP datagram containing repeated Vehicle Info rows.",
    )
    parser.add_argument("--listen-ip", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--bufsize", type=int, default=65535)
    parser.add_argument(
        "--print-limit",
        type=int,
        default=10,
        help="Maximum vehicles to print per UDP datagram.",
    )
    args = parser.parse_args()

    try:
        run(args.listen_ip, args.port, args.bufsize, args.print_limit)
    except KeyboardInterrupt:
        print("\n[VehicleInfoArrayTest] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
