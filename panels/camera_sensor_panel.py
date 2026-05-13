from __future__ import annotations

import time
from typing import Optional

import cv2
import dearpygui.dearpygui as dpg
import numpy as np

import panels.log as log
from receivers.camera_receiver import CameraReceiver
import utils.ui_queue as ui_queue

_CAM_W = 640
_CAM_H = 360
_CAM_BLANK: list = [0.0] * (_CAM_W * _CAM_H * 4)
_FRAME_INTERVAL = 1.0 / 30.0

_receiver: Optional[CameraReceiver] = None
_last_frame_t = 0.0
_last_rx_t = 0.0


def build(parent) -> None:
    with dpg.texture_registry():
        if not dpg.does_item_exist("cam_sensor_texture"):
            dpg.add_dynamic_texture(
                width=_CAM_W,
                height=_CAM_H,
                default_value=_CAM_BLANK,
                tag="cam_sensor_texture",
            )

    with dpg.child_window(parent=parent, width=-1, height=-1, border=False):
        _section("CONTROL")
        with dpg.group(horizontal=True):
            dpg.add_text("Bind IP   :", color=(180, 180, 180, 255))
            dpg.add_input_text(
                tag="cam_sensor_ip",
                default_value="0.0.0.0",
                width=120,
            )
            dpg.add_text("Port      :", color=(180, 180, 180, 255))
            dpg.add_input_int(
                tag="cam_sensor_port",
                default_value=9090,
                width=80,
                min_value=1,
                max_value=65535,
                step=0,
            )
            dpg.add_button(label="Start", tag="cam_sensor_btn_start", width=90, callback=_on_start)
            dpg.add_button(label="Stop", tag="cam_sensor_btn_stop", width=90, callback=_on_stop)
            dpg.add_text("Stopped", tag="cam_sensor_status", color=(180, 80, 80, 255))

        _section("STATUS")
        with dpg.group(horizontal=True):
            _kv("FPS", "cam_sensor_fps")
            dpg.add_spacer(width=16)
            _kv("Frame", "cam_sensor_size")
            dpg.add_spacer(width=16)
            _kv("Last RX", "cam_sensor_last_rx")

        _section("LIVE VIEW")
        dpg.add_image("cam_sensor_texture", width=_CAM_W, height=_CAM_H)


def _on_start() -> None:
    global _receiver, _last_rx_t
    if _receiver is not None and _receiver.is_alive():
        log.append("[CameraSensor] already running", "WARN")
        return

    ip = dpg.get_value("cam_sensor_ip").strip() or "0.0.0.0"
    port = int(dpg.get_value("cam_sensor_port"))
    _last_rx_t = 0.0

    _receiver = CameraReceiver(
        ip=ip,
        port=port,
        on_frame=_on_frame,
        show=False,
    )
    _receiver.start()
    dpg.configure_item("cam_sensor_btn_start", enabled=False)
    dpg.set_value("cam_sensor_status", "Running")
    dpg.configure_item("cam_sensor_status", color=(100, 220, 100, 255))
    dpg.set_value("cam_sensor_fps", "-")
    dpg.set_value("cam_sensor_size", "-")
    dpg.set_value("cam_sensor_last_rx", "-")
    log.append(f"[CameraSensor] start {ip}:{port}", "INFO")


def _on_stop() -> None:
    stop()


def stop() -> None:
    global _receiver
    if _receiver is not None:
        try:
            _receiver.stop()
        except Exception:
            pass
        _receiver = None
    if dpg.does_item_exist("cam_sensor_btn_start"):
        dpg.configure_item("cam_sensor_btn_start", enabled=True)
        dpg.set_value("cam_sensor_status", "Stopped")
        dpg.configure_item("cam_sensor_status", color=(180, 80, 80, 255))
        dpg.set_value("cam_sensor_texture", _CAM_BLANK)
        dpg.set_value("cam_sensor_fps", "-")
        dpg.set_value("cam_sensor_size", "-")
        dpg.set_value("cam_sensor_last_rx", "-")


def _on_frame(frame: np.ndarray) -> None:
    global _last_frame_t, _last_rx_t
    now = time.monotonic()
    _last_rx_t = now
    if now - _last_frame_t < _FRAME_INTERVAL:
        return
    _last_frame_t = now

    resized = cv2.resize(frame, (_CAM_W, _CAM_H))
    rgba = cv2.cvtColor(resized, cv2.COLOR_BGR2RGBA)
    flat = (rgba.astype(np.float32) / 255.0).flatten()
    height, width = frame.shape[:2]
    fps = _receiver.fps if _receiver is not None else 0.0

    def _apply(data=flat, w=width, h=height, f=fps, rx=now):
        if not dpg.does_item_exist("cam_sensor_texture"):
            return
        dpg.set_value("cam_sensor_texture", data)
        dpg.set_value("cam_sensor_fps", f"{f:.1f}")
        dpg.set_value("cam_sensor_size", f"{w} x {h}")
        age = max(0.0, time.monotonic() - rx)
        dpg.set_value("cam_sensor_last_rx", f"{age:.2f}s ago")
    ui_queue.post(_apply)


def _section(title: str) -> None:
    dpg.add_spacer(height=6)
    dpg.add_text(title, color=(200, 200, 100, 255))
    dpg.add_separator()
    dpg.add_spacer(height=2)


def _kv(label: str, tag: str) -> None:
    with dpg.group(horizontal=True):
        dpg.add_text(f"{label}:", color=(160, 160, 160, 255))
        dpg.add_text("-", tag=tag, color=(210, 210, 215, 255))
