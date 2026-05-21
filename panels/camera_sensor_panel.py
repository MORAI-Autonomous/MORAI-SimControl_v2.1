from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional

import cv2
import dearpygui.dearpygui as dpg
import numpy as np

import panels.log as log
from receivers.camera_sensor_receiver import CameraSensorReceiver, draw_bbox_overlays
import utils.ui_queue as ui_queue

_SLOT_COUNT = 4
_GRID_COLUMNS = 2
_VIEW_W = 520
_VIEW_H = 292
_FRAME_INTERVAL = 1.0 / 30.0
_TEX_W = 960
_TEX_H = 540
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "camera_sensor_state.json",
)
_TEX_BLANK: list = [0.0] * (_TEX_W * _TEX_H * 4)


@dataclass
class _SlotState:
    receiver: Optional[CameraSensorReceiver] = None
    last_frame_t: float = 0.0
    last_rx_t: float = 0.0
    last_debug_log_t: float = 0.0


_slots: Dict[int, _SlotState] = {i: _SlotState() for i in range(_SLOT_COUNT)}


def build(parent) -> None:
    with dpg.texture_registry():
        for slot in range(_SLOT_COUNT):
            tex_tag = _tag(slot, "texture")
            if not dpg.does_item_exist(tex_tag):
                dpg.add_dynamic_texture(
                    width=_TEX_W,
                    height=_TEX_H,
                    default_value=_TEX_BLANK,
                    tag=tex_tag,
                )

    with dpg.child_window(parent=parent, width=-1, height=-1, border=False):
        _section("CONTROL")
        with dpg.group(horizontal=True):
            dpg.add_text("Multi-camera monitor (4 slots)", color=(210, 210, 215, 255))
            dpg.add_spacer(width=12)
            dpg.add_button(label="Start All", width=100, callback=lambda: _start_all())
            dpg.add_button(label="Stop All", width=100, callback=lambda: stop())

        dpg.add_spacer(height=6)
        with dpg.table(
            header_row=False,
            borders_innerH=False,
            borders_innerV=False,
            borders_outerH=False,
            borders_outerV=False,
            resizable=False,
            policy=dpg.mvTable_SizingStretchProp,
        ):
            for _ in range(_GRID_COLUMNS):
                dpg.add_table_column()
            for row in range((_SLOT_COUNT + _GRID_COLUMNS - 1) // _GRID_COLUMNS):
                with dpg.table_row():
                    for col in range(_GRID_COLUMNS):
                        slot = row * _GRID_COLUMNS + col
                        with dpg.table_cell():
                            if slot < _SLOT_COUNT:
                                _build_slot(slot)

    _load_state()


def stop() -> None:
    for slot in range(_SLOT_COUNT):
        _stop_slot(slot)


def _build_slot(slot: int) -> None:
    with dpg.child_window(
        width=-1,
        height=500,
        border=True,
        autosize_x=False,
        autosize_y=False,
        tag=_tag(slot, "card"),
    ):
        dpg.add_text(f"Camera {slot + 1}", color=(200, 200, 100, 255))
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text("IP:", color=(180, 180, 180, 255))
            dpg.add_input_text(
                tag=_tag(slot, "ip"),
                default_value="0.0.0.0",
                width=120,
                callback=lambda sender, app_data, user_data: _on_state_change(user_data),
                user_data=slot,
            )
            dpg.add_text("Port:", color=(180, 180, 180, 255))
            dpg.add_input_int(
                tag=_tag(slot, "port"),
                default_value=9096 + slot,
                width=80,
                min_value=1,
                max_value=65535,
                step=0,
                callback=lambda sender, app_data, user_data: _on_state_change(user_data),
                user_data=slot,
            )
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Start",
                tag=_tag(slot, "btn_start"),
                width=80,
                callback=lambda sender, app_data, user_data: _start_slot(user_data),
                user_data=slot,
            )
            dpg.add_button(
                label="Stop",
                tag=_tag(slot, "btn_stop"),
                width=80,
                callback=lambda sender, app_data, user_data: _stop_slot(user_data),
                user_data=slot,
            )
            dpg.add_text("Stopped", tag=_tag(slot, "status"), color=(180, 80, 80, 255))

        with dpg.group(horizontal=True):
            _kv("FPS", _tag(slot, "fps"))
            dpg.add_spacer(width=12)
            _kv("Frame", _tag(slot, "size"))
        with dpg.group(horizontal=True):
            _kv("Objects", _tag(slot, "objects"))
            dpg.add_spacer(width=12)
            _kv("Last RX", _tag(slot, "last_rx"))

        dpg.add_spacer(height=4)
        with dpg.child_window(
            width=-1,
            height=330,
            border=False,
            horizontal_scrollbar=True,
        ):
            dpg.add_image(
                _tag(slot, "texture"),
                width=_VIEW_W,
                height=_VIEW_H,
                tag=_tag(slot, "image"),
            )


