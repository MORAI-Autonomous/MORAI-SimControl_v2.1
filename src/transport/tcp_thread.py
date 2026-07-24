from __future__ import annotations

# tcp_thread.py
import socket
import threading
import time

import transport.protocol_defs as proto
import transport.tcp_transport as tcp
import utils.input_helper as prompt
import panels.log as log
import panels.commands as cmd_panel


def result_to_string(code: int):
    return proto.RESULT_CODE_MAP.get(code, f"UNKNOWN({code})")

def time_mode_to_string(mode: int):
    if mode == proto.TIME_MODE_VARIABLE:    return "VARIABLE"
    if mode == proto.TIME_MODE_FIXED:       return "FIXED"
    if mode == proto.TIME_MODE_FIXED_STEP:  return "FIXED_STEP_LEGACY"
    return f"UNKNOWN({mode})"

def simulator_state_to_string(state: int):
    return proto.SIMULATOR_STATE_MAP.get(state, f"UNKNOWN({state})")


def simulator_mode_to_string(mode: int):
    return proto.SIMULATOR_MODE_MAP.get(mode, f"UNKNOWN({mode})")


def _hex_dump(data: bytes):
    return " ".join(f"{b:02X}" for b in data) if data else "(empty)"


def scenario_state_to_string(state: int):
    return {
        1: "PLAY",
        2: "PAUSE",
        3: "STOP",
        4: "COMPLETED",
    }.get(state, f"UNKNOWN({state})")


def _msg_type_name(msg_type: int) -> str:
    return {
        proto.MSG_TYPE_FIXED_STEP: "FixedStep",
        proto.MSG_TYPE_SAVE_DATA: "SaveData",
        proto.MSG_TYPE_SCENARIO_CONTROL: "ScenarioControl",
    }.get(msg_type, f"0x{msg_type:04X}")


