from __future__ import annotations

import socket
import struct
from typing import Any, Dict, List, Optional, Tuple

from transport.message_schema import (
    get_response_message,
    pack_message_payload,
    unpack_fields,
    unpack_message_payload,
)
import transport.protocol_defs as proto


# ============================================================
# Low-level recv / send helpers
# ============================================================

def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed by peer")
        buf.extend(chunk)
    return bytes(buf)


def recv_header_synced(sock: socket.socket) -> bytes:
    """Read a valid TCP header after syncing on the MAGIC byte."""
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
    """Return `(msg_class, msg_type, payload_size, request_id, flag, payload)`."""
    header_bytes = recv_header_synced(sock)
    _, msg_class, msg_type, payload_size, request_id, flag = struct.unpack(
        proto.HEADER_FMT, header_bytes
    )
    if payload_size < 0 or payload_size > 1024 * 1024:
        raise ValueError(f"Invalid payload_size: {payload_size}")

    payload = recv_exact(sock, payload_size) if payload_size > 0 else b""
    return msg_class, msg_type, payload_size, request_id, flag, payload


def build_header(
    msg_class: int,
    msg_type: int,
    payload_size: int,
    request_id: int,
    flag: int = 0,
) -> bytes:
    return struct.pack(
        proto.HEADER_FMT,
        proto.MAGIC, msg_class, msg_type, payload_size, request_id, flag,
    )


def _send_packet(
    sock: socket.socket,
    request_id: int,
    msg_type: int,
    payload: bytes,
    log: str = "",
) -> None:
    """Build the header, send the packet, and emit optional send log."""
    header = build_header(proto.MSG_CLASS_REQ, msg_type, len(payload), request_id, proto.FLAG)
    sock.sendall(header + payload)
    if log:
        print(f"[SEND][TCP] {log} rid={request_id}")


# ============================================================
# Payload builders
# ============================================================

def build_manual_control_by_id_payload(
    entity_id: str,
    throttle: float,
    brake: float,
    steer_angle: float,
) -> bytes:
    return pack_message_payload(
        proto.MSG_TYPE_MANUAL_CONTROL_BY_ID_COMMAND,
        {
            "entity_id": entity_id,
            "throttle": throttle,
            "brake": brake,
            "steer_angle": steer_angle,
        },
    )


def build_transform_control_by_id_payload(
    entity_id: str,
    pos_x: float, pos_y: float, pos_z: float,
    rot_x: float, rot_y: float, rot_z: float,
    steer_angle: float,
    speed: float,
) -> bytes:
    return pack_message_payload(
        proto.MSG_TYPE_TRANSFORM_CONTROL_BY_ID_COMMAND,
        {
            "entity_id": entity_id,
            "pos_x": pos_x,
            "pos_y": pos_y,
            "pos_z": pos_z,
            "rot_x": rot_x,
            "rot_y": rot_y,
            "rot_z": rot_z,
            "steer_angle": steer_angle,
            "speed": speed,
        },
    )


def build_set_trajectory_payload(
    entity_id: str,
    follow_mode: int,
    trajectory_name: str,
    points: List[Tuple[float, float, float, float]],
) -> bytes:
    return pack_message_payload(
        proto.MSG_TYPE_SET_TRAJECTORY_COMMAND,
        {
            "entity_id": entity_id,
            "follow_mode": follow_mode,
            "trajectory_name": trajectory_name,
            "point_count": len(points),
        },
        repeated_items=[
            {
                "points[].x": x,
                "points[].y": y,
                "points[].z": z,
                "points[].time": t,
            }
            for x, y, z, t in points
        ],
    )


# ============================================================
# Send commands
# ============================================================

def send_get_status(sock: socket.socket, request_id: int) -> None:
    _send_packet(sock, request_id, proto.MSG_TYPE_GET_SIMULATION_TIME_STATUS, b"",
                 "GetStatus(0x1101)")


def send_get_simulator_status(sock: socket.socket, request_id: int) -> None:
    _send_packet(sock, request_id, proto.MSG_TYPE_GET_SIMULATOR_STATUS, b"",
                 "GetSimulatorStatus(0x1001)")