def _start_all() -> None:
    for slot in range(_SLOT_COUNT):
        _start_slot(slot)


def _start_slot(slot: int) -> None:
    state = _slots[slot]
    if state.receiver is not None and state.receiver.is_alive():
        log.append(f"[CameraSensor:{slot + 1}] already running", "WARN")
        return

    ip = dpg.get_value(_tag(slot, "ip")).strip() or "0.0.0.0"
    port = int(dpg.get_value(_tag(slot, "port")))
    state.last_frame_t = 0.0
    state.last_rx_t = 0.0
    state.last_debug_log_t = 0.0
    _save_state()

    state.receiver = CameraSensorReceiver(
        ip=ip,
        port=port,
        on_packet=lambda packet, s=slot: _on_packet(s, packet),
    )
    state.receiver.start()
    dpg.configure_item(_tag(slot, "btn_start"), enabled=False)
    dpg.set_value(_tag(slot, "status"), "Running")
    dpg.configure_item(_tag(slot, "status"), color=(100, 220, 100, 255))
    dpg.set_value(_tag(slot, "fps"), "-")
    dpg.set_value(_tag(slot, "size"), "-")
    dpg.set_value(_tag(slot, "objects"), "-")
    dpg.set_value(_tag(slot, "last_rx"), "-")
    log.append(f"[CameraSensor:{slot + 1}] start {ip}:{port}", "INFO")


def _stop_slot(slot: int) -> None:
    state = _slots[slot]
    if state.receiver is not None:
        try:
            state.receiver.stop()
        except Exception:
            pass
        state.receiver = None

    start_tag = _tag(slot, "btn_start")
    if dpg.does_item_exist(start_tag):
        dpg.configure_item(start_tag, enabled=True)
        dpg.set_value(_tag(slot, "status"), "Stopped")
        dpg.configure_item(_tag(slot, "status"), color=(180, 80, 80, 255))
        dpg.set_value(_tag(slot, "texture"), _TEX_BLANK)
        dpg.configure_item(
            _tag(slot, "image"),
            width=_VIEW_W,
            height=_VIEW_H,
            uv_min=(0.0, 0.0),
            uv_max=(_VIEW_W / _TEX_W, _VIEW_H / _TEX_H),
        )
        dpg.set_value(_tag(slot, "fps"), "-")
        dpg.set_value(_tag(slot, "size"), "-")
        dpg.set_value(_tag(slot, "objects"), "-")
        dpg.set_value(_tag(slot, "last_rx"), "-")


