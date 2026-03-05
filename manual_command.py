# udp_manual.py
import socket
import struct

import protocol_defs as proto


def send_manual_udp(
    udp_sock: socket.socket,
    throttle: float,
    brake: float,
    steer: float,
):
    """
    ManualCommand UDP 송신
    payload: <ddd (float64 x3) = 24 bytes
    """
    payload = struct.pack(proto.MANUAL_FMT, throttle, brake, steer)
    if len(payload) != proto.MANUAL_SIZE:
        raise RuntimeError(
            f"Manual payload size mismatch: {len(payload)} (expected {proto.MANUAL_SIZE})"
        )

    udp_sock.sendto(payload, (proto.UDP_IP, proto.UDP_PORT))
    print(
        f"[SEND][UDP] ManualCommand -> {proto.UDP_IP}:{proto.UDP_PORT} "
        f"(thr={throttle:.3f}, brk={brake:.3f}, steer={steer:.3f}) size={len(payload)}B"
    )