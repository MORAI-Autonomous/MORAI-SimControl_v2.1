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
from receivers.camera_depth_receiver import CameraDepthReceiver
from receivers.camera_receiver import CameraReceiver
from receivers.camera_semantic_receiver import CameraSemanticReceiver
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

_TPL_RGB = "Camera RGB.tmpl"
_TPL_DEPTH = "Camera Depth.tmpl"
_TPL_SEMANTIC = "Camera Semantic.tmpl"
_TPL_INSTANCE = "Instance Cam.tmpl"
_TPL_RGB_BBOX = "Camera With 2D_3D Bounding Box.tmpl"
_TEMPLATE_ITEMS = [_TPL_RGB, _TPL_DEPTH, _TPL_SEMANTIC, _TPL_INSTANCE, _TPL_RGB_BBOX]
_DEPTH_VIEW_GRAYSCALE = "Grayscale"
_DEPTH_VIEW_COLOR_MAP = "Color Map"
_DEPTH_VIEW_ITEMS = [_DEPTH_VIEW_GRAYSCALE, _DEPTH_VIEW_COLOR_MAP]
_DEPTH_SCALE_MORAI_255 = "MORAI 0-255"
_DEPTH_SCALE_RAW_32FC1 = "Raw 32FC1"
_DEPTH_SCALE_ITEMS = [_DEPTH_SCALE_MORAI_255, _DEPTH_SCALE_RAW_32FC1]
_DEPTH_SCALE_M = 200.0 / 255.0
_TEMPLATE_PATHS = {
    _TPL_RGB_BBOX: os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "templates",
        _TPL_RGB_BBOX,
    ),
}


