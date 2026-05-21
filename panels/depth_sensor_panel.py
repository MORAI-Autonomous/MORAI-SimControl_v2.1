from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import dearpygui.dearpygui as dpg
import numpy as np

import panels.log as log
from receivers.camera_depth_receiver import CameraDepthReceiver
import utils.ui_queue as ui_queue

_VIEW_W = 960
_VIEW_H = 540
_FRAME_INTERVAL = 1.0 / 15.0
_DEFAULT_TEX_W = 640
_DEFAULT_TEX_H = 480
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "depth_sensor_state.json",
)
_TEX_BLANK: list = [0.0] * (_DEFAULT_TEX_W * _DEFAULT_TEX_H * 4)


@dataclass
class _State:
    receiver: Optional[CameraDepthReceiver] = None
    last_frame_t: float = 0.0
    last_rx_t: float = 0.0
    last_depth_m: Optional[np.ndarray] = None
    last_width: int = 0
    last_height: int = 0
    last_encoding: str = ""
    last_perf_log_t: float = 0.0
    texture_w: int = _DEFAULT_TEX_W
    texture_h: int = _DEFAULT_TEX_H
    ui_posted: bool = False
    pending_ui: Optional[dict] = None


_state = _State()
_ui_lock = threading.Lock()


def build(parent) -> None:
    with dpg.texture_registry():
        if not dpg.does_item_exist("depth_sensor_texture"):
            dpg.add_dynamic_texture(
                width=_DEFAULT_TEX_W,
                height=_DEFAULT_TEX_H,
                default_value=_TEX_BLANK,
                tag="depth_sensor_texture",
            )

    with dpg.child_window(parent=parent, width=-1, height=-1, border=False):
        _section("CONTROL")
        with dpg.group(horizontal=True):
            dpg.add_text("Bind IP", color=(180, 180, 180, 255))
            dpg.add_input_text(
                tag="depth_sensor_ip",
                default_value="0.0.0.0",
                width=140,
                callback=_on_state_change,
            )
            dpg.add_text("Port", color=(180, 180, 180, 255))
            dpg.add_input_int(
                tag="depth_sensor_port",
                default_value=9100,
                width=100,
                min_value=1,
                max_value=65535,
                step=0,
                callback=_on_state_change,
            )
            dpg.add_button(label="Start", width=90, callback=lambda: _start())
            dpg.add_button(label="Stop", width=90, callback=lambda: stop())
            dpg.add_text("Stopped", tag="depth_sensor_status", color=(180, 80, 80, 255))

        _section("DISPLAY")
        with dpg.group(horizontal=True):
            dpg.add_text("View", color=(180, 180, 180, 255))
            dpg.add_combo(
                tag="depth_sensor_view_mode",
                items=["Grayscale", "Color Map"],
                default_value="Grayscale",
                width=140,
                callback=_on_display_change,
            )
            dpg.add_text("Min (m)", color=(180, 180, 180, 255))
            dpg.add_input_float(
                tag="depth_sensor_min_m",
                default_value=0.0,
                width=100,
                step=0.0,
                callback=_on_display_change,
            )
            dpg.add_text("Max (m)", color=(180, 180, 180, 255))
            dpg.add_input_float(
                tag="depth_sensor_max_m",
                default_value=200.0,
                width=100,
                step=0.0,
                callback=_on_display_change,
            )

        _section("STATUS")
        with dpg.group(horizontal=True):
            _kv("FPS", "depth_sensor_fps")
            dpg.add_spacer(width=12)
            _kv("Frame", "depth_sensor_frame")
            dpg.add_spacer(width=12)
            _kv("Encoding", "depth_sensor_encoding")
        with dpg.group(horizontal=True):
            _kv("Depth", "depth_sensor_depth_range")
            dpg.add_spacer(width=12)
            _kv("Last RX", "depth_sensor_last_rx")

        _section("LIVE VIEW")
        with dpg.child_window(
            tag="depth_sensor_view_host",
            width=-1,
            height=-1,
            border=False,
            horizontal_scrollbar=True,
        ):
            dpg.add_image(
                "depth_sensor_texture",
                width=_VIEW_W,
                height=_VIEW_H,
                tag="depth_sensor_image",
            )

    _load_state()