def send_simulation_time_mode_command(
    sock: socket.socket,
    request_id: int,
    mode: int,
    target_fps: int = 60,
    physics_delta_time: int = 10,
    rtf: int = 1,
    user_control: int = 0,
) -> None:
    """mode: 1=variable, 2=fixed."""
    if mode not in (proto.TIME_MODE_VARIABLE, proto.TIME_MODE_FIXED):
        raise ValueError(f"Unsupported simulation time mode: {mode}")

    payload_values = {
        "mode": int(mode),
        "target_fps": int(target_fps),
        "physics_delta_time": int(physics_delta_time),
        "rtf": int(rtf) if mode == proto.TIME_MODE_FIXED else 0,
        "user_control": int(user_control) if mode == proto.TIME_MODE_FIXED else 0,
    }
    log_text = (
        "SetSimulationTimeModeCommand(0x1102) "
        f"mode={mode} target_fps={target_fps} "
        f"physics_delta_time={physics_delta_time} "
        f"rtf={payload_values['rtf']} user_control={payload_values['user_control']}"
    )

    payload = pack_message_payload(
        proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND,
        payload_values,
    )
    _send_packet(
        sock,
        request_id,
        proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND,
        payload,
        log_text,
    )


def send_fixed_step(sock: socket.socket, request_id: int, step_count: int) -> None:
    payload = pack_message_payload(
        proto.MSG_TYPE_FIXED_STEP,
        {"step_count": step_count},
    )
    _send_packet(sock, request_id, proto.MSG_TYPE_FIXED_STEP, payload)


def send_save_data(sock: socket.socket, request_id: int) -> None:
    _send_packet(sock, request_id, proto.MSG_TYPE_SAVE_DATA, b"")


def send_create_object(
    sock: socket.socket,
    request_id: int,
    entity_type: int,
    pos_x: float, pos_y: float, pos_z: float,
    rot_x: float, rot_y: float, rot_z: float,
    driving_mode: int,
    ground_vehicle_model: int,
) -> None:
    payload = pack_message_payload(
        proto.MSG_TYPE_CREATE_OBJECT,
        {
            "entity_type": entity_type,
            "pos_x": pos_x,
            "pos_y": pos_y,
            "pos_z": pos_z,
            "rot_x": rot_x,
            "rot_y": rot_y,
            "rot_z": rot_z,
            "driving_mode": driving_mode,
            "ground_vehicle_model": ground_vehicle_model,
        },
    )
    _send_packet(sock, request_id, proto.MSG_TYPE_CREATE_OBJECT, payload,
                 "CreateObject(0x1301)")


def send_manual_control_by_id(
    sock: socket.socket,
    request_id: int,
    entity_id: str,
    throttle: float,
    brake: float,
    steer_angle: float,
) -> None:
    payload = build_manual_control_by_id_payload(entity_id, throttle, brake, steer_angle)
    _send_packet(sock, request_id, proto.MSG_TYPE_MANUAL_CONTROL_BY_ID_COMMAND, payload)


def send_transform_control_by_id(
    sock: socket.socket,
    request_id: int,
    entity_id: str,
    pos_x: float, pos_y: float, pos_z: float,
    rot_x: float, rot_y: float, rot_z: float,
    steer_angle: float,
    speed: float,
) -> None:
    payload = build_transform_control_by_id_payload(
        entity_id, pos_x, pos_y, pos_z, rot_x, rot_y, rot_z, steer_angle, speed,
    )
    _send_packet(sock, request_id, proto.MSG_TYPE_TRANSFORM_CONTROL_BY_ID_COMMAND, payload)