@dataclass
class _SlotState:
    receiver: Optional[object] = None
    receiver_kind: str = ""
    depth_view_mode: str = _DEPTH_VIEW_GRAYSCALE
    depth_scale_mode: str = _DEPTH_SCALE_MORAI_255
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

    with dpg.group(parent=parent):
        _section("CONTROL")
        with dpg.group(horizontal=True):
            dpg.add_text("Multi-sensor monitor (4 slots)", color=(210, 210, 215, 255))
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
        height=520,
        border=True,
        autosize_x=False,
        autosize_y=False,
        no_scrollbar=True,
        no_scroll_with_mouse=True,
        tag=_tag(slot, "card"),
    ):
        dpg.add_text(f"Sensor {slot + 1}", color=(200, 200, 100, 255))
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text("Template:", color=(180, 180, 180, 255))
            dpg.add_combo(
                items=_TEMPLATE_ITEMS,
                default_value=_TPL_RGB,
                width=220,
                tag=_tag(slot, "template"),
                callback=lambda sender, app_data, user_data: _on_state_change(user_data),
                user_data=slot,
            )
        with dpg.group(horizontal=True):
            dpg.add_text("Depth View:", color=(180, 180, 180, 255))
            dpg.add_combo(
                items=_DEPTH_VIEW_ITEMS,
                default_value=_DEPTH_VIEW_GRAYSCALE,
                width=110,
                tag=_tag(slot, "depth_view"),
                callback=lambda sender, app_data, user_data: _on_depth_view_change(
                    user_data,
                    app_data,
                ),
                user_data=slot,
            )
            dpg.add_text("Scale:", color=(180, 180, 180, 255))
            dpg.add_combo(
                items=_DEPTH_SCALE_ITEMS,
                default_value=_DEPTH_SCALE_MORAI_255,
                width=110,
                tag=_tag(slot, "depth_scale"),
                callback=lambda sender, app_data, user_data: _on_depth_scale_change(
                    user_data,
                    app_data,
                ),
                user_data=slot,
            )
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
            _kv("Type", _tag(slot, "type"))
            dpg.add_spacer(width=12)
            _kv("Info", _tag(slot, "info"))
        with dpg.group(horizontal=True):
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
    template_name = _normalize_template(str(dpg.get_value(_tag(slot, "template"))))
    dpg.set_value(_tag(slot, "template"), template_name)
    state.depth_view_mode = _normalize_depth_view(
        str(dpg.get_value(_tag(slot, "depth_view")))
    )
    state.depth_scale_mode = _normalize_depth_scale(
        str(dpg.get_value(_tag(slot, "depth_scale")))
    )

    state.last_frame_t = 0.0
    state.last_rx_t = 0.0
    state.last_debug_log_t = 0.0
    _save_state()

    if template_name == _TPL_RGB:
        state.receiver_kind = "rgb"
        state.receiver = CameraReceiver(
            ip=ip,
            port=port,
            on_frame=lambda frame, s=slot: _on_rgb_frame(s, frame),
            show=False,
        )
    elif template_name == _TPL_DEPTH:
        state.receiver_kind = "depth"
        state.receiver = CameraDepthReceiver(
            ip=ip,
            port=port,
            on_packet=lambda packet, s=slot: _on_depth_packet(s, packet),
        )
    elif template_name == _TPL_SEMANTIC:
        state.receiver_kind = "semantic"
        state.receiver = CameraSemanticReceiver(
            ip=ip,
            port=port,
            on_packet=lambda packet, s=slot: _on_semantic_packet(s, packet),
        )
    elif template_name == _TPL_INSTANCE:
        state.receiver_kind = "instance"
        state.receiver = CameraSemanticReceiver(
            ip=ip,
            port=port,
            on_packet=lambda packet, s=slot: _on_instance_packet(s, packet),
        )
    else:
        state.receiver_kind = "bbox"
        state.receiver = CameraSensorReceiver(
            ip=ip,
            port=port,
            on_packet=lambda packet, s=slot: _on_bbox_packet(s, packet),
            tmpl_path=_TEMPLATE_PATHS[_TPL_RGB_BBOX],
        )

    state.receiver.start()
    dpg.configure_item(_tag(slot, "btn_start"), enabled=False)
    dpg.configure_item(_tag(slot, "template"), enabled=False)
    dpg.set_value(_tag(slot, "status"), "Running")
    dpg.configure_item(_tag(slot, "status"), color=(100, 220, 100, 255))
    dpg.set_value(_tag(slot, "fps"), "-")
    dpg.set_value(_tag(slot, "size"), "-")
    dpg.set_value(_tag(slot, "type"), _receiver_type_text(state.receiver_kind))
    dpg.set_value(_tag(slot, "info"), "-")
    dpg.set_value(_tag(slot, "last_rx"), "-")
    log.append(
        f"[CameraSensor:{slot + 1}] start {ip}:{port} template={template_name}",
        "INFO",
    )


def _stop_slot(slot: int) -> None:
    state = _slots[slot]
    if state.receiver is not None:
        try:
            state.receiver.stop()
        except Exception:
            pass
        state.receiver = None
    state.receiver_kind = ""

    start_tag = _tag(slot, "btn_start")
    if dpg.does_item_exist(start_tag):
        dpg.configure_item(start_tag, enabled=True)
        dpg.configure_item(_tag(slot, "template"), enabled=True)
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
        dpg.set_value(_tag(slot, "type"), "-")
        dpg.set_value(_tag(slot, "info"), "-")
        dpg.set_value(_tag(slot, "last_rx"), "-")


def _on_rgb_frame(slot: int, frame: np.ndarray) -> None:
    state = _slots[slot]
    now = time.monotonic()
    state.last_rx_t = now
    if now - state.last_frame_t < _FRAME_INTERVAL:
        return
    state.last_frame_t = now

    src_h, src_w = frame.shape[:2]
    fps = float(state.receiver.fps if state.receiver is not None else 0.0)
    if now - state.last_debug_log_t >= 1.0:
        state.last_debug_log_t = now
        log.append(
            f"[CameraSensor:{slot + 1}][RGB] frame={src_w}x{src_h} fps={fps:.1f}",
            "INFO",
        )
    _render_slot_image(
        slot=slot,
        display_bgr=frame,
        src_w=src_w,
        src_h=src_h,
        fps=fps,
        type_text="RGB",
        info_text="Raw RGB",
        rx_t=now,
    )