def stop() -> None:
    if _state.receiver is not None:
        try:
            _state.receiver.stop()
        except Exception:
            pass
        _state.receiver = None

    if dpg.does_item_exist("depth_sensor_status"):
        dpg.configure_item("depth_sensor_status", color=(180, 80, 80, 255))
        dpg.set_value("depth_sensor_status", "Stopped")
        _ensure_texture_size(_DEFAULT_TEX_W, _DEFAULT_TEX_H)
        dpg.set_value("depth_sensor_texture", _TEX_BLANK)
        dpg.configure_item(
            "depth_sensor_image",
            width=_DEFAULT_TEX_W,
            height=_DEFAULT_TEX_H,
            uv_min=(0.0, 0.0),
            uv_max=(1.0, 1.0),
        )
        dpg.set_value("depth_sensor_fps", "-")
        dpg.set_value("depth_sensor_frame", "-")
        dpg.set_value("depth_sensor_encoding", "-")
        dpg.set_value("depth_sensor_depth_range", "-")
        dpg.set_value("depth_sensor_last_rx", "-")


def _start() -> None:
    if _state.receiver is not None and _state.receiver.is_alive():
        log.append("[DepthSensor] already running", "WARN")
        return

    ip = dpg.get_value("depth_sensor_ip").strip() or "0.0.0.0"
    port = int(dpg.get_value("depth_sensor_port"))
    _state.last_frame_t = 0.0
    _state.last_rx_t = 0.0
    _state.last_depth_m = None
    _save_state()

    _state.receiver = CameraDepthReceiver(
        ip=ip,
        port=port,
        on_packet=_on_packet,
    )
    _state.receiver.start()
    dpg.configure_item("depth_sensor_status", color=(100, 220, 100, 255))
    dpg.set_value("depth_sensor_status", "Running")
    dpg.set_value("depth_sensor_fps", "-")
    dpg.set_value("depth_sensor_frame", "-")
    dpg.set_value("depth_sensor_encoding", "-")
    dpg.set_value("depth_sensor_depth_range", "-")
    dpg.set_value("depth_sensor_last_rx", "-")
    log.append(f"[DepthSensor] start {ip}:{port}", "INFO")


def _on_packet(packet: dict) -> None:
    now = time.monotonic()
    _state.last_rx_t = now
    _state.last_depth_m = packet["depth_m"]
    _state.last_width = int(packet["width"])
    _state.last_height = int(packet["height"])
    _state.last_encoding = str(packet["encoding"])
    packet["copy_ms"] = 0.0
    packet["rx_t"] = now
    if now - _state.last_frame_t < _FRAME_INTERVAL:
        return
    _state.last_frame_t = now
    _render_packet(packet)


