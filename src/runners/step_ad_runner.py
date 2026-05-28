from __future__ import annotations

import itertools
import socket
import threading
import time

import numpy as np

import transport.protocol_defs as proto
import transport.tcp_transport as tcp
from autonomous_driving.autonomous_driving import AutonomousDriving
from autonomous_driving.vehicle_state import VehicleState
from receivers.vehicle_info_receiver import parse_vehicle_info_payload

MAX_STEER_RAD = 0.5

_rid_iter = itertools.count(1)
_SPEED_GAIN = 0.1
_CHASE_LFD_MIN = 3.0
_CHASE_LFD_MAX = 15.0
_CHASE_STEER_GAIN = 1.35


def _next_rid() -> int:
    return next(_rid_iter)


def _speed_ctrl(current_kph: float, target_kph: float) -> tuple[float, float]:
    err = target_kph - current_kph
    if err > 0:
        return float(np.clip(err * _SPEED_GAIN, 0.0, 1.0)), 0.0
    return 0.0, float(np.clip(-err * _SPEED_GAIN, 0.0, 0.5))


def _calc_chase_steer_norm(parsed: dict, target_x: float, target_y: float, wheelbase: float) -> float:
    dx = target_x - parsed["location"]["x"]
    dy = target_y - parsed["location"]["y"]
    distance = float(np.hypot(dx, dy))
    if distance < 1e-3:
        return 0.0

    yaw = np.deg2rad(parsed["rotation"]["z"])
    local_x = np.cos(-yaw) * dx - np.sin(-yaw) * dy
    local_y = np.sin(-yaw) * dx + np.cos(-yaw) * dy
    theta = float(np.arctan2(local_y, local_x))
    lfd = float(np.clip(distance, _CHASE_LFD_MIN, _CHASE_LFD_MAX))
    steer_rad = np.arctan2(2.0 * wheelbase * np.sin(theta), lfd) * _CHASE_STEER_GAIN
    return float(np.clip(steer_rad / MAX_STEER_RAD, -1.0, 1.0))


class _VehicleCtx:
    def __init__(
        self,
        entity_id: str,
        vi_ip: str,
        vi_port: int,
        path_file: str,
        map_name: str = None,
        is_chaser: bool = False,
        is_collision_target: bool = False,
        speed_kph: float = 60.0,
        trigger_kph: float = 5.0,
        max_speed_kph: float = None,
    ):
        self.entity_id = entity_id
        self.is_chaser = is_chaser
        self.is_collision_target = is_collision_target
        self.target_speed_kph = speed_kph if not is_chaser else speed_kph * 1.2
        self.trigger_kph = trigger_kph
        self.ad = AutonomousDriving(path_file, map_name=map_name, max_speed_kph=max_speed_kph)
        self.latest = None
        self.lock = threading.Lock()
        self.vi_event = threading.Event()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(2.0)
        self.sock.bind((vi_ip, vi_port))