def send_set_trajectory(
    sock: socket.socket,
    request_id: int,
    entity_id: str,
    follow_mode: int,
    trajectory_name: str,
    points: List[Tuple[float, float, float, float]],
) -> None:
    payload = build_set_trajectory_payload(entity_id, follow_mode, trajectory_name, points)
    print(
        f"[SEND][TCP] SetTrajectory payload_size={len(payload)} "
        f"packet_size={proto.HEADER_SIZE + len(payload)} "
        f"points={len(points)} rid={request_id}"
    )
    _send_packet(sock, request_id, proto.MSG_TYPE_SET_TRAJECTORY_COMMAND, payload,
                 f"SetTrajectory(0x1304) id={entity_id} points={len(points)}")


def send_delete_object(sock: socket.socket, request_id: int, entity_id: str) -> None:
    payload = pack_message_payload(
        proto.MSG_TYPE_DELETE_OBJECT,
        {"entity_id": entity_id},
    )
    print(
        f"[SEND][TCP] DeleteObject payload_size={len(payload)} "
        f"packet_size={proto.HEADER_SIZE + len(payload)} rid={request_id}"
    )
    _send_packet(sock, request_id, proto.MSG_TYPE_DELETE_OBJECT, payload,
                 f"DeleteObject(0x1305) id={entity_id}")


def send_load_suite(sock: socket.socket, request_id: int, suite_path: str) -> None:
    payload = pack_message_payload(
        proto.MSG_TYPE_LOAD_SUITE,
        {"suite_path": suite_path},
    )
    _send_packet(sock, request_id, proto.MSG_TYPE_LOAD_SUITE, payload,
                 f"LoadSuite(0x1402) suite_path={suite_path}")


def send_scenario_status(sock: socket.socket, request_id: int) -> None:
    _send_packet(sock, request_id, proto.MSG_TYPE_SCENARIO_STATUS, b"",
                 "ScenarioStatus(0x1504)")


def send_scenario_control(
    sock: socket.socket,
    request_id: int,
    command: int,
    scenario_name: str = "",
) -> None:
    payload = pack_message_payload(
        proto.MSG_TYPE_SCENARIO_CONTROL,
        {
            "command": command,
            "scenario_name": scenario_name,
        },
    )
    _send_packet(sock, request_id, proto.MSG_TYPE_SCENARIO_CONTROL, payload,
                 f"ScenarioControl(0x1505) command={command} scenario_name={scenario_name!r}")


def send_active_suite_status(sock: socket.socket, request_id: int) -> None:
    _send_packet(sock, request_id, proto.MSG_TYPE_ACTIVE_SUITE_STATUS, b"",
                 "ActiveSuiteStatus(0x1401)")


# ============================================================
# Response parsers
# ============================================================

def parse_get_simulator_status_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) != proto.GET_SIMULATOR_STATUS_SIZE:
        return None
    try:
        values, offset = unpack_fields(get_response_message(0x1001).fields, payload)
    except ValueError:
        return None
    if offset != len(payload):
        return None
    if values.get("result_code") != 0:
        return values
    if values.get("state") not in proto.SIMULATOR_STATE_MAP:
        return None
    return values


def parse_get_simulator_status_notification_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    """
    Parse protobuf-encoded datamodel::SimulatorStatus notification.

    Expected minimal wire format for `message SimulatorStatus { enum state = 1; }`:
      0x08 <varint(state)>
    """
    if not payload:
        return None

    offset = 0
    state: Optional[int] = None
    while offset < len(payload):
        key = payload[offset]
        offset += 1
        field_number = key >> 3
        wire_type = key & 0x07

        if wire_type != 0:
            return None

        shift = 0
        value = 0
        while True:
            if offset >= len(payload) or shift > 63:
                return None
            b = payload[offset]
            offset += 1
            value |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7

        if field_number == 1:
            state = int(value)
        else:
            # message currently expected to contain only state enum
            continue

    if state is None or state not in proto.SIMULATOR_STATE_MAP:
        return None
    return {"state": state}

def parse_result_code(payload: bytes) -> Optional[Tuple[int, int]]:
    if len(payload) != proto.RESULT_SIZE:
        return None
    try:
        values, offset = unpack_fields(get_response_message(0x1201).fields, payload)
    except ValueError:
        return None
    if offset != len(payload):
        return None
    return values["result_code"], values["detail_code"]


