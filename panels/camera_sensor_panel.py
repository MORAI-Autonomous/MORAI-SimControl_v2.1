from __future__ import annotations

import json
import os
import time
from typing import Optional

import cv2
import dearpygui.dearpygui as dpg
import numpy as np

import panels.log as log
from receivers.camera_sensor_receiver import CameraSensorReceiver, draw_bbox_overlays
import utils.ui_queue as ui_queue

_CAM_W = 640
_CAM_H = 360
_CAM_BLANK: list = [0.0] * (_CAM_W * _CAM_H * 4)
_FRAME_INTERVAL = 1.0 / 30.0
_TEX_W = 1920
_TEX_H = 1080
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "camera_sensor_state.json"
)

_receiver: Optional[CameraSensorReceiver] = None
_last_frame_t = 0.0
_last_rx_t = 0.0
_last_debug_log_t = 0.0
_TEX_BLANK: list = [0.0] * (_TEX_W * _TEX_H * 4)


def build(parent) -> None:
    with dpg.texture_registry():
        if not dpg.does_item_exist("cam_sensor_texture"):
            dpg.add_dynamic_texture(
                width=_TEX_W,
                height=_TEX_H,
                default_value=_TEX_BLANK,
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
                callback=_on_state_change,
            )
            dpg.add_text("Port      :", color=(180, 180, 180, 255))
            dpg.add_input_int(
                tag="cam_sensor_port",
                default_value=9090,
                width=80,
                min_value=1,
                max_value=65535,
                step=0,
                callback=_on_state_change,
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
            _kv("Objects", "cam_sensor_objects")
            dpg.add_spacer(width=16)
            _kv("Last RX", "cam_sensor_last_rx")

        _section("LIVE VIEW")
        with dpg.child_window(
            tag="cam_sensor_view_scroll",
            width=-1,
            height=-1,
            border=False,
            horizontal_scrollbar=True,
        ):
            dpg.add_image("cam_sensor_texture", width=_CAM_W, height=_CAM_H, tag="cam_sensor_image")

    _load_state()


def _on_start() -> None:
    global _receiver, _last_rx_t
    if _receiver is not None and _receiver.is_alive():
        log.append("[CameraSensor] already running", "WARN")
        return

    ip = dpg.get_value("cam_sensor_ip").strip() or "0.0.0.0"
    port = int(dpg.get_value("cam_sensor_port"))
    _last_rx_t = 0.0
    _save_state()

    _receiver = CameraSensorReceiver(
        ip=ip,
        port=port,
        on_packet=_on_packet,
    )
    _receiver.start()
    dpg.configure_item("cam_sensor_btn_start", enabled=False)
    dpg.set_value("cam_sensor_status", "Running")
    dpg.configure_item("cam_sensor_status", color=(100, 220, 100, 255))
    dpg.set_value("cam_sensor_fps", "-")
    dpg.set_value("cam_sensor_size", "-")
    dpg.set_value("cam_sensor_objects", "-")
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
        dpg.set_value("cam_sensor_texture", _TEX_BLANK)
        dpg.configure_item(
            "cam_sensor_image",
            width=_CAM_W,
            height=_CAM_H,
            uv_min=(0.0, 0.0),
            uv_max=(_CAM_W / _TEX_W, _CAM_H / _TEX_H),
        )
        dpg.set_value("cam_sensor_fps", "-")
        dpg.set_value("cam_sensor_size", "-")
        dpg.set_value("cam_sensor_objects", "-")
        dpg.set_value("cam_sensor_last_rx", "-")


def _on_packet(packet: dict) -> None:
    global _last_frame_t, _last_rx_t, _last_debug_log_t
    now = time.monotonic()
    _last_rx_t = now
    if now - _last_frame_t < _FRAME_INTERVAL:
        return
    _last_frame_t = now

    frame = packet.get("frame")
    if frame is None:
        return
    objects = packet.get("objects", [])
    overlay, draw_stats = draw_bbox_overlays(frame, objects)
    height, width = frame.shape[:2]
    view_w = width
    view_h = height
    if view_w > _TEX_W or view_h > _TEX_H:
        scale = min(_TEX_W / max(1, view_w), _TEX_H / max(1, view_h), 1.0)
        view_w = max(1, int(view_w * scale))
        view_h = max(1, int(view_h * scale))
        resized = cv2.resize(overlay, (view_w, view_h))
        if now - _last_debug_log_t >= 1.0:
            log.append(
                f"[CameraSensor] source frame {width}x{height} exceeds texture {_TEX_W}x{_TEX_H}; displayed as {view_w}x{view_h}",
                "WARN",
            )
    else:
        resized = overlay
    canvas = np.zeros((_TEX_H, _TEX_W, 4), dtype=np.float32)
    rgba = cv2.cvtColor(resized, cv2.COLOR_BGR2RGBA).astype(np.float32) / 255.0
    canvas[:view_h, :view_w, :] = rgba
    flat = canvas.flatten()
    fps = float(packet.get("fps", _receiver.fps if _receiver is not None else 0.0))
    object_count = int(packet.get("object_count", len(objects)))
    packet_seq = int(packet.get("packet_seq", 0))

    if now - _last_debug_log_t >= 1.0:
        _last_debug_log_t = now
        log.append(
            f"[CameraSensor] pkt={packet_seq} objects={object_count} drawn2d={draw_stats['drawn_2d']} drawn3d={draw_stats['drawn_3d']} frame={width}x{height}",
            "INFO",
        )

    def _apply(data=flat, w=width, h=height, vw=view_w, vh=view_h, f=fps, c=object_count, rx=now):
        if not dpg.does_item_exist("cam_sensor_texture"):
            return
        dpg.set_value("cam_sensor_texture", data)
        dpg.configure_item(
            "cam_sensor_image",
            width=vw,
            height=vh,
            uv_min=(0.0, 0.0),
            uv_max=(vw / _TEX_W, vh / _TEX_H),
        )
        dpg.set_value("cam_sensor_fps", f"{f:.1f}")
        dpg.set_value("cam_sensor_size", f"{w} x {h}")
        dpg.set_value("cam_sensor_objects", str(c))
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


def _on_state_change(sender=None, app_data=None, user_data=None) -> None:
    _save_state()


def _save_state() -> None:
    if not dpg.does_item_exist("cam_sensor_ip") or not dpg.does_item_exist("cam_sensor_port"):
        return

    data = {
        "ip": dpg.get_value("cam_sensor_ip").strip() or "0.0.0.0",
        "port": int(dpg.get_value("cam_sensor_port")),
    }
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
    except Exception as e:
        log.append(f"[CameraSensor] save state error: {e}", "ERROR")


def _load_state() -> None:
    if not os.path.isfile(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception as e:
        log.append(f"[CameraSensor] load state error: {e}", "ERROR")
        return

    try:
        if dpg.does_item_exist("cam_sensor_ip"):
            dpg.set_value("cam_sensor_ip", str(data.get("ip", "0.0.0.0")))
        if dpg.does_item_exist("cam_sensor_port"):
            dpg.set_value("cam_sensor_port", int(data.get("port", 9090)))
    except Exception as e:
        log.append(f"[CameraSensor] apply state error: {e}", "ERROR")