def _on_bbox_packet(slot: int, packet: dict) -> None:
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
    fps = float(packet.get("fps", state.receiver.fps if state.receiver is not None else 0.0))
    object_count = int(packet.get("object_count", len(objects)))
    packet_seq = int(packet.get("packet_seq", 0))

    if now - state.last_debug_log_t >= 1.0:
        state.last_debug_log_t = now
        log.append(
            f"[CameraSensor:{slot + 1}][BBox] pkt={packet_seq} objects={object_count} "
            f"drawn2d={draw_stats['drawn_2d']} drawn3d={draw_stats['drawn_3d']} "
            f"frame={src_w}x{src_h}",
            "INFO",
        )
    _render_slot_image(
        slot=slot,
        display_bgr=overlay,
        src_w=src_w,
        src_h=src_h,
        fps=fps,
        type_text="RGB+BBox",
        info_text=f"Objects: {object_count}",
        rx_t=now,
    )


def _on_depth_packet(slot: int, packet: dict) -> None:
    state = _slots[slot]
    now = time.monotonic()
    state.last_rx_t = now
    if now - state.last_frame_t < _FRAME_INTERVAL:
        return
    state.last_frame_t = now

    depth_raw = packet.get("depth_raw")
    if depth_raw is None:
        return
    depth_m = _scale_depth(depth_raw, state.depth_scale_mode)

    vis_bgr = _visualize_depth(
        depth_m,
        min_m=0.0,
        max_m=200.0,
        view_mode=state.depth_view_mode,
    )
    src_h, src_w = vis_bgr.shape[:2]
    fps = float(packet.get("fps", state.receiver.fps if state.receiver is not None else 0.0))
    depth_min_m, depth_max_m = _depth_range(depth_m)
    depth_raw_min = float(packet.get("depth_raw_min", 0.0))
    depth_raw_max = float(packet.get("depth_raw_max", 0.0))
    encoding = str(packet.get("encoding", "32FC1"))

    if now - state.last_debug_log_t >= 1.0:
        state.last_debug_log_t = now
        log.append(
            f"[CameraSensor:{slot + 1}][Depth] frame={src_w}x{src_h} "
            f"raw={depth_raw_min:.2f}~{depth_raw_max:.2f} "
            f"depth={depth_min_m:.2f}~{depth_max_m:.2f}m "
            f"scale={state.depth_scale_mode} fps={fps:.1f}",
            "INFO",
        )
    _render_slot_image(
        slot=slot,
        display_bgr=vis_bgr,
        src_w=src_w,
        src_h=src_h,
        fps=fps,
        type_text=encoding,
        info_text=(
            f"Raw: {depth_raw_min:.1f}~{depth_raw_max:.1f}  "
            f"Depth: {depth_min_m:.1f}~{depth_max_m:.1f}m"
        ),
        rx_t=now,
    )


def _on_semantic_packet(slot: int, packet: dict) -> None:
    _on_segmentation_packet(slot, packet, label="Semantic", log_key="Semantic")


def _on_instance_packet(slot: int, packet: dict) -> None:
    _on_segmentation_packet(slot, packet, label="Instance", log_key="Instance")


