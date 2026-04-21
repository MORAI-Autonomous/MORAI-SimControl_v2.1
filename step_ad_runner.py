from __future__ import annotations

# step_ad_runner.py
# ad_runner.py 구조 기반 + Fixed Step 추가.
#
# 루프 순서:
#   ① 모든 차량 VI 읽기
#   ② 모든 차량 ManualControl 전송 (fire-and-forget)
#   ③ FixedStep 전송 → ACK 대기  (시뮬레이터 1틱 진행 + VI 전송)

import itertools
import socket
import threading

import numpy as np

import transport.tcp_transport as tcp
import transport.protocol_defs as proto
from receivers.vehicle_info_receiver import parse_vehicle_info_payload
from autonomous_driving.autonomous_driving import AutonomousDriving
from autonomous_driving.vehicle_state import VehicleState

MAX_STEER_RAD = 0.5

_rid_iter = itertools.count(1)

def _next_rid() -> int:
    return next(_rid_iter)


# ── 차량 컨텍스트 ─────────────────────────────────────────────

class _VehicleCtx:
    def __init__(self, entity_id: str, vi_ip: str, vi_port: int, path_file: str):
        self.entity_id = entity_id
        self.ad        = AutonomousDriving(path_file)
        self.latest    = None
        self.lock      = threading.Lock()
        self.vi_event  = threading.Event()   # FixedStep 후 VI 도착 신호

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(2.0)
        self.sock.bind((vi_ip, vi_port))


# ── StepAdRunner ──────────────────────────────────────────────

class StepAdRunner:
    def __init__(
        self,
        tcp_sock:      socket.socket,
        vehicles:      list,           # [{ entity_id, vi_ip, vi_port, path }, ...]
        pending:       dict,
        lock:          threading.Lock,
        request_id_ref,                # RequestIdCounter (app.py 공유)
        pending_add_fn,
        pending_pop_fn,
        timeout_sec:   float = 3.0,
        log_fn=None,
        status_cb=None,
        on_done=None,
        **kwargs,                      # save_data 등 미사용 파라미터
    ):
        self._tcp_sock    = tcp_sock
        self._pending     = pending
        self._lock        = lock
        self._rid         = request_id_ref
        self._pending_add = pending_add_fn
        self._pending_pop = pending_pop_fn
        self._timeout_sec = timeout_sec
        self._log         = log_fn or (lambda msg, level="INFO": print(f"[StepAD] {msg}"))
        self._status_cb   = status_cb or (lambda *a: None)
        self._on_done     = on_done
        self._running     = False
        self._ctxs: list[_VehicleCtx] = []
        for v in vehicles:
            ctx = _VehicleCtx(
                entity_id = v["entity_id"],
                vi_ip     = v.get("vi_ip", "0.0.0.0"),
                vi_port   = v["vi_port"],
                path_file = v.get("path", "path_link.csv"),
            )
            self._ctxs.append(ctx)
            self._log(f"[{ctx.entity_id}] VI 수신 대기 → {v.get('vi_ip', '0.0.0.0')}:{v['vi_port']}")

    # ── 공개 API ──────────────────────────────────────────────

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

    # ── UDP 수신 스레드 (차량별) ───────────────────────────────

    def _recv_loop(self, ctx: _VehicleCtx) -> None:
        while self._running:
            try:
                data, _ = ctx.sock.recvfrom(65535)
                parsed = parse_vehicle_info_payload(data)
                if parsed:
                    with ctx.lock:
                        ctx.latest = parsed
                    ctx.vi_event.set()   # VI 도착 신호
            except socket.timeout:
                continue
            except OSError:
                break

    # ── 제어 루프 ─────────────────────────────────────────────

    def _control_loop(self) -> None:
        self._log("주행 시작")

        try:
            while self._running:

                # ① 모든 차량 ManualControl 전송
                for ctx in self._ctxs:
                    with ctx.lock:
                        parsed = ctx.latest

                    if parsed is None:
                        self._log(f"[{ctx.entity_id}] 차량 상태 대기 중...", "INFO")
                        continue

                    vs = VehicleState(
                        x        = parsed["location"]["x"],
                        y        = parsed["location"]["y"],
                        yaw      = np.deg2rad(parsed["rotation"]["z"]),
                        velocity = parsed["local_velocity"]["x"] / 3.6,
                    )
                    try:
                        ctrl, _ = ctx.ad.execute(vs)
                        steer_n = float(np.clip(ctrl.steering / MAX_STEER_RAD, -1.0, 1.0))

                        tcp.send_manual_control_by_id(
                            self._tcp_sock,
                            _next_rid(),
                            entity_id   = ctx.entity_id,
                            throttle    = ctrl.accel,
                            brake       = ctrl.brake,
                            steer_angle = steer_n,
                        )
                        self._status_cb(
                            ctx.entity_id,
                            vs.position.x,
                            vs.position.y,
                            vs.velocity * 3.6,
                            ctrl.accel,
                            ctrl.brake,
                            steer_n,
                        )
                    except Exception as e:
                        self._log(f"[{ctx.entity_id}] 제어 오류: {e}", "ERROR")

                # ② FixedStep 전송 → ACK 대기
                #    전송 전에 vi_event 초기화 — ACK 이후 도착할 VI를 놓치지 않기 위함
                for ctx in self._ctxs:
                    ctx.vi_event.clear()

                rid = self._rid.next()
                ev  = self._pending_add(self._pending, self._lock, rid,
                                        proto.MSG_TYPE_FIXED_STEP)
                try:
                    tcp.send_fixed_step(self._tcp_sock, rid, step_count=1)
                except OSError as e:
                    self._log(f"FixedStep 전송 오류: {e}", "ERROR")
                    break

                if not ev.wait(self._timeout_sec):
                    self._pending_pop(self._pending, self._lock, rid,
                                      proto.MSG_TYPE_FIXED_STEP)
                    self._log(
                        f"FixedStep ACK timeout ({self._timeout_sec}s) — 중단. "
                        "시나리오가 Fixed Step 모드인지 확인하세요.",
                        "ERROR"
                    )
                    break

                self._pending_pop(self._pending, self._lock, rid,
                                  proto.MSG_TYPE_FIXED_STEP)

                # ③ SaveData 전송 (fire-and-forget — VI 도착이 완료 신호)
                try:
                    tcp.send_save_data(self._tcp_sock, _next_rid())
                except OSError as e:
                    self._log(f"SaveData 전송 오류: {e}", "ERROR")
                    break

                # ④ VI 도착 대기 (FixedStep 후 시뮬레이터가 UDP 전송)
                for ctx in self._ctxs:
                    if not ctx.vi_event.wait(self._timeout_sec):
                        self._log(
                            f"[{ctx.entity_id}] VI timeout ({self._timeout_sec}s) — 이전 상태로 계속",
                            "WARN"
                        )

        finally:
            self._running = False
            self._log("주행 종료")
            if self._on_done:
                self._on_done()