def _render_packet(packet: dict) -> None:
    t_vis0 = time.perf_counter()
    depth_m = packet["depth_m"]
    view_mode = str(dpg.get_value("depth_sensor_view_mode"))
    min_m = float(dpg.get_value("depth_sensor_min_m"))
    max_m = float(dpg.get_value("depth_sensor_max_m"))
    vis_bgr = _visualize_depth(depth_m, min_m=min_m, max_m=max_m, view_mode=view_mode)
    visualize_ms = (time.perf_counter() - t_vis0) * 1000.0

    src_h, src_w = vis_bgr.shape[:2]
    view_w = src_w
    view_h = src_h
    scale_ms = 0.0
    max_tex_w = 1920
    max_tex_h = 1080
    if src_w > max_tex_w or src_h > max_tex_h:
        t_scale0 = time.perf_counter()
        scale = min(max_tex_w / max(1, src_w), max_tex_h / max(1, src_h), 1.0)
        view_w = max(1, int(src_w * scale))
        view_h = max(1, int(src_h * scale))
        vis_bgr = cv2.resize(vis_bgr, (view_w, view_h), interpolation=cv2.INTER_AREA)
        scale_ms = (time.perf_counter() - t_scale0) * 1000.0
        log.append(
            f"[DepthSensor] frame scaled {src_w}x{src_h} -> {view_w}x{view_h}",
            "WARN",
        )

    t_canvas0 = time.perf_counter()
    rgba = cv2.cvtColor(vis_bgr, cv2.COLOR_BGR2RGBA).astype(np.float32) / 255.0
    flat = rgba.flatten()
    canvas_ms = (time.perf_counter() - t_canvas0) * 1000.0

    fps = float(packet.get("fps", _state.receiver.fps if _state.receiver is not None else 0.0))
    depth_min_m = float(packet.get("depth_min_m", 0.0))
    depth_max_m = float(packet.get("depth_max_m", 0.0))
    last_rx_age = max(0.0, time.monotonic() - _state.last_rx_t)
    parse_ms = float(packet.get("parse_ms", 0.0))
    copy_ms = float(packet.get("copy_ms", 0.0))

    ui_payload = {
        "flat": flat,
        "view_w": view_w,
        "view_h": view_h,
        "src_w": src_w,
        "src_h": src_h,
        "fps": fps,
        "encoding": packet["encoding"],
        "depth_min_m": depth_min_m,
        "depth_max_m": depth_max_m,
        "last_rx_age": last_rx_age,
        "parse_ms": parse_ms,
        "copy_ms": copy_ms,
        "visualize_ms": visualize_ms,
        "scale_ms": scale_ms,
        "canvas_ms": canvas_ms,
        "rx_t": float(packet.get("rx_t", time.monotonic())),
    }

    should_post = False
    with _ui_lock:
        _state.pending_ui = ui_payload
        if not _state.ui_posted:
            _state.ui_posted = True
            should_post = True

    if should_post:
        ui_queue.post(_apply_latest_ui)


def _apply_latest_ui() -> None:
    while True:
        with _ui_lock:
            ui_payload = _state.pending_ui
            _state.pending_ui = None

        if ui_payload is None:
            with _ui_lock:
                _state.ui_posted = False
            return

        t_upload0 = time.perf_counter()
        _ensure_texture_size(ui_payload["view_w"], ui_payload["view_h"])
        dpg.set_value("depth_sensor_texture", ui_payload["flat"])
        dpg.configure_item(
            "depth_sensor_image",
            width=ui_payload["view_w"],
            height=ui_payload["view_h"],
            uv_min=(0.0, 0.0),
            uv_max=(1.0, 1.0),
        )
        dpg.set_value("depth_sensor_fps", f"{ui_payload['fps']:.1f}")
        dpg.set_value("depth_sensor_frame", f"{ui_payload['src_w']} x {ui_payload['src_h']}")
        dpg.set_value("depth_sensor_encoding", ui_payload["encoding"])
        dpg.set_value(
            "depth_sensor_depth_range",
            f"{ui_payload['depth_min_m']:.2f} ~ {ui_payload['depth_max_m']:.2f} m",
        )
        live_age = max(0.0, time.monotonic() - ui_payload["rx_t"])
        dpg.set_value("depth_sensor_last_rx", f"{live_age:.2f}s ago")
        upload_ms = (time.perf_counter() - t_upload0) * 1000.0

        now = time.monotonic()
        if now - _state.last_perf_log_t >= 1.0:
            _state.last_perf_log_t = now
            log.append(
                f"[DepthPerf] parse={ui_payload['parse_ms']:.1f}ms copy={ui_payload['copy_ms']:.1f}ms "
                f"visualize={ui_payload['visualize_ms']:.1f}ms scale={ui_payload['scale_ms']:.1f}ms "
                f"canvas={ui_payload['canvas_ms']:.1f}ms upload={upload_ms:.1f}ms "
                f"latency={live_age * 1000.0:.1f}ms frame={ui_payload['src_w']}x{ui_payload['src_h']}",
                "INFO",
            )
        with _ui_lock:
            has_newer = _state.pending_ui is not None
            if not has_newer:
                _state.ui_posted = False
                return


