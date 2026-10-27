from __future__ import annotations

"""Regression check for the simulator's 21 legacy TCP opcodes (0x1001 ... 0x1602).

The responses are checked with SimControl's own parsers (transport/tcp_transport.py), which demand
the exact byte layout. So a simulator change that alters a legacy response in any way - size, field
order, result code - fails here, without anyone driving the GUI.

Phase A (default, safe in any simulator state; changes nothing):
  - status queries: 0x1001 0x1002 0x1101 0x1401 0x1504
  - every opcode with a payload gets a malformed one and must answer InvalidParam (102) with a bare
    8-byte ResultCode - checks the decoders reject bad input instead of executing or crashing
  - unknown ids / names, unknown opcodes (NotSupported 202)
  - failures show their detail_code (ErrorReason); an unknown Proto opcode answers with a Reply

Phase B (--scenario-run): plays a scenario in fixed-step mode and exercises the entity commands:
  (LoadSuite) -> SetSimulationTimeMode fixed -> Play -> FixedStep -> CreateObject -> GetVehicleInfo
  -> ManualControl / TransformControl / SetTrajectory -> SaveData -> DeleteObject -> Stop -> variable

Never sent: 0x1005 ShutdownSimulator. Not exercised with valid payloads (they switch the world or
the mode): 0x1003 SetSimulatorMode, 0x1004 LoadMap, 0x1601 LoadTrafficScenario, 0x1602 TrafficGenerate.

    python tools/legacy_regression.py
    python tools/legacy_regression.py --scenario-run --scenario CTO-1721
    python tools/legacy_regression.py --scenario-run --suite-path "C:/.../CTO-1721 Project Suite.msuite"
"""

import argparse
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import transport.protocol_defs as proto  # noqa: E402
import transport.tcp_transport as tcp    # noqa: E402
from transport.proto_client import decode_reply  # noqa: E402

OK, INVALID_STATE, INVALID_PARAM, FAILED, NOT_SUPPORTED = 0, 101, 102, 200, 202
NONZERO = -1  # any failure code

RESULT_NAMES = {0: "OK", 101: "InvalidState", 102: "InvalidParam", 200: "Failed", 201: "Timeout",
                202: "NotSupported"}


def u32(v: int) -> bytes:
    return struct.pack("<I", v)


def i32(v: int) -> bytes:
    return struct.pack("<i", v)


def lp(text: str) -> bytes:
    """[uint32 len][utf-8]"""
    b = text.encode("utf-8")
    return u32(len(b)) + b