class StepAdRunner:
    _TIMING_INTERVAL = 100
    _STEP_DEBUG_INTERVAL = 20

    def __init__(
        self,
        tcp_sock: socket.socket,
        vehicles: list,
        pending: dict,
        lock: threading.Lock,
        request_id_ref,
        pending_add_fn,
        pending_pop_fn,
        timeout_sec: float = 10.0,
        log_fn=None,
        status_cb=None,
        on_done=None,
        collision_cfg: dict = None,
        save_data: bool = False,
        **kwargs,
    ):
        self._tcp_sock = tcp_sock
        self._pending = pending
        self._lock = lock
        self._rid = request_id_ref
        self._pending_add = pending_add_fn
        self._pending_pop = pending_pop_fn
        self._timeout_sec = timeout_sec
        self._log = log_fn or (lambda msg, level="INFO": print(f"[StepAD] {msg}"))
        self._status_cb = status_cb or (lambda *a: None)
        self._on_done = on_done
        self._running = False
        self._collision_cfg = collision_cfg
        self._save_data = save_data
        self._ctxs: list[_VehicleCtx] = []

        chaser_id = (collision_cfg or {}).get("chaser_entity_id")
        target_id = (collision_cfg or {}).get("target_entity_id")
        speed_kph = (collision_cfg or {}).get("speed_kph", 60.0)

        for vehicle in vehicles:
            is_chaser = chaser_id == vehicle["entity_id"]
            is_target = bool(collision_cfg) and vehicle["entity_id"] == target_id
            ctx = _VehicleCtx(
                entity_id=vehicle["entity_id"],
                vi_ip=vehicle.get("vi_ip", "0.0.0.0"),
                vi_port=vehicle["vi_port"],
                path_file=vehicle.get("path", "path_link.csv"),
                map_name=vehicle.get("map_name"),
                is_chaser=is_chaser,
                is_collision_target=is_target,
                speed_kph=speed_kph,
                trigger_kph=(collision_cfg or {}).get("trigger_kph", 5.0),
                max_speed_kph=vehicle.get("max_speed_kph"),
            )
            self._ctxs.append(ctx)

            if is_chaser:
                role = f"Chaser ({speed_kph * 1.2:.0f} km/h)"
            elif is_target:
                role = f"Target ({speed_kph:.0f} km/h)"
            else:
                role = f"PathFollow (max={vehicle.get('max_speed_kph', 0):.0f} km/h)"
            self._log(
                f"[{ctx.entity_id}] waiting for VI on "
                f"{vehicle.get('vi_ip', '0.0.0.0')}:{vehicle['vi_port']} ({role})"
            )

    def update_max_speed_kph(self, entity_id: str, max_speed_kph: float) -> bool:
        for ctx in self._ctxs:
            if ctx.entity_id == entity_id:
                ctx.ad.set_max_speed_kph(float(max_speed_kph))
                return True
        return False

    def start(self) -> None:
        self._running = True
        for ctx in self._ctxs:
            threading.Thread(target=self._recv_loop, args=(ctx,), daemon=True).start()
        threading.Thread(target=self._control_loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        for ctx in self._ctxs:
            try:
                ctx.sock.close()
            except Exception:
                pass

    def _recv_loop(self, ctx: _VehicleCtx) -> None:
        while self._running:
            try:
                data, _ = ctx.sock.recvfrom(65535)
                self._log(
                    f"[VI][{ctx.entity_id}] UDP recv on "
                    f"{ctx.sock.getsockname()[0]}:{ctx.sock.getsockname()[1]} bytes={len(data)}",
                    "INFO",
                )
                parsed = parse_vehicle_info_payload(data)
                if parsed:
                    with ctx.lock:
                        ctx.latest = parsed
                    ctx.vi_event.set()
                    self._log(
                        f"[VI][{ctx.entity_id}] parse ok "
                        f"pos=({parsed['location']['x']:.3f}, {parsed['location']['y']:.3f}) "
                        f"vel_x={parsed['local_velocity']['x']:.3f} "
                        f"yaw_z={parsed['rotation']['z']:.3f}",
                        "INFO",
                    )
                else:
                    preview = data[:16].hex(" ")
                    self._log(
                        f"[VI][{ctx.entity_id}] parse failed bytes={len(data)} first16=[{preview}]",
                        "WARN",
                    )
            except socket.timeout:
                continue
            except OSError:
                break

    def _send_path_follow(self, ctx: _VehicleCtx, parsed: dict) -> None:
        vs = VehicleState(
            x=parsed["location"]["x"],
            y=parsed["location"]["y"],
            yaw=np.deg2rad(parsed["rotation"]["z"]),
            velocity=parsed["local_velocity"]["x"],
        )

        try:
            ctrl, _ = ctx.ad.execute(vs)
            steer_n = float(np.clip(ctrl.steering / MAX_STEER_RAD, -1.0, 1.0))

            if ctx.is_collision_target or ctx.is_chaser:
                current_kph = abs(parsed["local_velocity"]["x"]) * 3.6
                throttle, brake = _speed_ctrl(current_kph, ctx.target_speed_kph)
            else:
                throttle, brake = ctrl.accel, ctrl.brake

            tcp.send_manual_control_by_id(
                self._tcp_sock,
                _next_rid(),
                entity_id=ctx.entity_id,
                throttle=throttle,
                brake=brake,
                steer_angle=steer_n,
            )
            self._status_cb(
                ctx.entity_id,
                vs.position.x,
                vs.position.y,
                vs.velocity * 3.6,
                throttle,
                brake,
                steer_n,
            )
        except Exception as exc:
            self._log(f"[{ctx.entity_id}] control error: {exc}", "ERROR")

    def _send_chaser(self, ctx: _VehicleCtx, parsed: dict) -> None:
        target_id = self._collision_cfg["target_entity_id"]
        target_ctx = next((item for item in self._ctxs if item.entity_id == target_id), None)
        if target_ctx is None:
            return

        with target_ctx.lock:
            target_parsed = target_ctx.latest
        if target_parsed is None:
            return

        target_kph = abs(target_parsed["local_velocity"]["x"]) * 3.6
        if target_kph < ctx.trigger_kph:
            tcp.send_manual_control_by_id(
                self._tcp_sock,
                _next_rid(),
                entity_id=ctx.entity_id,
                throttle=0.0,
                brake=0.5,
                steer_angle=0.0,
            )
            return

        current_kph = abs(parsed["local_velocity"]["x"]) * 3.6
        throttle, brake = _speed_ctrl(current_kph, ctx.target_speed_kph)
        steer_n = _calc_chase_steer_norm(
            parsed,
            target_x=target_parsed["location"]["x"],
            target_y=target_parsed["location"]["y"],
            wheelbase=float(ctx.ad.pure_pursuit.wheelbase),
        )
        tcp.send_manual_control_by_id(
            self._tcp_sock,
            _next_rid(),
            entity_id=ctx.entity_id,
            throttle=throttle,
            brake=brake,
            steer_angle=steer_n,
        )
        self._status_cb(
            ctx.entity_id,
            parsed["location"]["x"],
            parsed["location"]["y"],
            abs(parsed["local_velocity"]["x"]) * 3.6,
            throttle,
            brake,
            steer_n,
        )

    def _control_loop(self) -> None:
        self._log("Driving started")
        step_index = 0

        _t_ack = []
        _t_vi = []
        _t_cmd = []
        _t_total = []

        def _should_debug() -> bool:
            return self._save_data and (step_index < 5 or step_index % self._STEP_DEBUG_INTERVAL == 0)

        def _send_all_cmds() -> None:
            sent_ids = []
            for ctx in self._ctxs:
                with ctx.lock:
                    parsed = ctx.latest
                if parsed is None:
                    if _should_debug():
                        self._log(f"[StepAD][step={step_index}] skip cmd: {ctx.entity_id} latest=None", "WARN")
                    continue
                if ctx.is_chaser:
                    self._send_chaser(ctx, parsed)
                else:
                    self._send_path_follow(ctx, parsed)
                sent_ids.append(ctx.entity_id)

            if _should_debug():
                sent_text = ", ".join(sent_ids) if sent_ids else "(none)"
                self._log(f"[StepAD][step={step_index}] commands sent: {sent_text}", "INFO")

        def _presend_step():
            rid = self._rid.next()
            ev = self._pending_add(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
            tcp.send_fixed_step(self._tcp_sock, rid, step_count=1)
            if _should_debug():
                self._log(f"[StepAD][step={step_index}] presend FixedStep rid={rid}", "INFO")
            return ev, rid

        try:
            for ctx in self._ctxs:
                ctx.vi_event.clear()

            ev, rid = _presend_step()
            if not ev.wait(self._timeout_sec):
                self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
                self._log("Initial FixedStep ACK timeout - stopping", "ERROR")
                return
            self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
            if _should_debug():
                self._log(f"[StepAD][init] FixedStep ACK rid={rid}", "INFO")

            if self._save_data:
                save_rid = _next_rid()
                if _should_debug():
                    self._log(f"[StepAD][init] SaveData send rid={save_rid}", "INFO")
                tcp.send_save_data(self._tcp_sock, save_rid)
                for ctx in self._ctxs:
                    if not ctx.vi_event.wait(self._timeout_sec):
                        self._log(f"[{ctx.entity_id}] initial VI timeout - stopping", "ERROR")
                        return
                    if _should_debug():
                        self._log(f"[StepAD][init] VI ready: {ctx.entity_id}", "INFO")

            _send_all_cmds()
            for ctx in self._ctxs:
                ctx.vi_event.clear()
            ev, rid = _presend_step()

            while self._running:
                t0 = time.perf_counter()
                if _should_debug():
                    self._log(f"[StepAD][step={step_index}] wait ACK rid={rid}", "INFO")

                if not ev.wait(self._timeout_sec):
                    self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
                    self._log(
                        f"FixedStep ACK timeout ({self._timeout_sec}s) - stopping. "
                        "Check whether the scenario is running in Fixed Step mode.",
                        "ERROR",
                    )
                    break
                self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
                if _should_debug():
                    self._log(f"[StepAD][step={step_index}] ACK ok rid={rid}", "INFO")

                t1 = time.perf_counter()

                if self._save_data:
                    try:
                        save_rid = _next_rid()
                        if _should_debug():
                            self._log(f"[StepAD][step={step_index}] SaveData send rid={save_rid}", "INFO")
                        tcp.send_save_data(self._tcp_sock, save_rid)
                    except OSError as exc:
                        self._log(f"SaveData send error: {exc}", "ERROR")
                        break

                for ctx in self._ctxs:
                    ctx.vi_event.clear()
                try:
                    ev, rid = _presend_step()
                except OSError as exc:
                    self._log(f"FixedStep send error: {exc}", "ERROR")
                    break

                t2 = time.perf_counter()

                if self._save_data:
                    for ctx in self._ctxs:
                        if not ctx.vi_event.wait(self._timeout_sec):
                            self._log(
                                f"[{ctx.entity_id}] VI timeout ({self._timeout_sec}s) - keep previous state",
                                "WARN",
                            )
                        elif _should_debug():
                            self._log(f"[StepAD][step={step_index}] VI ready: {ctx.entity_id}", "INFO")

                t3 = time.perf_counter()
                _send_all_cmds()
                t4 = time.perf_counter()

                _t_ack.append((t1 - t0) * 1000)
                _t_vi.append((t3 - t2) * 1000)
                _t_cmd.append((t4 - t3) * 1000)
                _t_total.append((t4 - t0) * 1000)

                if len(_t_total) >= self._TIMING_INTERVAL:
                    def _stats(samples):
                        return sum(samples) / len(samples), min(samples), max(samples)

                    aa, an, ax = _stats(_t_ack)
                    va, vn, vx = _stats(_t_vi)
                    ca, cn, cx = _stats(_t_cmd)
                    ta, tn, tx = _stats(_t_total)
                    self._log(
                        f"[Timing/{self._TIMING_INTERVAL}step] total={ta:.1f}ms({tn:.1f}~{tx:.1f})  "
                        f"ack_wait={aa:.1f}({an:.1f}~{ax:.1f})  "
                        f"vi_wait={va:.1f}({vn:.1f}~{vx:.1f})  "
                        f"cmd={ca:.1f}({cn:.1f}~{cx:.1f})",
                        "INFO",
                    )
                    _t_ack.clear()
                    _t_vi.clear()
                    _t_cmd.clear()
                    _t_total.clear()

                step_index += 1

        finally:
            self._running = False
            self._log("Driving stopped")
            if self._on_done:
                self._on_done()