def _on_segmentation_packet(slot: int, packet: dict, label: str, log_key: str) -> None:
    state = _slots[slot]
    now = time.monotonic()
    state.last_rx_t = now
    if now - state.last_frame_t < _FRAME_INTERVAL:
        return
    state.last_frame_t = now

    frame = packet.get("frame")
    if frame is None:
        return

    src_h, src_w = frame.shape[:2]
    fps = float(packet.get("fps", state.receiver.fps if state.receiver is not None else 0.0))
    pixel_format = str(packet.get("pixel_format", "Semantic"))
    step = int(packet.get("step", 0))
    image_size = int(packet.get("image_size", 0))
    value_range = str(packet.get("value_range", "-"))
    unique_count = int(packet.get("unique_count", 0))
    parse_mode = str(packet.get("parse_mode", "-"))

    if now - state.last_debug_log_t >= 1.0:
        state.last_debug_log_t = now
        log.append(
            f"[CameraSensor:{slot + 1}][{log_key}] frame={src_w}x{src_h} "
            f"format={pixel_format} step={step} image_size={image_size} "
            f"mode={parse_mode} range={value_range} unique={unique_count} fps={fps:.1f}",
            "INFO",
        )

    if pixel_format == "LABEL8":
        info_text = f"Labels: {value_range} ({unique_count})"
    else:
        info_text = f"{pixel_format} step={step}"
    _render_slot_image(
        slot=slot,
        display_bgr=frame,
        src_w=src_w,
        src_h=src_h,
        fps=fps,
        type_text=label,
        info_text=info_text,
        rx_t=now,
    )