def parse_get_status_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) != proto.GET_STATUS_SIZE:
        return None

    try:
        values, _, offset = unpack_message_payload(0x1101, payload, direction="response")
    except ValueError:
        return None
    if offset != len(payload):
        return None
    if values.get("mode") not in (proto.TIME_MODE_VARIABLE, proto.TIME_MODE_FIXED):
        return None
    return values


def parse_set_simulation_time_mode_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) != proto.SET_SIM_TIME_MODE_RESP_SIZE:
        return None
    try:
        values, _, offset = unpack_message_payload(0x1102, payload, direction="response")
    except ValueError:
        return None
    return values if offset == len(payload) else None


def parse_create_object_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) < proto.RESULT_SIZE + 4:
        return None
    try:
        values, _, offset = unpack_message_payload(0x1301, payload, direction="response")
    except ValueError:
        return None
    if offset != len(payload):
        return None
    values["object_id_length"] = len(values["object_id"].encode("utf-8"))
    return values


def parse_active_suite_status_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) < proto.RESULT_SIZE + proto.ACTIVE_SUITE_STATUS_RESP_MIN_SIZE:
        return None

    try:
        values, repeated_items, offset = unpack_message_payload(
            0x1401,
            payload,
            direction="response",
            repeated_count_field="scenario_list_size",
        )
    except ValueError as e:
        print(f"[PARSE][ActiveSuiteStatus] {e}")
        return None

    if offset != len(payload):
        return None
    if values["result_code"] != 0:
        print(
            f"[PARSE][ActiveSuiteStatus] Server error: "
            f"result_code={values['result_code']} detail_code={values['detail_code']}"
        )
        return None

    return {
        "result_code": values["result_code"],
        "detail_code": values["detail_code"],
        "active_suite_name": values["active_suite_name"],
        "active_scenario_name": values["active_scenario_name"],
        "scenario_list_size": values["scenario_list_size"],
        "scenario_list": [item["scenario_list[].name"] for item in repeated_items],
    }


def parse_scenario_status_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if len(payload) == 12:
        try:
            result_code, detail_code, state = struct.unpack("<III", payload)
        except struct.error as e:
            print(f"[PARSE][ScenarioStatus] {e}")
            return None
        if state not in (1, 2, 3, 4):
            return None
        return {
            "result_code": result_code,
            "detail_code": detail_code,
            "state": state,
            "name": "",
        }
    try:
        values, _, offset = unpack_message_payload(0x1504, payload, direction="response")
    except ValueError as e:
        print(f"[PARSE][ScenarioStatus] {e}")
        return None
    if offset != len(payload):
        return None
    if values.get("state") not in (1, 2, 3, 4):
        return None
    return values


def parse_scenario_status_notification_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    """
    Parse protobuf-like scenario status notification.

    Expected minimal wire format:
      field #1: varint state
      field #2: length-delimited utf-8 scenario name
    """
    if not payload:
        return None

    offset = 0
    state: Optional[int] = None
    name = ""
    while offset < len(payload):
        key = payload[offset]
        offset += 1
        field_number = key >> 3
        wire_type = key & 0x07

        if wire_type == 0:
            shift = 0
            value = 0
            while True:
                if offset >= len(payload):
                    return None
                b = payload[offset]
                offset += 1
                value |= (b & 0x7F) << shift
                if (b & 0x80) == 0:
                    break
                shift += 7
                if shift > 35:
                    return None
            if field_number == 1:
                state = value
        elif wire_type == 2:
            shift = 0
            length = 0
            while True:
                if offset >= len(payload):
                    return None
                b = payload[offset]
                offset += 1
                length |= (b & 0x7F) << shift
                if (b & 0x80) == 0:
                    break
                shift += 7
                if shift > 35:
                    return None
            end = offset + length
            if end > len(payload):
                return None
            if field_number == 2:
                try:
                    name = payload[offset:end].decode("utf-8")
                except UnicodeDecodeError:
                    return None
            offset = end
        else:
            return None

    if state not in (1, 2, 3, 4):
        return None
    return {"state": state, "name": name}