def _ensure_texture_size(width: int, height: int) -> None:
    width = max(1, int(width))
    height = max(1, int(height))
    if _state.texture_w == width and _state.texture_h == height and dpg.does_item_exist("depth_sensor_texture"):
        return

    if dpg.does_item_exist("depth_sensor_image"):
        dpg.delete_item("depth_sensor_image")
    if dpg.does_item_exist("depth_sensor_texture"):
        dpg.delete_item("depth_sensor_texture")

    blank = [0.0] * (width * height * 4)
    with dpg.texture_registry():
        dpg.add_dynamic_texture(
            width=width,
            height=height,
            default_value=blank,
            tag="depth_sensor_texture",
        )
    dpg.add_image(
        "depth_sensor_texture",
        width=width,
        height=height,
        tag="depth_sensor_image",
        parent="depth_sensor_view_host",
    )
    _state.texture_w = width
    _state.texture_h = height


def _visualize_depth(depth_m: np.ndarray, min_m: float, max_m: float, view_mode: str) -> np.ndarray:
    min_m = max(0.0, float(min_m))
    max_m = max(min_m + 0.001, float(max_m))
    valid = depth_m > 0.0
    clipped = np.clip(depth_m, min_m, max_m)
    norm = np.zeros(depth_m.shape, dtype=np.uint8)
    if np.any(valid):
        scaled = 1.0 - ((clipped - min_m) / (max_m - min_m))
        norm[valid] = np.clip(scaled[valid] * 255.0, 0.0, 255.0).astype(np.uint8)

    if view_mode == "Grayscale":
        vis = cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)
    else:
        vis = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)
        vis[~valid] = (0, 0, 0)
    return vis


def _on_state_change(sender=None, app_data=None, user_data=None) -> None:
    _save_state()


def _on_display_change(sender=None, app_data=None, user_data=None) -> None:
    _save_state()
    if _state.last_depth_m is None:
        return
    packet = {
        "depth_m": _state.last_depth_m,
        "width": _state.last_width,
        "height": _state.last_height,
        "encoding": _state.last_encoding or "32FC1",
        "depth_min_m": float(np.min(_state.last_depth_m[_state.last_depth_m > 0.0])) if np.any(_state.last_depth_m > 0.0) else 0.0,
        "depth_max_m": float(np.max(_state.last_depth_m[_state.last_depth_m > 0.0])) if np.any(_state.last_depth_m > 0.0) else 0.0,
        "fps": _state.receiver.fps if _state.receiver is not None else 0.0,
    }
    _render_packet(packet)


def _load_state() -> None:
    if not os.path.exists(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception:
        return

    if dpg.does_item_exist("depth_sensor_ip"):
        dpg.set_value("depth_sensor_ip", str(data.get("ip", "0.0.0.0")))
    if dpg.does_item_exist("depth_sensor_port"):
        dpg.set_value("depth_sensor_port", int(data.get("port", 9100)))
    if dpg.does_item_exist("depth_sensor_view_mode"):
        dpg.set_value("depth_sensor_view_mode", str(data.get("view_mode", "Grayscale")))
    if dpg.does_item_exist("depth_sensor_min_m"):
        dpg.set_value("depth_sensor_min_m", float(data.get("min_m", 0.0)))
    if dpg.does_item_exist("depth_sensor_max_m"):
        dpg.set_value("depth_sensor_max_m", float(data.get("max_m", 200.0)))


def _save_state() -> None:
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    data = {
        "ip": dpg.get_value("depth_sensor_ip") if dpg.does_item_exist("depth_sensor_ip") else "0.0.0.0",
        "port": int(dpg.get_value("depth_sensor_port")) if dpg.does_item_exist("depth_sensor_port") else 9100,
        "view_mode": dpg.get_value("depth_sensor_view_mode") if dpg.does_item_exist("depth_sensor_view_mode") else "Grayscale",
        "min_m": float(dpg.get_value("depth_sensor_min_m")) if dpg.does_item_exist("depth_sensor_min_m") else 0.0,
        "max_m": float(dpg.get_value("depth_sensor_max_m")) if dpg.does_item_exist("depth_sensor_max_m") else 200.0,
    }
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _section(title: str) -> None:
    dpg.add_spacer(height=6)
    dpg.add_text(title, color=(220, 220, 90, 255))
    dpg.add_separator()


def _kv(label: str, value_tag: str) -> None:
    dpg.add_text(f"{label}:", color=(160, 160, 160, 255))
    dpg.add_text("-", tag=value_tag)
