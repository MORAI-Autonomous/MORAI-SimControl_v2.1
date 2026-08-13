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
        vehicle_info_source: str = "UDP",
    ):
        self.entity_id = entity_id
        self.is_chaser = is_chaser
        self.is_collision_target = is_collision_target
        self.target_speed_kph = speed_kph if not is_chaser else speed_kph * 1.2
        self.trigger_kph = trigger_kph
        self.ad = AutonomousDriving(path_file, map_name=map_name, max_speed_kph=max_speed_kph)
        self.latest = None
        self.last_vi_monotonic = None
        self.last_vi_timeout_log_monotonic = None
        self.lock = threading.Lock()
        self.vi_event = threading.Event()
        self.vehicle_info_source = vehicle_info_source.upper()

        self.sock = None
        if self.vehicle_info_source == "UDP":
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.settimeout(2.0)
            self.sock.bind((vi_ip, vi_port))


class StepAdRunner:
    _TIMING_INTERVAL = 100
    _STEP_DEBUG_INTERVAL = 20
    _SLOW_WAIT_SEC = 0.5
    _VI_STEP_WAIT_SEC = 0.5

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
        save_mode: int = proto.SAVE_MODE_SKIP,
        **kwargs,
    ):
        if save_mode not in proto.SAVE_MODE_MAP:
            raise ValueError(f"Unsupported save mode: {save_mode}")

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
        self._save_mode = save_mode
        self._ctxs: list[_VehicleCtx] = []
        self._tcp_vi_requests: dict[int, _VehicleCtx] = {}
        self._tcp_vi_lock = threading.Lock()

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
                vehicle_info_source=(
                    "TCP" if vehicle.get("interface") == "TCP" else "UDP"
                ),
            )
            self._ctxs.append(ctx)

            if is_chaser:
                role = f"Chaser ({speed_kph * 1.2:.0f} km/h)"
            elif is_target:
                role = f"Target ({speed_kph:.0f} km/h)"
            else:
                role = f"PathFollow (max={vehicle.get('max_speed_kph', 0):.0f} km/h)"
            if ctx.vehicle_info_source == "TCP":
                self._log(f"[{ctx.entity_id}] Vehicle Info via TCP 0x1306 ({role})")
            else:
                self._log(
                    f"[{ctx.entity_id}] waiting for VI on "
                    f"{vehicle.get('vi_ip', '0.0.0.0')}:{vehicle['vi_port']} ({role})"
                )

        self._tcp_external = bool(self._ctxs) and all(
            ctx.vehicle_info_source == "TCP" for ctx in self._ctxs
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
            if ctx.sock is not None:
                threading.Thread(target=self._recv_loop, args=(ctx,), daemon=True).start()
        threading.Thread(target=self._control_loop, daemon=True).start()

    def stop(self) -> None:
        self._log("Stop requested", "INFO")
        self._running = False
        for ctx in self._ctxs:
            if ctx.sock is not None:
                try:
                    ctx.sock.close()
                except Exception:
                    pass
            ctx.vi_event.set()

    def handle_vehicle_info_response(self, request_id: int, parsed: dict) -> bool:
        with self._tcp_vi_lock:
            ctx = self._tcp_vi_requests.pop(request_id, None)
        if ctx is None:
            return False
        if parsed.get("result_code") == 0:
            with ctx.lock:
                ctx.latest = parsed
                ctx.last_vi_monotonic = time.monotonic()
                ctx.last_vi_timeout_log_monotonic = None
        else:
            self._log(
                f"[{ctx.entity_id}] GetVehicleInfo failed: "
                f"result={parsed.get('result_code')} detail={parsed.get('detail_code')}",
                "WARN",
            )
        ctx.vi_event.set()
        return True

    def _request_tcp_vehicle_info(self) -> set[str]:
        requests = []
        for ctx in self._ctxs:
            if ctx.vehicle_info_source != "TCP":
                continue
            ctx.vi_event.clear()
            rid = self._rid.next()
            with self._tcp_vi_lock:
                self._tcp_vi_requests[rid] = ctx
            tcp.send_get_vehicle_info(self._tcp_sock, rid, ctx.entity_id)
            requests.append((rid, ctx))

        ready_ids = set()
        deadline = time.perf_counter() + self._VI_STEP_WAIT_SEC
        for rid, ctx in requests:
            remaining = max(0.0, deadline - time.perf_counter())
            if ctx.vi_event.wait(remaining):
                with ctx.lock:
                    if ctx.latest is not None:
                        ready_ids.add(ctx.entity_id)
            else:
                self._log(f"[{ctx.entity_id}] GetVehicleInfo timeout", "WARN")
            with self._tcp_vi_lock:
                self._tcp_vi_requests.pop(rid, None)
        return ready_ids

    def _recv_loop(self, ctx: _VehicleCtx) -> None:
        while self._running:
            try:
                data, _ = ctx.sock.recvfrom(65535)
                # Verbose per-packet VehicleInfo receive log.
                # Enable temporarily only when debugging raw UDP traffic volume.
                # self._log(
                #     f"[VI][{ctx.entity_id}] UDP recv on "
                #     f"{ctx.sock.getsockname()[0]}:{ctx.sock.getsockname()[1]} bytes={len(data)}",
                #     "INFO",
                # )
                parsed = parse_vehicle_info_payload(data)
                if parsed:
                    with ctx.lock:
                        prev_last_vi_monotonic = ctx.last_vi_monotonic
                        ctx.latest = parsed
                        ctx.last_vi_monotonic = time.monotonic()
                        ctx.last_vi_timeout_log_monotonic = None
                    ctx.vi_event.set()
                    if prev_last_vi_monotonic is not None:
                        gap_sec = max(0.0, time.monotonic() - prev_last_vi_monotonic)
                        if gap_sec >= 1.0:
                            self._log(
                                f"[VI][{ctx.entity_id}] resumed after {gap_sec:.3f}s",
                                "WARN",
                            )
                    # Verbose per-packet VehicleInfo parse log.
                    # self._log(
                    #     f"[VI][{ctx.entity_id}] parse ok "
                    #     f"pos=({parsed['location']['x']:.3f}, {parsed['location']['y']:.3f}) "
                    #     f"vel_x={parsed['local_velocity']['x']:.3f} "
                    #     f"yaw_z={parsed['rotation']['z']:.3f}",
                    #     "INFO",
                    # )
                else:
                    preview = data[:16].hex(" ")
                    self._log(
                        f"[VI][{ctx.entity_id}] parse failed bytes={len(data)} first16=[{preview}]",
                        "WARN",
                    )
            except socket.timeout:
                continue
            except OSError as exc:
                if self._running:
                    self._log(f"[VI][{ctx.entity_id}] UDP recv stopped: {exc}", "WARN")
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
                self._rid.next(),
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
                self._rid.next(),
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
            self._rid.next(),
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
        stop_reason = "loop exited"

        _t_ack = []
        _t_vi = []
        _t_cmd = []
        _t_total = []

        def _should_debug() -> bool:
            return step_index < 5 or step_index % self._STEP_DEBUG_INTERVAL == 0

        def _last_vi_age_text(ctx: _VehicleCtx) -> str:
            with ctx.lock:
                last_vi_monotonic = ctx.last_vi_monotonic
            if last_vi_monotonic is None:
                return "none"
            return f"{max(0.0, time.monotonic() - last_vi_monotonic):.3f}s"

        def _wait_for_vi(timeout_sec: float, phase: str, stop_on_timeout: bool) -> set[str]:
            ready_ids = set()
            deadline = time.perf_counter() + timeout_sec
            for ctx in self._ctxs:
                vi_wait_started = time.perf_counter()
                remaining = max(0.0, deadline - vi_wait_started)
                ready = ctx.vi_event.is_set()
                if not ready and remaining > 0.0:
                    ready = ctx.vi_event.wait(remaining)

                if not ready:
                    now = time.monotonic()
                    should_log_timeout = False
                    with ctx.lock:
                        last_timeout_log = ctx.last_vi_timeout_log_monotonic
                        if (
                            last_timeout_log is None
                            or now - last_timeout_log >= 5.0
                        ):
                            ctx.last_vi_timeout_log_monotonic = now
                            should_log_timeout = True
                    action = "stop" if stop_on_timeout else "skip control this step"
                    if should_log_timeout:
                        self._log(
                            f"[{ctx.entity_id}] VI timeout ({timeout_sec:.3f}s total) - {action} "
                            f"phase={phase} last_vi_age={_last_vi_age_text(ctx)}",
                            "ERROR" if stop_on_timeout else "WARN",
                        )
                    if stop_on_timeout:
                        return set()
                    continue

                ready_ids.add(ctx.entity_id)
                vi_wait_sec = time.perf_counter() - vi_wait_started
                if _should_debug() or vi_wait_sec >= self._SLOW_WAIT_SEC:
                    self._log(
                        f"[StepAD][{phase}] VI ready: {ctx.entity_id} "
                        f"wait={vi_wait_sec:.3f}s last_vi_age={_last_vi_age_text(ctx)}",
                        "WARN" if vi_wait_sec >= self._SLOW_WAIT_SEC else "INFO",
                    )
            return ready_ids

        def _send_all_cmds(fresh_entity_ids: set[str] = None) -> None:
            sent_ids = []
            for ctx in self._ctxs:
                if fresh_entity_ids is not None and ctx.entity_id not in fresh_entity_ids:
                    if _should_debug():
                        self._log(
                            f"[StepAD][step={step_index}] skip cmd: "
                            f"{ctx.entity_id} no fresh VI",
                            "WARN",
                        )
                    continue

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
            for ctx in self._ctxs:
                ctx.vi_event.clear()
            rid = self._rid.next()
            ev = self._pending_add(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
            tcp.send_fixed_step(
                self._tcp_sock,
                rid,
                step_count=1,
                save_mode=self._save_mode,
            )
            if _should_debug():
                self._log(f"[StepAD][step={step_index}] presend FixedStep rid={rid}", "INFO")
            return ev, rid

        try:
            ev, rid = _presend_step()
            ack_wait_started = time.perf_counter()
            if not ev.wait(self._timeout_sec):
                self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
                stop_reason = "initial FixedStep ACK timeout"
                self._log("Initial FixedStep ACK timeout - stopping", "ERROR")
                return
            ack_wait_sec = time.perf_counter() - ack_wait_started
            self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
            if _should_debug() or ack_wait_sec >= self._SLOW_WAIT_SEC:
                self._log(
                    f"[StepAD][init] FixedStep ACK rid={rid} wait={ack_wait_sec:.3f}s",
                    "WARN" if ack_wait_sec >= self._SLOW_WAIT_SEC else "INFO",
                )

            tcp_ready_ids = self._request_tcp_vehicle_info()
            if not self._tcp_external:
                ready_ids = _wait_for_vi(
                    timeout_sec=self._timeout_sec,
                    phase="init",
                    stop_on_timeout=True,
                )
                if len(ready_ids) < len(self._ctxs):
                    stop_reason = "initial VehicleInfo timeout"
                    return

            initial_ready_ids = (
                tcp_ready_ids
                if self._tcp_external
                else ready_ids
            )
            _send_all_cmds(initial_ready_ids)
            ev, rid = _presend_step()

            while self._running:
                t0 = time.perf_counter()
                if _should_debug():
                    self._log(f"[StepAD][step={step_index}] wait ACK rid={rid}", "INFO")

                if not ev.wait(self._timeout_sec):
                    self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
                    stop_reason = "FixedStep ACK timeout"
                    self._log(
                        f"FixedStep ACK timeout ({self._timeout_sec}s) - stopping. "
                        "Check whether the scenario is running in Fixed Step mode.",
                        "ERROR",
                    )
                    break
                ack_wait_sec = time.perf_counter() - t0
                self._pending_pop(self._pending, self._lock, rid, proto.MSG_TYPE_FIXED_STEP)
                if _should_debug() or ack_wait_sec >= self._SLOW_WAIT_SEC:
                    self._log(
                        f"[StepAD][step={step_index}] FixedStep ACK rid={rid} "
                        f"wait={ack_wait_sec:.3f}s",
                        "WARN" if ack_wait_sec >= self._SLOW_WAIT_SEC else "INFO",
                    )

                t1 = time.perf_counter()

                tcp_ready_ids = self._request_tcp_vehicle_info()

                if not self._tcp_external:
                    ready_ids = _wait_for_vi(
                        timeout_sec=self._VI_STEP_WAIT_SEC,
                        phase=f"step={step_index}",
                        stop_on_timeout=False,
                    )

                t2 = time.perf_counter()
                if self._tcp_external:
                    _send_all_cmds(tcp_ready_ids)
                else:
                    _send_all_cmds(ready_ids)

                t3 = time.perf_counter()
                try:
                    ev, rid = _presend_step()
                except OSError as exc:
                    stop_reason = f"FixedStep send error: {exc}"
                    self._log(f"FixedStep send error: {exc}", "ERROR")
                    break

                t4 = time.perf_counter()

                _t_ack.append((t1 - t0) * 1000)
                _t_vi.append((t2 - t1) * 1000)
                _t_cmd.append((t3 - t2) * 1000)
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
            if not self._running and stop_reason == "loop exited":
                stop_reason = "stop requested"
            self._running = False
            self._log(f"Driving stopped ({stop_reason})")
            if self._on_done:
                self._on_done()