# ------------------------------------------------------------------------------------------------
# Connection: own receive loop, because tcp.recv_packet skips msg_types outside VALID_MSG_TYPES
# (the unknown-opcode checks need to see those responses).
# ------------------------------------------------------------------------------------------------
class Conn:
    def __init__(self, ip: str, port: int, timeout: float):
        self.sock = socket.create_connection((ip, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.timeout = timeout
        self.rid = 0

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def raw(self, opcode: int, payload: bytes, timeout: Optional[float] = None) -> Optional[bytes]:
        self.rid += 1
        header = struct.pack(proto.HEADER_FMT, proto.MAGIC, proto.MSG_CLASS_REQ, opcode,
                             len(payload), self.rid, proto.FLAG)
        self.sock.sendall(header + payload)
        return self._wait(opcode, self.rid, timeout)

    def call(self, send_fn: Callable, opcode: int, timeout: Optional[float] = None, **kwargs) -> Optional[bytes]:
        """Sends with SimControl's own request builder, so the request side is checked too."""
        self.rid += 1
        send_fn(self.sock, self.rid, **kwargs)
        return self._wait(opcode, self.rid, timeout)

    def _wait(self, opcode: int, rid: int, timeout: Optional[float]) -> Optional[bytes]:
        self.sock.settimeout(timeout or self.timeout)
        try:
            while True:
                header = self._recv_exact(proto.HEADER_SIZE)
                magic, msg_class, msg_type, size, resp_rid, _flag = struct.unpack(proto.HEADER_FMT, header)
                if magic != proto.MAGIC:
                    raise ConnectionError(f"bad magic 0x{magic:02X}")
                body = self._recv_exact(size) if size else b""
                if msg_class == proto.MSG_CLASS_RESP and msg_type == opcode and resp_rid == rid:
                    return body
                # notifications and other responses are skipped
        except socket.timeout:
            return None

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed by simulator")
            buf.extend(chunk)
        return bytes(buf)


# ------------------------------------------------------------------------------------------------
# Checks
# ------------------------------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.rows: List[tuple] = []

    def check(self, name: str, opcode: int, payload: Optional[bytes], want: int,
              parser: Optional[Callable[[bytes], Any]] = None,
              verify: Optional[Callable[[Any], Optional[str]]] = None) -> Any:
        """want: expected result code, a tuple of acceptable ones, or NONZERO (any failure). A failure
        must be a bare 8-byte ResultCode; a success must satisfy `parser` (exact layout) and `verify`
        (content)."""
        if payload is None:
            return self._add(name, opcode, False, "no response (timeout)")
        if len(payload) < proto.RESULT_SIZE:
            return self._add(name, opcode, False, f"payload {len(payload)}B < ResultCode")
        rc, detail = struct.unpack_from(proto.RESULT_FMT, payload)
        got = f"{rc}({RESULT_NAMES.get(rc, '?')}) {len(payload)}B"
        if detail != 0:
            got += f" detail={detail}({proto.ERROR_REASON_MAP.get(detail, '?')})"

        allowed = want if isinstance(want, tuple) else (want,)
        if (want == NONZERO and rc == 0) or (want != NONZERO and rc not in allowed):
            wanted = "failure" if want == NONZERO else "/".join(RESULT_NAMES.get(w, str(w)) for w in allowed)
            return self._add(name, opcode, False, f"result {got}, want {wanted}")
        if rc != 0:
            ok = len(payload) == proto.RESULT_SIZE
            return self._add(name, opcode, ok, got if ok else f"{got}: failure must be 8B")

        parsed = parser(payload) if parser else tcp.parse_result_code(payload)
        if parsed is None:
            return self._add(name, opcode, False, f"{got}: layout does not parse")
        problem = verify(parsed) if verify else None
        self._add(name, opcode, problem is None, problem or got)
        return parsed

    def check_reply(self, name: str, opcode: int, payload: Optional[bytes], want: int, want_reason: int) -> None:
        """A Proto opcode answers with a datamodel.Reply instead of the 8-byte ResultCode."""
        if payload is None:
            return self._add(name, opcode, False, "no response (timeout)")
        try:
            code, reason, message, _body = decode_reply(payload)
        except Exception as e:  # noqa: BLE001 - any parse error is a failed check
            return self._add(name, opcode, False, f"not a Reply ({len(payload)}B): {e}")
        got = (f"{code}({RESULT_NAMES.get(code, '?')}) "
               f"reason={reason}({proto.ERROR_REASON_MAP.get(reason, '?')}) \"{message}\"")
        return self._add(name, opcode, code == want and reason == want_reason, got)

    def _add(self, name: str, opcode: int, ok: bool, note: str) -> None:
        self.rows.append((ok, opcode, name, note))
        print(f"  [{'PASS' if ok else 'FAIL'}] 0x{opcode:08X} {name:<46} {note}")
        return None

    def summary(self) -> int:
        failed = [r for r in self.rows if not r[0]]
        covered = sorted({r[1] for r in self.rows if r[1] in proto.VALID_MSG_TYPES})
        print()
        print(f"{len(self.rows) - len(failed)} passed, {len(failed)} failed")
        print("legacy opcodes covered: " + " ".join(f"0x{o:04X}" for o in covered))
        for ok, opcode, name, note in failed:
            print(f"  FAIL 0x{opcode:08X} {name}: {note}")
        return 1 if failed else 0


# ------------------------------------------------------------------------------------------------
# Phase A: safe in any state
# ------------------------------------------------------------------------------------------------
def phase_a(c: Conn, r: Report) -> None:
    print("== Phase A: status queries")
    r.check("GetSimulatorStatus", 0x1001, c.call(tcp.send_get_simulator_status, 0x1001), OK,
            tcp.parse_get_simulator_status_payload)
    r.check("GetSimulatorMode", 0x1002, c.call(tcp.send_get_simulator_mode, 0x1002), OK,
            tcp.parse_get_simulator_mode_payload)
    # These depend on the simulator state (no scenario / suite yet answers a failure code); either
    # way the layout must hold.
    r.check("GetSimulationTimeStatus", 0x1101, c.call(tcp.send_get_status, 0x1101, log_send=False),
            (OK, INVALID_STATE), tcp.parse_get_status_payload)
    r.check("ScenarioStatus", 0x1504, c.call(tcp.send_scenario_status, 0x1504), (OK, FAILED),
            tcp.parse_scenario_status_payload)
    r.check("ActiveSuiteStatus", 0x1401, c.call(tcp.send_active_suite_status, 0x1401), (OK, INVALID_STATE),
            tcp.parse_active_suite_status_payload)

    print("== Phase A: malformed payloads -> InvalidParam, nothing executed")
    malformed = [
        ("SetSimulatorMode empty", 0x1003, b""),
        ("LoadMap empty", 0x1004, b""),
        ("LoadMap name length past end", 0x1004, u32(0xFFFFFFFF)),
        ("SetSimulationTimeMode short (4B)", 0x1102, i32(2)),
        ("SetSimulationTimeMode unknown mode 9", 0x1102, i32(9) + i32(30) + i32(10) + i32(1) + i32(1)),
        ("FixedStep empty", 0x1201, b""),
        ("CreateObject short (4B)", 0x1301, i32(1)),
        ("ManualControlById empty", 0x1302, b""),
        ("ManualControlById id only", 0x1302, lp("Car_1")),
        ("TransformControlById empty", 0x1303, b""),
        ("TransformControlById id only", 0x1303, lp("Car_1")),
        ("SetTrajectory empty", 0x1304, b""),
        ("SetTrajectory point count past end", 0x1304, lp("Car_1") + i32(0) + lp("t") + u32(1000)),
        ("DeleteObject empty", 0x1305, b""),
        ("GetVehicleInfo empty", 0x1306, b""),
        ("GetVehicleInfo id length past end", 0x1306, u32(64) + b"Car"),
        ("LoadSuite empty", 0x1402, b""),
        ("ScenarioControl empty", 0x1505, b""),
        ("ScenarioControl name length past end", 0x1505, u32(1) + u32(64) + b"x"),
        ("LoadTrafficScenario empty", 0x1601, b""),
        ("TrafficGenerate short (4B)", 0x1602, i32(1)),
    ]
    for name, opcode, payload in malformed:
        r.check(name, opcode, c.raw(opcode, payload), INVALID_PARAM)

    print("== Phase A: unknown names / opcodes")
    r.check("GetVehicleInfo unknown id", 0x1306,
            c.call(tcp.send_get_vehicle_info, 0x1306, entity_id="__regression_no_such_vehicle__"), NONZERO)
    r.check("LoadMap unknown map", 0x1004,
            c.call(tcp.send_load_map, 0x1004, map_name="__regression_no_such_map__"), NONZERO)
    r.check("unknown legacy opcode 0x1999", 0x00001999, c.raw(0x00001999, b""), NOT_SUPPORTED)
    r.check_reply("unknown proto opcode 0x01019999", 0x01019999, c.raw(0x01019999, b""),
                  NOT_SUPPORTED, 101)  # ERROR_REASON_UNKNOWN_API


# ------------------------------------------------------------------------------------------------
# Phase B: a running scenario
# ------------------------------------------------------------------------------------------------
def phase_b(c: Conn, r: Report, args) -> None:
    print("== Phase B: scenario run")
    if args.suite_path:
        r.check("LoadSuite", 0x1402,
                c.call(tcp.send_load_suite, 0x1402, timeout=args.load_timeout, suite_path=args.suite_path), OK)
        time.sleep(5.0)

    r.check("ActiveSuiteStatus (suite loaded)", 0x1401, c.call(tcp.send_active_suite_status, 0x1401), OK,
            tcp.parse_active_suite_status_payload,
            lambda p: None if args.scenario in p["scenario_list"]
            else f"scenario {args.scenario!r} not in {p['scenario_list']}")

    r.check("SetSimulationTimeMode fixed", 0x1102,
            c.call(tcp.send_simulation_time_mode_command, 0x1102, mode=proto.TIME_MODE_FIXED,
                   target_fps=30, physics_delta_time=10, rtf=1, user_control=1), OK,
            tcp.parse_set_simulation_time_mode_payload)
    r.check("ScenarioControl Play", 0x1505,
            c.call(tcp.send_scenario_control, 0x1505, timeout=args.step_timeout, command=1,
                   scenario_name=args.scenario), OK)
    time.sleep(args.start_wait)

    def step(label: str, count: int = 1) -> None:
        r.check(f"FixedStep {label}", 0x1201,
                c.call(tcp.send_fixed_step, 0x1201, timeout=args.step_timeout, step_count=count,
                       save_mode=proto.SAVE_MODE_SKIP), OK)

    step("warm-up")
    r.check("ScenarioStatus (playing)", 0x1504, c.call(tcp.send_scenario_status, 0x1504), OK,
            tcp.parse_scenario_status_payload)
    r.check("GetSimulationTimeStatus (fixed)", 0x1101, c.call(tcp.send_get_status, 0x1101, log_send=False), OK,
            tcp.parse_get_status_payload,
            lambda p: None if p["mode"] == proto.TIME_MODE_FIXED else f"mode {p['mode']}, want fixed")

    x, y, z = args.spawn
    created = r.check("CreateObject Formula4 (model 12)", 0x1301,
                      c.call(tcp.send_create_object, 0x1301, timeout=args.step_timeout, entity_type=1,
                             pos_x=x, pos_y=y, pos_z=z, rot_x=0.0, rot_y=0.0, rot_z=0.0,
                             driving_mode=1, ground_vehicle_model=12), OK,
                      tcp.parse_create_object_payload,
                      lambda p: None if p["object_id"] else "empty entity name")
    r.check("CreateObject model 0 (rejected since 3/4-c)", 0x1301,
            c.call(tcp.send_create_object, 0x1301, entity_type=1, pos_x=x, pos_y=y, pos_z=z, rot_x=0.0,
                   rot_y=0.0, rot_z=0.0, driving_mode=1, ground_vehicle_model=0), INVALID_PARAM)
    r.check("CreateObject entity_type 0 (rejected since 3/4-c)", 0x1301,
            c.call(tcp.send_create_object, 0x1301, entity_type=0, pos_x=x, pos_y=y, pos_z=z, rot_x=0.0,
                   rot_y=0.0, rot_z=0.0, driving_mode=1, ground_vehicle_model=12), INVALID_PARAM)

    if created:
        name = created["object_id"]
        step("after create", 3)
        r.check(f"GetVehicleInfo {name}", 0x1306, c.call(tcp.send_get_vehicle_info, 0x1306, entity_id=name), OK,
                tcp.parse_get_vehicle_info_payload,
                lambda p: None if p["entity_id"] == name else f"entity_id {p['entity_id']!r}")
        r.check(f"ManualControlById {name}", 0x1302,
                c.call(tcp.send_manual_control_by_id, 0x1302, entity_id=name, throttle=0.3, brake=0.0,
                       steer_angle=0.0), OK)
        r.check(f"TransformControlById {name}", 0x1303,
                c.call(tcp.send_transform_control_by_id, 0x1303, entity_id=name, pos_x=x, pos_y=y, pos_z=z,
                       rot_x=0.0, rot_y=0.0, rot_z=0.0, steer_angle=0.0, speed=5.0), OK)
        r.check(f"SetTrajectory {name}", 0x1304,
                c.call(tcp.send_set_trajectory, 0x1304, entity_id=name, follow_mode=0,
                       trajectory_name="regression",
                       points=[(x, y, z, 0.0), (x + 10.0, y, z, 2.0)]), OK)
        step("after control", 3)
        r.check("SaveData", 0x1202, c.call(tcp.send_save_data, 0x1202, timeout=args.step_timeout), OK)
        step("after save")
        r.check(f"DeleteObject {name}", 0x1305, c.call(tcp.send_delete_object, 0x1305, entity_id=name), OK)
        step("after delete")
        r.check(f"GetVehicleInfo {name} after delete", 0x1306,
                c.call(tcp.send_get_vehicle_info, 0x1306, entity_id=name), NONZERO)

    if not args.no_stop:
        r.check("ScenarioControl Stop", 0x1505,
                c.call(tcp.send_scenario_control, 0x1505, timeout=args.step_timeout, command=3,
                       scenario_name=args.scenario), OK)
    r.check("SetSimulationTimeMode variable", 0x1102,
            c.call(tcp.send_simulation_time_mode_command, 0x1102, mode=proto.TIME_MODE_VARIABLE), OK,
            tcp.parse_set_simulation_time_mode_payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default=proto.TCP_SERVER_IP)
    ap.add_argument("--port", type=int, default=proto.TCP_SERVER_PORT)
    ap.add_argument("--timeout", type=float, default=10.0, help="default response timeout (s)")
    ap.add_argument("--scenario-run", action="store_true", help="also run Phase B (plays a scenario)")
    ap.add_argument("--scenario", default="CTO-1721")
    ap.add_argument("--suite-path", default="", help="load this suite first (Phase B)")
    ap.add_argument("--spawn", type=lambda s: tuple(float(v) for v in s.split(",")), default=(0.0, 0.0, 0.0),
                    help="x,y,z for the created vehicle (Phase B)")
    ap.add_argument("--start-wait", type=float, default=5.0, help="seconds after Play")
    ap.add_argument("--step-timeout", type=float, default=60.0)
    ap.add_argument("--load-timeout", type=float, default=300.0)
    ap.add_argument("--no-stop", action="store_true", help="leave the scenario playing at the end")
    args = ap.parse_args()

    c = Conn(args.ip, args.port, args.timeout)
    print(f"connected {args.ip}:{args.port}")
    r = Report()
    try:
        phase_a(c, r)
        if args.scenario_run:
            phase_b(c, r, args)
    except ConnectionError as e:
        print(f"[ERROR] connection lost: {e} (did the simulator crash?)")
        r.rows.append((False, 0, "connection", str(e)))
    finally:
        c.close()
    return r.summary()


if __name__ == "__main__":
    raise SystemExit(main())
