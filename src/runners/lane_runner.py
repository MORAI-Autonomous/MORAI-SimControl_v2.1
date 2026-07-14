from __future__ import annotations

"""Lane control runner wrapper used by the GUI."""

import itertools
import os
import socket
import threading
import time
from typing import Optional

import transport.tcp_transport as tcp
from lane_control.lane_controller import LaneController
from lane_control.run_recorder import LaneRunRecorder
from receivers.camera_receiver import CameraReceiver

_rid_iter = itertools.count(500_000)


def _next_rid() -> int:
    return next(_rid_iter)


class LaneRunner:
    """
    Manage LaneController and CameraReceiver as one GUI-facing runner.

    Parameters
    ----------
    tcp_sock:
        Connected TCP socket.
    entity_id:
        Target vehicle entity id.
    cam_ip, cam_port:
        Camera UDP bind address and port.
    vi_ip, vi_port:
        Vehicle Info UDP bind address and port.
    speed_ctrl:
        True uses speed PI control, False uses fixed throttle.
    log_fn:
        Optional logger callback fn(msg, level="INFO").
    """

    def __init__(
        self,
        tcp_sock: socket.socket,
        entity_id: str = "Car_1",
        cam_ip: str = "0.0.0.0",
        cam_port: int = 9090,
        vi_ip: str = "0.0.0.0",
        vi_port: int = 9091,
        speed_ctrl: bool = True,
        target_kmh: float = 15.0,
        throttle: float = 0.3,
        invert_steer: bool = True,
        log_fn=None,
        frame_cb=None,   # fn(frame: np.ndarray BGR)
        vi_cb=None,      # fn(parsed: dict)
        debug_cb=None,   # fn(composite: np.ndarray BGR)
        record_run: bool = False,
        tune_params: Optional[dict] = None,
    ):
        self._tcp_sock = tcp_sock
        self._entity_id = entity_id
        self._log = log_fn or (lambda msg, level="INFO": print(f"[LC] {msg}"))
        self._recorder: Optional[LaneRunRecorder] = None
        self._stop_reason = "stopped"
        self._telemetry_lock = threading.Lock()
        self._last_telemetry: Optional[dict] = None
        tune_params = dict(tune_params or {})
        record_path = None

        if record_run:
            root_dir = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "..", "runs", "lane_control"
            ))
            safe_entity = "".join(
                c if c.isalnum() or c in ("-", "_") else "_" for c in entity_id
            )
            run_dir = os.path.join(root_dir, f"{time.strftime('%Y%m%d-%H%M%S')}_{safe_entity}")
            config = {
                "entity_id": entity_id,
                "cam_ip": cam_ip,
                "cam_port": cam_port,
                "vi_ip": vi_ip,
                "vi_port": vi_port,
                "speed_ctrl": speed_ctrl,
                "target_kmh": target_kmh,
                "throttle": throttle,
                "invert_steer": invert_steer,
                "tune_params": tune_params,
            }
            self._recorder = LaneRunRecorder(run_dir, config, self._log)
            self._recorder.open()
            record_path = self._recorder.video_path

        self._controller = LaneController(
            tcp_sock=tcp_sock,
            entity_id=entity_id,
            throttle=throttle,
            show=False,
            tuning=False,
            speed_ctrl=speed_ctrl,
            vi_ip=vi_ip,
            vi_port=vi_port,
            target_kmh=target_kmh,
            invert_steer=invert_steer,
            log_fn=self._log,
            vi_data_cb=vi_cb,
            debug_cb=debug_cb,
            record_path=record_path,
            telemetry_cb=self._on_telemetry,
        )
        if tune_params:
            self._controller.update_params(**tune_params)

        _ctrl_on_frame = self._controller.on_frame

        def _on_frame(frame, _ctrl=_ctrl_on_frame, _fcb=frame_cb):
            _ctrl(frame)
            if _fcb:
                try:
                    _fcb(frame)
                except Exception:
                    pass

        self._receiver = CameraReceiver(
            ip=cam_ip,
            port=cam_port,
            on_frame=_on_frame,
            show=False,
        )
        mode = f"target={target_kmh}km/h" if speed_ctrl else f"throttle={throttle}"
        self._log(
            f"initialized: Camera={cam_ip}:{cam_port}, VI={vi_ip}:{vi_port}, "
            f"entity={entity_id}, {mode}"
        )
        if self._recorder is not None:
            self._log(f"recording run: {self._recorder.run_dir}")

    def start(self) -> None:
        """Start camera receiver and lane control loop."""
        self._receiver.start()
        self._controller.start()
        self._log("Lane Control started")

    def update_params(self, **kwargs) -> None:
        """Apply GUI parameter changes to LaneController."""
        self._controller.update_params(**kwargs)

    def set_stop_reason(self, reason: str) -> None:
        self._stop_reason = reason or "stopped"

    def _on_telemetry(self, row: dict) -> None:
        with self._telemetry_lock:
            self._last_telemetry = dict(row)
        if self._recorder is not None:
            self._recorder.record(row)

    def get_last_telemetry(self) -> Optional[dict]:
        with self._telemetry_lock:
            return dict(self._last_telemetry) if self._last_telemetry is not None else None

    def stop(self) -> None:
        """Stop lane control and send a brake command."""
        self._controller.stop()
        self._receiver.stop()
        if self._recorder is not None:
            self._recorder.close(stop_reason=self._stop_reason)
            self._recorder = None
        self._stop_reason = "stopped"
        try:
            tcp.send_manual_control_by_id(
                self._tcp_sock, _next_rid(), self._entity_id,
                throttle=0.0, brake=1.0, steer_angle=0.0,
            )
            self._log("Stop command sent (brake=1.0)")
        except OSError:
            pass
        self._log("Lane Control stopped")