def _render_slot_image(
    slot: int,
    display_bgr: np.ndarray,
    src_w: int,
    src_h: int,
    fps: float,
    type_text: str,
    info_text: str,
    rx_t: float,
) -> None:
    scale = min(_VIEW_W / max(1, src_w), _VIEW_H / max(1, src_h), 1.0)
    view_w = max(1, int(src_w * scale))
    view_h = max(1, int(src_h * scale))
    resized = cv2.resize(display_bgr, (view_w, view_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((_TEX_H, _TEX_W, 4), dtype=np.float32)
    rgba = cv2.cvtColor(resized, cv2.COLOR_BGR2RGBA).astype(np.float32) / 255.0
    canvas[:view_h, :view_w, :] = rgba
    flat = canvas.flatten()

    def _apply(
        data=flat,
        src_width=src_w,
        src_height=src_h,
        thumb_w=view_w,
        thumb_h=view_h,
        frame_fps=fps,
        kind_text=type_text,
        extra_info=info_text,
        rx_time=rx_t,
        s=slot,
    ) -> None:
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
        dpg.set_value(_tag(s, "type"), kind_text)
        dpg.set_value(_tag(s, "info"), extra_info)
        age = max(0.0, time.monotonic() - rx_time)
        dpg.set_value(_tag(s, "last_rx"), f"{age:.2f}s ago")

    ui_queue.post(_apply)


def _visualize_depth(
    depth_m: np.ndarray,
    min_m: float,
    max_m: float,
    view_mode: str,
) -> np.ndarray:
    min_m = max(0.0, float(min_m))
    max_m = max(min_m + 1e-3, float(max_m))

    valid = depth_m > 0.0
    clipped = np.clip(depth_m, min_m, max_m)
    scaled = 1.0 - ((clipped - min_m) / (max_m - min_m))
    scaled = np.clip(scaled, 0.0, 1.0)
    gray = (scaled * 255.0).astype(np.uint8)
    gray[~valid] = 0

    if view_mode == "Color Map":
        vis = cv2.applyColorMap(gray, cv2.COLORMAP_TURBO)
        vis[~valid] = 0
        return vis
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _receiver_type_text(kind: str) -> str:
    if kind == "rgb":
        return "RGB"
    if kind == "bbox":
        return "RGB+BBox"
    if kind == "depth":
        return "32FC1"
    if kind == "semantic":
        return "Semantic"
    if kind == "instance":
        return "Instance"
    return "-"


def _normalize_template(template_name: str) -> str:
    legacy_names = {
        "Camera Template.tmpl": _TPL_RGB,
        "Camera Depth Template.tmpl": _TPL_DEPTH,
        "CameraSensorMessageTemplate.tmpl": _TPL_RGB_BBOX,
        "CameraWithBboxMessageTemplate.tmpl": _TPL_RGB_BBOX,
        "Camera With Bbox Message Template.tmpl": _TPL_RGB_BBOX,
    }
    if template_name in legacy_names:
        return legacy_names[template_name]
    if template_name in _TEMPLATE_ITEMS:
        return template_name
    return _TPL_RGB


def _normalize_depth_view(view_mode: str) -> str:
    if view_mode in _DEPTH_VIEW_ITEMS:
        return view_mode
    return _DEPTH_VIEW_GRAYSCALE


def _normalize_depth_scale(scale_mode: str) -> str:
    if scale_mode in _DEPTH_SCALE_ITEMS:
        return scale_mode
    return _DEPTH_SCALE_MORAI_255


def _scale_depth(depth_raw: np.ndarray, scale_mode: str) -> np.ndarray:
    if scale_mode == _DEPTH_SCALE_RAW_32FC1:
        return depth_raw
    return depth_raw * _DEPTH_SCALE_M


def _depth_range(depth_m: np.ndarray) -> tuple:
    valid = depth_m > 0.0
    if np.any(valid):
        return float(np.min(depth_m[valid])), float(np.max(depth_m[valid]))
    return 0.0, 0.0


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


def _on_depth_view_change(slot: int, view_mode: str) -> None:
    _slots[slot].depth_view_mode = _normalize_depth_view(str(view_mode))
    _save_state()


def _on_depth_scale_change(slot: int, scale_mode: str) -> None:
    _slots[slot].depth_scale_mode = _normalize_depth_scale(str(scale_mode))
    _save_state()


def _save_state() -> None:
    slots = []
    for slot in range(_SLOT_COUNT):
        ip_tag = _tag(slot, "ip")
        port_tag = _tag(slot, "port")
        template_tag = _tag(slot, "template")
        depth_view_tag = _tag(slot, "depth_view")
        depth_scale_tag = _tag(slot, "depth_scale")
        if (
            not dpg.does_item_exist(ip_tag)
            or not dpg.does_item_exist(port_tag)
            or not dpg.does_item_exist(template_tag)
            or not dpg.does_item_exist(depth_view_tag)
            or not dpg.does_item_exist(depth_scale_tag)
        ):
            return
        slots.append(
            {
                "name": f"Sensor {slot + 1}",
                "ip": dpg.get_value(ip_tag).strip() or "0.0.0.0",
                "port": int(dpg.get_value(port_tag)),
                "template": _normalize_template(str(dpg.get_value(template_tag))),
                "depth_view": _normalize_depth_view(str(dpg.get_value(depth_view_tag))),
                "depth_scale": _normalize_depth_scale(str(dpg.get_value(depth_scale_tag))),
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
            if dpg.does_item_exist(_tag(slot, "template")):
                dpg.set_value(
                    _tag(slot, "template"),
                    _normalize_template(str(slots[slot].get("template", _TPL_RGB))),
                )
            if dpg.does_item_exist(_tag(slot, "depth_view")):
                depth_view_mode = _normalize_depth_view(
                    str(slots[slot].get("depth_view", _DEPTH_VIEW_GRAYSCALE))
                )
                dpg.set_value(_tag(slot, "depth_view"), depth_view_mode)
                _slots[slot].depth_view_mode = depth_view_mode
            if dpg.does_item_exist(_tag(slot, "depth_scale")):
                depth_scale_mode = _normalize_depth_scale(
                    str(slots[slot].get("depth_scale", _DEPTH_SCALE_MORAI_255))
                )
                dpg.set_value(_tag(slot, "depth_scale"), depth_scale_mode)
                _slots[slot].depth_scale_mode = depth_scale_mode
        except Exception as exc:
            log.append(f"[CameraSensor] apply state error: {exc}", "ERROR")


def _tag(slot: int, suffix: str) -> str:
    return f"cam_sensor_{slot}_{suffix}"
