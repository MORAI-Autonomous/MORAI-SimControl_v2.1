# tcp_transport.py
import socket
import struct
from typing import Optional, Dict, Any, Tuple

import protocol_defs as proto


# =========================
# TCP Helpers
# =========================
def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed by peer")
        buf.extend(chunk)
    return bytes(buf)


def recv_header_synced(sock: socket.socket) -> bytes:
    """
    Stream에서 MAGIC 동기화 후, 올바른 header를 찾아 리턴.
    (TCP는 byte stream이라 boundary가 없으니 resync 필요)
    """
    while True:
        b = recv_exact(sock, 1)
        if b[0] != proto.MAGIC:
            continue

        rest = recv_exact(sock, proto.HEADER_SIZE - 1)
        header_bytes = b + rest

        _, msg_class, msg_type, payload_size, _, _ = struct.unpack(proto.HEADER_FMT, header_bytes)

        if msg_class not in proto.VALID_MSG_CLASSES:
            continue
        if msg_type not in proto.VALID_MSG_TYPES:
            continue
        if payload_size > 1024 * 1024:
            continue

        return header_bytes


def recv_packet(sock: socket.socket) -> Tuple[int, int, int, int, int, bytes]:
    """
    return: (msg_class, msg_type, payload_size, request_id, flag, payload)
    """
    header_bytes = recv_header_synced(sock)
    _, msg_class, msg_type, payload_size, request_id, flag = struct.unpack(
        proto.HEADER_FMT, header_bytes
    )

    if payload_size < 0 or payload_size > 1024 * 1024:
        raise ValueError(f"Invalid payload_size: {payload_size}")

    payload = recv_exact(sock, payload_size) if payload_size > 0 else b""
    return msg_class, msg_type, payload_size, request_id, flag, payload


def build_header(msg_class: int, msg_type: int, payload_size: int, request_id: int, flag: int = 0) -> bytes:
    return struct.pack(proto.HEADER_FMT, proto.MAGIC, msg_class, msg_type, payload_size, request_id, flag)


# =========================
# Commands (Send)
# =========================
def send_fixed_step(sock: socket.socket, request_id: int, step_count: int):
    payload = struct.pack("<I", step_count)  # uint32
    header = build_header(proto.MSG_CLASS_REQ, proto.MSG_TYPE_FIXED_STEP, len(payload), request_id, proto.FLAG)
    sock.sendall(header + payload)


def send_get_status(sock: socket.socket, request_id: int):
    payload = b""
    header = build_header(proto.MSG_CLASS_REQ, proto.MSG_TYPE_GET_STATUS, len(payload), request_id, proto.FLAG)
    sock.sendall(header + payload)
    print(f"[SEND][TCP] GetStatus(0x1201) rid={request_id}")


def send_save_data(sock: socket.socket, request_id: int):
    payload = b""
    header = build_header(proto.MSG_CLASS_REQ, proto.MSG_TYPE_SAVE_DATA, len(payload), request_id, proto.FLAG)
    sock.sendall(header + payload)


# =========================
# Parsers
# =========================
def parse_result_code(payload: bytes) -> Optional[Tuple[int, int]]:
    if len(payload) != proto.RESULT_SIZE:
        return None
    return struct.unpack(proto.RESULT_FMT, payload)


def parse_get_status_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) != proto.GET_STATUS_PAYLOAD_SIZE:
        return None
    result_code, detail_code = struct.unpack_from(proto.RESULT_FMT, payload, 0)
    fixed_delta, step_index, seconds, nanos = struct.unpack_from(proto.STATUS_FMT, payload, proto.RESULT_SIZE)
    return {
        "result_code": result_code,
        "detail_code": detail_code,
        "fixed_delta": fixed_delta,
        "step_index": step_index,
        "seconds": seconds,
        "nanos": nanos,
    }