class Receiver(threading.Thread):
    def __init__(self, sock, pending: dict, lock: threading.Lock, on_disconnect=None,
                 on_response=None, on_vehicle_info=None):
        super().__init__(daemon=True)
        self.sock          = sock
        self.pending       = pending
        self.lock          = lock
        self.running       = True
        self.on_disconnect = on_disconnect
        self.on_response   = on_response
        self.on_vehicle_info = on_vehicle_info

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            # recv_packet만 별도 try — socket.timeout(recv 주기 만료)은 재연결 없이 continue
            try:
                msg_class, msg_type, payload_size, request_id, flag, payload = \
                    tcp.recv_packet(self.sock)
            except socket.timeout:
                continue
            except (ConnectionError, OSError) as e:
                err_code = getattr(e, 'errno', None) or getattr(e, 'winerror', None)
                log.append(f"Receiver stopped: errno={err_code}", "ERROR")
                self.running = False
                if self.on_disconnect:
                    self.on_disconnect()
                return
            except Exception as e:
                import traceback
                log.append(f"Receiver unexpected: {type(e).__name__}: {e}", "ERROR")
                log.append(traceback.format_exc(), "ERROR")
                self.running = False
                if self.on_disconnect:
                    self.on_disconnect()
                return

            response_result_code = None
            response_detail_code = None

            # SetSimulationTimeModeCommand (0x1102)
            if msg_class == proto.MSG_CLASS_NOTI \
                    and msg_type == proto.MSG_TYPE_SCENARIO_STATUS:
                header = tcp.build_header(msg_class, msg_type, payload_size, request_id, flag)
                log.append(
                    "[DBG][0x1504][NOTI] "
                    f"header=[{_hex_dump(header)}] payload=[{_hex_dump(payload)}]",
                    "INFO",
                )
                parsed = tcp.parse_scenario_status_notification_payload(payload)
                if parsed:
                    state = parsed["state"]
                    name = parsed["name"]
                    log.append(
                        f"ScenarioStatusNoti "
                        f"state={state}({scenario_state_to_string(state)}) "
                        f"name={name!r}",
                        "RECV"
                    )
                    cmd_panel.on_scenario_status(state, name)
                else:
                    log.append("ScenarioStatusNoti parse_failed", "WARN")

            elif msg_class == proto.MSG_CLASS_NOTI \
                    and msg_type == proto.MSG_TYPE_GET_SIMULATOR_STATUS:
                parsed = tcp.parse_get_simulator_status_notification_payload(payload)
                if parsed:
                    state = parsed["state"]
                    log.append(
                        f"SimulatorStatusNoti "
                        f"state={state}({simulator_state_to_string(state)})",
                        "RECV"
                    )
                    cmd_panel.on_simulator_status(state)
                else:
                    log.append("SimulatorStatusNoti parse_failed", "WARN")

            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_GET_SIMULATOR_STATUS:
                parsed = tcp.parse_get_simulator_status_payload(payload)
                if parsed:
                    state = parsed["state"]
                    result_code = parsed["result_code"]
                    detail_code = parsed["detail_code"]
                    level = "RECV" if result_code == 0 else "WARN"
                    log.append(
                        f"GetSimulatorStatus rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code} "
                        f"state={state}({simulator_state_to_string(state)})",
                        level
                    )
                    if result_code == 0:
                        cmd_panel.on_simulator_status(state)
                else:
                    log.append(f"GetSimulatorStatus parse_failed rid={request_id}", "WARN")

            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_GET_SIMULATOR_MODE:
                parsed = tcp.parse_get_simulator_mode_payload(payload)
                if parsed:
                    mode = parsed["mode"]
                    result_code = parsed["result_code"]
                    detail_code = parsed["detail_code"]
                    level = "RECV" if result_code == 0 else "WARN"
                    log.append(
                        f"GetSimulatorMode rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code} "
                        f"mode={mode}({simulator_mode_to_string(mode)})",
                        level
                    )
                    if result_code == 0:
                        cmd_panel.on_simulator_mode(mode)
                else:
                    log.append(f"GetSimulatorMode parse_failed rid={request_id}", "WARN")

            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_SET_SIMULATOR_MODE:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "WARN"
                    log.append(
                        f"SetSimulatorMode rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level
                    )
                else:
                    log.append(f"SetSimulatorMode parse_failed rid={request_id}", "WARN")

            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_LOAD_MAP:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "WARN"
                    log.append(
                        f"LoadMap rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level
                    )
                else:
                    log.append(f"LoadMap parse_failed rid={request_id}", "WARN")

            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_SHUTDOWN_SIMULATOR:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "WARN"
                    log.append(
                        f"ShutdownSimulator rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level,
                    )
                else:
                    log.append(f"ShutdownSimulator parse_failed rid={request_id}", "WARN")

            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND:
                parsed = tcp.parse_set_simulation_time_mode_payload(payload)
                if parsed:
                    message = (
                        f"SetSimulationTimeMode rid={request_id} "
                        f"result={parsed['result_code']}"
                        f"({result_to_string(parsed['result_code'])}) "
                        f"detail={parsed['detail_code']}"
                    )
                    if "mode" in parsed:
                        message += (
                            f" mode={time_mode_to_string(parsed['mode'])} "
                            f"fixed_delta={parsed['fixed_delta']:.3f}"
                        )
                    log.append(message, "RECV")
                else:
                    log.append(f"SetSimulationTimeMode parse_failed rid={request_id}", "WARN")

            # GetSimulationTimeStatus (0x1101)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_GET_SIMULATION_TIME_STATUS:
                parsed = tcp.parse_get_status_payload(payload)
                if parsed:
                    mode_detail = (
                        f"result={parsed['result_code']}({result_to_string(parsed['result_code'])}) "
                        f"detail={parsed['detail_code']} "
                        f"target_fps={parsed['target_fps']} "
                        f"physics_dt={parsed['physics_delta_time']}ms "
                        f"rtf={parsed['rtf']} user_control={parsed['user_control']}"
                    )
                    level = "RECV" if parsed["result_code"] == 0 else "WARN"
                    log.append(
                        f"GetStatus rid={request_id} "
                        f"mode={time_mode_to_string(parsed['mode'])} "
                        f"{mode_detail} "
                        f"step={parsed['step_index']} "
                        f"sim={parsed['seconds']}s {parsed['nanos']}ns",
                        level
                    )
                else:
                    log.append(f"GetStatus parse_failed rid={request_id}", "WARN")

            # CreateObject (0x1301)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_CREATE_OBJECT:
                parsed = tcp.parse_create_object_payload(payload)
                if parsed:
                    log.append(
                        f"CreateObject rid={request_id} "
                        f"result={parsed['result_code']}({result_to_string(parsed['result_code'])}) "
                        f"object_id={parsed['object_id']}",
                        "RECV"
                    )
                else:
                    log.append(f"CreateObject parse_failed rid={request_id}", "WARN")

            # SetTrajectory (0x1304)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_SET_TRAJECTORY_COMMAND:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "WARN"
                    log.append(
                        f"SetTrajectory rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level
                    )
                else:
                    log.append(f"SetTrajectory parse_failed rid={request_id}", "WARN")

            # DeleteObject (0x1305)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_DELETE_OBJECT:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "WARN"
                    log.append(
                        f"DeleteObject rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level
                    )
                else:
                    log.append(f"DeleteObject parse_failed rid={request_id}", "WARN")

            # GetVehicleInfo (0x1306)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_GET_VEHICLE_INFO:
                parsed = tcp.parse_get_vehicle_info_payload(payload)
                if parsed and self.on_vehicle_info:
                    try:
                        self.on_vehicle_info(request_id, parsed)
                    except Exception as e:
                        log.append(f"vehicle info callback error: {e}", "WARN")
                if parsed:
                    result_code = parsed["result_code"]
                    detail_code = parsed["detail_code"]
                    if result_code != 0:
                        log.append(
                            f"GetVehicleInfo rid={request_id} "
                            f"result={result_code}({result_to_string(result_code)}) "
                            f"detail={detail_code}",
                            "WARN",
                        )
                else:
                    log.append(f"GetVehicleInfo parse_failed rid={request_id}", "WARN")

            # ActiveSuiteStatus (0x1401)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_ACTIVE_SUITE_STATUS:
                parsed = tcp.parse_active_suite_status_payload(payload)
                if parsed:
                    prompt.update_scenario_list(parsed["scenario_list"])
                    scenarios = ", ".join(parsed["scenario_list"]) or "(empty)"
                    log.append(
                        f"ActiveSuiteStatus rid={request_id} "
                        f"suite={parsed['active_suite_name']!r} "
                        f"scenario={parsed['active_scenario_name']!r} "
                        f"list=[{scenarios}]",
                        "RECV"
                    )
                else:
                    log.append(f"ActiveSuiteStatus parse_failed rid={request_id}", "WARN")

            # LoadSuite (0x1402)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_LOAD_SUITE:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    response_result_code = result_code
                    response_detail_code = detail_code
                    level = "RECV" if result_code == 0 else "ERROR"
                    log.append(
                        f"LoadSuite rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level
                    )
                else:
                    log.append(f"LoadSuite parse_failed rid={request_id}", "WARN")

            # ScenarioStatus (0x1504)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_SCENARIO_STATUS:
                parsed = tcp.parse_scenario_status_payload(payload)
                if parsed:
                    state_str = scenario_state_to_string(parsed["state"])
                    log.append(
                        f"ScenarioStatus rid={request_id} "
                        f"result={parsed['result_code']}({result_to_string(parsed['result_code'])}) "
                        f"state={state_str} "
                        f"name={parsed['name']!r}",
                        "RECV"
                    )
                    if parsed["result_code"] == 0:
                        cmd_panel.on_scenario_status(parsed["state"], parsed["name"])
                else:
                    log.append(f"ScenarioStatus parse_failed rid={request_id}", "WARN")

            # ScenarioControl (0x1505)
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_SCENARIO_CONTROL:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "ERROR"
                    log.append(
                        f"ScenarioControl rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level,
                    )
                    cmd_panel.on_scenario_control_response(
                        request_id,
                        result_code,
                        detail_code,
                    )
                else:
                    log.append(
                        f"ScenarioControl parse_failed rid={request_id}",
                        "WARN",
                    )

            # General RESP — 오류만 로그
            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_LOAD_TRAFFIC_SCENARIO:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "ERROR"
                    log.append(
                        f"LoadTrafficScenario rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level,
                    )
                else:
                    log.append(
                        f"LoadTrafficScenario parse_failed rid={request_id}",
                        "WARN",
                    )

            elif msg_class == proto.MSG_CLASS_RESP \
                    and msg_type == proto.MSG_TYPE_TRAFFIC_GENERATE:
                parsed = tcp.parse_result_code(payload)
                if parsed:
                    result_code, detail_code = parsed
                    level = "RECV" if result_code == 0 else "ERROR"
                    log.append(
                        f"TrafficGenerate rid={request_id} "
                        f"result={result_code}({result_to_string(result_code)}) "
                        f"detail={detail_code}",
                        level,
                    )
                else:
                    log.append(
                        f"TrafficGenerate parse_failed rid={request_id}",
                        "WARN",
                    )

            elif msg_class == proto.MSG_CLASS_RESP:
                if payload_size >= proto.RESULT_SIZE:
                    parsed = tcp.parse_result_code(payload)
                    if parsed:
                        result_code, detail_code = parsed
                        if result_code != 0:
                            log.append(
                                f"0x{msg_type:04X} rid={request_id} "
                                f"result={result_code}({result_to_string(result_code)}) "
                                f"detail={detail_code}",
                                "ERROR"
                            )
                    else:
                        log.append(
                            f"0x{msg_type:04X} rid={request_id} result=parse_failed",
                            "WARN"
                        )

            # pending event set + cleanup
            if msg_class == proto.MSG_CLASS_RESP:
                with self.lock:
                    pending_item = self.pending.get((request_id, msg_type))
                if (
                    pending_item is not None
                    and msg_type in (proto.MSG_TYPE_FIXED_STEP, proto.MSG_TYPE_SAVE_DATA)
                ):
                    elapsed = max(0.0, time.time() - pending_item["t"])
                    if elapsed >= 0.5:
                        log.append(
                            f"[TCP][WAIT] {_msg_type_name(msg_type)} response delayed "
                            f"rid={request_id} elapsed={elapsed:.3f}s",
                            "WARN",
                        )
                if self.on_response:
                    try:
                        self.on_response(
                            msg_type,
                            request_id,
                            response_result_code,
                            response_detail_code,
                        )
                    except Exception as e:
                        log.append(f"response callback error: {e}", "WARN")
                with self.lock:
                    item = self.pending.pop((request_id, msg_type), None)
                    if item:
                        item["ev"].set()
