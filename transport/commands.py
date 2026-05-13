from __future__ import annotations

# udp_manual.py
import socket
import struct
from typing import Any, Dict

import transport.protocol_defs as proto


def build_udp_payload(fields, values_by_variable_name: Dict[str, Any]) -> bytes:
    payload = bytearray()
    for field in fields:
        value = values_by_variable_name.get(field.variable_name, 0)
        if field.is_string:
            raw = str(value).encode("utf-8")
            payload.extend(raw[:field.length].ljust(field.length, b"\x00"))
            continue
        payload.extend(struct.pack(proto.LITTLE_ENDIAN + field.struct_char, value))
    return bytes(payload)


def send_udp_payload(
    udp_sock: socket.socket,
    payload: bytes,
    ip: str,
    port: int,
    label: str,
):
    udp_sock.sendto(payload, (ip, port))
    print(f"[SEND][UDP] {label} -> {ip}:{port} size={len(payload)}B")


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

    send_udp_payload(udp_sock, payload, proto.UDP_IP, proto.UDP_PORT, "ManualCommand")
    print(
        f"[SEND][UDP] ManualCommand values "
        f"(thr={throttle:.3f}, brk={brake:.3f}, steer={steer:.3f})"
    )


def send_transform_control_udp(
    udp_sock: socket.socket,
    pos_x: float,
    pos_y: float,
    pos_z: float,
    rot_x: float,
    rot_y: float,
    rot_z: float,
    steer_angle: float,
):
    """
    TransformControl UDP 송신
    payload:
        pos(x,y,z)
        rot(x,y,z)
        steer_angle

    double x7 = 56 bytes
    """

    payload = struct.pack(
        proto.TRANSFORM_CONTROL_FMT,
        pos_x,
        pos_y,
        pos_z,
        rot_x,
        rot_y,
        rot_z,
        steer_angle,
    )

    if len(payload) != proto.TRANSFORM_CONTROL_SIZE:
        raise RuntimeError(
            f"Transform payload size mismatch: {len(payload)} "
            f"(expected {proto.TRANSFORM_CONTROL_SIZE})"
        )

    send_udp_payload(udp_sock, payload, proto.UDP_IP_TR, proto.UDP_PORT_TR, "TransformControl")
    print(
        f"[SEND][UDP] TransformControl values "
        f"pos=({pos_x:.3f},{pos_y:.3f},{pos_z:.3f}) "
        f"rot=({rot_x:.3f},{rot_y:.3f},{rot_z:.3f}) "
        f"steer={steer_angle:.3f} size={len(payload)}B"
    )