def _on_packet(slot: int, packet: dict) -> None:
    state = _slots[slot]
    now = time.monotonic()
    state.last_rx_t = now
    if now - state.last_frame_t < _FRAME_INTERVAL:
        return
    state.last_frame_t = now

    frame = packet.get("frame")
    if frame is None:
        return

    objects = packet.get("objects", [])
    overlay, draw_stats = draw_bbox_overlays(frame, objects)
    src_h, src_w = overlay.shape[:2]
    scale = min(_VIEW_W / max(1, src_w), _VIEW_H / max(1, src_h), 1.0)
    view_w = max(1, int(src_w * scale))
    view_h = max(1, int(src_h * scale))
    resized = cv2.resize(overlay, (view_w, view_h))

    canvas = np.zeros((_TEX_H, _TEX_W, 4), dtype=np.float32)
    rgba = cv2.cvtColor(resized, cv2.COLOR_BGR2RGBA).astype(np.float32) / 255.0
    canvas[:view_h, :view_w, :] = rgba
    flat = canvas.flatten()

    fps = float(packet.get("fps", state.receiver.fps if state.receiver is not None else 0.0))
    object_count = int(packet.get("object_count", len(objects)))
    packet_seq = int(packet.get("packet_seq", 0))

    if now - state.last_debug_log_t >= 1.0:
        state.last_debug_log_t = now
        log.append(
            f"[CameraSensor:{slot + 1}] pkt={packet_seq} objects={object_count} "
            f"drawn2d={draw_stats['drawn_2d']} drawn3d={draw_stats['drawn_3d']} "
            f"frame={src_w}x{src_h}",
            "INFO",
        )

    def _apply(
        data=flat,
        src_width=src_w,
        src_height=src_h,
        thumb_w=view_w,
        thumb_h=view_h,
        frame_fps=fps,
        count=object_count,
        rx=now,
        s=slot,
    ):
        tex_tag = _tag(s, "texture")
        if not dpg.does_item_exist(tex_tag):
            return
        dpg.set_value(tex_tag, data)
        dpg.configure_item(
            _tag(s, "image"),
            width=thumb_w,
            height=thumb_h,
            uv_min=(0.0, 0.0),
            uv_max=(thumb_w / _TEX_W, thumb_h / _TEX_H),
        )
        dpg.set_value(_tag(s, "fps"), f"{frame_fps:.1f}")
        dpg.set_value(_tag(s, "size"), f"{src_width} x {src_height}")
        dpg.set_value(_tag(s, "objects"), str(count))
        age = max(0.0, time.monotonic() - rx)
        dpg.set_value(_tag(s, "last_rx"), f"{age:.2f}s ago")

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


def _on_state_change(slot: int) -> None:
    _save_state()


def _save_state() -> None:
    slots = []
    for slot in range(_SLOT_COUNT):
        ip_tag = _tag(slot, "ip")
        port_tag = _tag(slot, "port")
        if not dpg.does_item_exist(ip_tag) or not dpg.does_item_exist(port_tag):
            return
        slots.append(
            {
                "name": f"Camera {slot + 1}",
                "ip": dpg.get_value(ip_tag).strip() or "0.0.0.0",
                "port": int(dpg.get_value(port_tag)),
            }
        )

    data = {"camera_count": _SLOT_COUNT, "slots": slots}
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
    except Exception as exc:
        log.append(f"[CameraSensor] save state error: {exc}", "ERROR")


def _load_state() -> None:
    if not os.path.isfile(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception as exc:
        log.append(f"[CameraSensor] load state error: {exc}", "ERROR")
        return

    slots = data.get("slots", [])
    for slot in range(min(_SLOT_COUNT, len(slots))):
        try:
            if dpg.does_item_exist(_tag(slot, "ip")):
                dpg.set_value(_tag(slot, "ip"), str(slots[slot].get("ip", "0.0.0.0")))
            if dpg.does_item_exist(_tag(slot, "port")):
                dpg.set_value(_tag(slot, "port"), int(slots[slot].get("port", 9096 + slot)))
        except Exception as exc:
            log.append(f"[CameraSensor] apply state error: {exc}", "ERROR")


def _tag(slot: int, suffix: str) -> str:
    return f"cam_sensor_{slot}_{suffix}"
