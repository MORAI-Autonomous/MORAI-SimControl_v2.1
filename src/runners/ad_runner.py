from __future__ import annotations

import argparse
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

_shared_positions: dict = {}
_shared_pos_lock = threading.Lock()


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


def _update_shared_pos(entity_id: str, x: float, y: float, speed_kph: float) -> None:
    with _shared_pos_lock:
        _shared_positions[entity_id] = {
            "x": x,
            "y": y,
            "speed_kph": speed_kph,
            "time": time.time(),
        }


def _get_shared_pos(entity_id: str | None) -> dict | None:
    if not entity_id:
        return None
    with _shared_pos_lock:
        pos = _shared_positions.get(entity_id)
        if not pos:
            return None
        return dict(pos)


def clear_shared_positions() -> None:
    with _shared_pos_lock:
        _shared_positions.clear()


class AdRunner:
    def __init__(
        self,
        tcp_sock,
        entity_id,
        vi_ip,
        vi_port,
        path_file="path_link.csv",
        map_name=None,
        log_fn=None,
        status_cb=None,
        is_chaser=False,
        is_collision_target=False,
        target_entity_id=None,
        speed_kph=60.0,
        trigger_kph=5.0,
        max_speed_kph=None,
        vehicle_info_source="UDP",
        request_id_ref=None,
    ):
        self._tcp_sock = tcp_sock
        self._entity_id = entity_id
        self._vehicle_info_source = vehicle_info_source.upper()
        self._request_id_ref = request_id_ref
        self._recv_sock = None
        if self._vehicle_info_source == "UDP":
            self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._recv_sock.bind((vi_ip, vi_port))
            self._recv_sock.settimeout(2.0)

        self._is_chaser = is_chaser
        self._is_collision_target = is_collision_target
        self._target_entity_id = target_entity_id
        self._target_speed_kph = speed_kph if not is_chaser else speed_kph * 1.2
        self._trigger_kph = trigger_kph
        self._max_speed_kph = max_speed_kph

        self._ad = AutonomousDriving(path_file, map_name=map_name, max_speed_kph=max_speed_kph)

        self._running = False
        self._lock = threading.Lock()
        self._latest = None
        self._vi_response = None
        self._vi_event = threading.Event()
        self._pending_vi_request_ids: set[int] = set()
        self._log = log_fn or (lambda msg, level="INFO": print(f"[{level}] {msg}"))
        self._status_cb = status_cb

        role = "Chaser" if is_chaser else "PathFollow"
        if self._vehicle_info_source == "UDP":
            self._log(f"Vehicle Info receiver: {vi_ip}:{vi_port}")
        else:
            self._log("Vehicle Info source: TCP GetVehicleInfo (0x1306)")
        self._log(f"TCP control entity_id={entity_id} ({role})")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._recv_sock is not None:
            threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._control_loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        if self._recv_sock is not None:
            try:
                self._recv_sock.close()
            except OSError:
                pass
        self._vi_event.set()

    def handle_vehicle_info_response(self, request_id: int, parsed: dict) -> bool:
        """Accept a GetVehicleInfo response owned by this runner."""
        with self._lock:
            if request_id not in self._pending_vi_request_ids:
                return False
            self._pending_vi_request_ids.discard(request_id)
            if parsed.get("result_code") == 0:
                self._latest = parsed
                self._vi_response = parsed
            else:
                self._vi_response = None
                self._log(
                    f"GetVehicleInfo failed: result={parsed.get('result_code')} "
                    f"detail={parsed.get('detail_code')}",
                    "WARN",
                )
        self._vi_event.set()
        return True

    def _next_request_id(self) -> int:
        if self._request_id_ref is not None:
            return self._request_id_ref.next()
        return _next_rid()

    def _request_vehicle_info(self) -> dict | None:
        rid = self._next_request_id()
        self._vi_event.clear()
        with self._lock:
            self._vi_response = None
            self._pending_vi_request_ids.add(rid)
        try:
            tcp.send_get_vehicle_info(self._tcp_sock, rid, self._entity_id)
        except Exception:
            with self._lock:
                self._pending_vi_request_ids.discard(rid)
            raise
        received = self._vi_event.wait(timeout=0.5)
        with self._lock:
            self._pending_vi_request_ids.discard(rid)
            return self._vi_response if received else None

    def update_max_speed_kph(self, max_speed_kph: float | None) -> None:
        self._max_speed_kph = max_speed_kph
        self._ad.set_max_speed_kph(max_speed_kph)

    def _recv_loop(self) -> None:
        while self._running:
            try:
                data, _addr = self._recv_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                parsed = parse_vehicle_info_payload(data)
            except Exception as exc:
                self._log(f"Vehicle Info parse error: {exc}", "WARN")
                continue

            with self._lock:
                self._latest = parsed

    def _control_loop(self) -> None:
        sampling_time = 1.0 / 30.0
        self._log("Driving started")

        while self._running:
            t_start = time.perf_counter()
            if self._vehicle_info_source == "TCP":
                try:
                    parsed = self._request_vehicle_info()
                except Exception as exc:
                    self._log(f"GetVehicleInfo error: {exc}", "ERROR")
                    break
            else:
                with self._lock:
                    parsed = self._latest

            if parsed:
                speed_kph = abs(parsed["local_velocity"]["x"]) * 3.6
                _update_shared_pos(
                    self._entity_id,
                    parsed["location"]["x"],
                    parsed["location"]["y"],
                    speed_kph,
                )
                if self._is_chaser:
                    self._run_chaser(parsed)
                else:
                    self._run_path_follow(parsed)
            else:
                self._log("Waiting for vehicle state...", "INFO")

            elapsed = time.perf_counter() - t_start
            sleep_t = sampling_time - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

        self._log("Driving stopped")

    def _run_path_follow(self, parsed: dict) -> None:
        vs = VehicleState(
            x=parsed["location"]["x"],
            y=parsed["location"]["y"],
            yaw=np.deg2rad(parsed["rotation"]["z"]),
            velocity=parsed["local_velocity"]["x"],
        )

        try:
            ctrl, _ = self._ad.execute(vs)
            steer_norm = float(np.clip(ctrl.steering / MAX_STEER_RAD, -1.0, 1.0))

            if self._is_collision_target:
                current_kph = abs(parsed["local_velocity"]["x"]) * 3.6
                throttle, brake = _speed_ctrl(current_kph, self._target_speed_kph)
            else:
                throttle = ctrl.accel
                brake = ctrl.brake

            tcp.send_manual_control_by_id(
                self._tcp_sock,
                self._next_request_id(),
                entity_id=self._entity_id,
                throttle=throttle,
                brake=brake,
                steer_angle=steer_norm,
            )

            if self._status_cb:
                self._status_cb(
                    self._entity_id,
                    vs.position.x,
                    vs.position.y,
                    vs.velocity * 3.6,
                    throttle,
                    brake,
                    steer_norm,
                )
        except Exception as exc:
            self._log(f"ERROR: {exc}", "ERROR")

    def _run_chaser(self, parsed: dict) -> None:
        target = _get_shared_pos(self._target_entity_id)
        if not target:
            return

        current_kph = abs(parsed["local_velocity"]["x"]) * 3.6
        if target["speed_kph"] < self._trigger_kph:
            throttle, brake = 0.0, 0.5
        else:
            throttle, brake = _speed_ctrl(current_kph, self._target_speed_kph)

        steer_norm = _calc_chase_steer_norm(
            parsed,
            target_x=target["x"],
            target_y=target["y"],
            wheelbase=float(self._ad.pure_pursuit.wheelbase),
        )

        tcp.send_manual_control_by_id(
            self._tcp_sock,
            self._next_request_id(),
            entity_id=self._entity_id,
            throttle=throttle,
            brake=brake,
            steer_angle=steer_norm,
        )

        if self._status_cb:
            self._status_cb(
                self._entity_id,
                parsed["location"]["x"],
                parsed["location"]["y"],
                current_kph,
                throttle,
                brake,
                steer_norm,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous driving runner test")
    parser.add_argument("--tcp-ip", default=proto.TCP_SERVER_IP)
    parser.add_argument("--tcp-port", type=int, default=proto.TCP_SERVER_PORT)
    parser.add_argument("--ego-ip", default="127.0.0.1")
    parser.add_argument("--ego-port", type=int, default=9091)
    parser.add_argument("--entity-id", default="Car_1")
    args = parser.parse_args()

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"TCP connect {args.tcp_ip}:{args.tcp_port} ...")
    try:
        tcp_sock.connect((args.tcp_ip, args.tcp_port))
    except OSError as exc:
        print(f"TCP connect failed: {exc}")
        return
    print("TCP connected")

    runner = AdRunner(
        tcp_sock=tcp_sock,
        entity_id=args.entity_id,
        vi_ip=args.ego_ip,
        vi_port=args.ego_port,
    )
    try:
        runner.start()
        threading.Event().wait()
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        runner.stop()
        tcp_sock.close()
        print("Stopped")


if __name__ == "__main__":
    main()
