from __future__ import annotations

import json
import math
import os
import socket
import time
from dataclasses import dataclass
from typing import Dict, Optional

import dearpygui.dearpygui as dpg

import panels.log as log
from panels.monitor_receiver import UDPThread
from receivers.radar_sensor_data import (
    build_detection_view,
    build_object_view,
    format_detection_list,
    format_object_list,
)
from receivers.template_parser import TemplateParser
from utils.project_paths import ROOT_DIR
from utils.template_paths import resolve_template_path
import utils.ui_queue as ui_queue

_OBJECTS = "objects"
_DETECTIONS = "detections"
_STREAM_ORDER = (_OBJECTS, _DETECTIONS)
_TEMPLATES = {
    _OBJECTS: "ARS540RadarObjectList.tmpl",
    _DETECTIONS: "ARS540RadarDetectionList.tmpl",
}
_DEFAULT_PORTS = {
    _OBJECTS: 9091,
    _DETECTIONS: 9092,
}
_STATE_FILE = os.path.join(str(ROOT_DIR), "config", "radar_sensor_state.json")
_UPDATE_INTERVAL = 0.05
_DOPPLER_RED = (255, 120, 80, 255)
_DOPPLER_BLUE = (80, 180, 255, 255)
_DOPPLER_NEUTRAL = (245, 220, 80, 255)
_object_color_item_tags = []


@dataclass
class _StreamState:
    sock: Optional[socket.socket] = None
    thread: Optional[UDPThread] = None
    parser: Optional[TemplateParser] = None
    last_update_t: float = 0.0


@dataclass
class _CameraState:
    x: float = 0.0
    y: float = -2.8
    z: float = 1.0
    yaw_degrees: float = 0.0
    pitch_degrees: float = -20.0
    move_offset: float = 0.12


_streams: Dict[str, _StreamState] = {
    stream: _StreamState() for stream in _STREAM_ORDER
}
_camera = _CameraState()
_detection_view: dict = {"detections": [], "plot_x": [], "plot_y": [], "plot_z": []}


def build(parent) -> None:
    with dpg.group(parent=parent):
        _section("ARS540 UDP STREAMS")
        dpg.add_text(
            "Configure the simulator Object List and Detection List templates "
            "to send to the ports below.",
            color=(190, 190, 195, 255),
        )
        dpg.add_spacer(height=4)

        with dpg.table(
            header_row=True,
            borders_innerH=True,
            borders_innerV=True,
            borders_outerH=True,
            borders_outerV=True,
            resizable=True,
            policy=dpg.mvTable_SizingStretchProp,
        ):
            dpg.add_table_column(label="Stream", width_fixed=True, init_width_or_weight=100)
            dpg.add_table_column(label="Template", init_width_or_weight=220)
            dpg.add_table_column(label="Bind IP", width_fixed=True, init_width_or_weight=120)
            dpg.add_table_column(label="Port", width_fixed=True, init_width_or_weight=80)
            dpg.add_table_column(label="Status", width_fixed=True, init_width_or_weight=100)

            for stream in _STREAM_ORDER:
                with dpg.table_row():
                    dpg.add_text(_stream_title(stream))
                    dpg.add_text(_TEMPLATES[stream], color=(160, 190, 220, 255))
                    dpg.add_input_text(
                        tag=_tag(stream, "ip"),
                        default_value="0.0.0.0",
                        width=-1,
                        callback=lambda sender, app_data, user_data: _save_state(),
                    )
                    dpg.add_input_int(
                        tag=_tag(stream, "port"),
                        default_value=_DEFAULT_PORTS[stream],
                        width=-1,
                        min_value=1,
                        max_value=65535,
                        step=0,
                        callback=lambda sender, app_data, user_data: _save_state(),
                    )
                    dpg.add_text(
                        "Stopped",
                        tag=_tag(stream, "status"),
                        color=(180, 80, 80, 255),
                    )

        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Start Both", width=110, callback=lambda: _start_all())
            dpg.add_button(label="Stop Both", width=110, callback=lambda: stop())
            dpg.add_text(
                "Both streams require different UDP ports.",
                color=(150, 150, 160, 255),
            )

        dpg.add_spacer(height=8)
        with dpg.tab_bar(tag="radar_sensor_view_tabs", callback=_on_view_tab):
            with dpg.tab(label="Top View - Object List"):
                _build_top_view()
            with dpg.tab(
                label="Top View - Detection List",
                tag=_tag(_DETECTIONS, "top_tab"),
            ):
                _build_detection_top_view()
            with dpg.tab(
                label="Novel View - Detection Point Cloud",
                tag=_tag(_DETECTIONS, "novel_tab"),
            ):
                _build_novel_view()

    _load_state()


def stop() -> None:
    for stream in _STREAM_ORDER:
        _stop_stream(stream)


def _build_top_view() -> None:
    dpg.add_text(
        "Waiting for ARS540 Radar Object List packets...",
        tag=_tag(_OBJECTS, "summary"),
        color=(190, 190, 195, 255),
    )
    with dpg.plot(
        label="Object positions in sensor coordinates",
        height=380,
        width=-1,
        equal_aspects=True,
    ):
        dpg.add_plot_legend()
        x_axis = dpg.add_plot_axis(
            dpg.mvXAxis,
            label="X / lateral (m)",
            tag=_tag(_OBJECTS, "x_axis"),
        )
        y_axis = dpg.add_plot_axis(
            dpg.mvYAxis,
            label="Y / forward (m)",
            tag=_tag(_OBJECTS, "y_axis"),
        )
        dpg.add_scatter_series(
            [0.0],
            [0.0],
            label="Sensor",
            parent=y_axis,
        )
        dpg.set_axis_limits(x_axis, -100.0, 100.0)
        dpg.set_axis_limits(y_axis, -100.0, 100.0)

    dpg.add_text("Object List", color=(200, 200, 100, 255))
    dpg.add_input_text(
        tag=_tag(_OBJECTS, "list"),
        multiline=True,
        readonly=True,
        width=-1,
        height=260,
        default_value="(0 objects)",
    )


def _build_detection_top_view() -> None:
    dpg.add_text(
        "Waiting for ARS540 Radar Detection List packets...",
        tag=_tag(_DETECTIONS, "summary"),
        color=(190, 190, 195, 255),
    )
    with dpg.plot(
        label="Detection positions in sensor coordinates",
        height=380,
        width=-1,
        equal_aspects=True,
    ):
        dpg.add_plot_legend()
        x_axis = dpg.add_plot_axis(
            dpg.mvXAxis,
            label="X / lateral (m)",
            tag=_tag(_DETECTIONS, "x_axis"),
        )
        y_axis = dpg.add_plot_axis(
            dpg.mvYAxis,
            label="Y / forward (m)",
            tag=_tag(_DETECTIONS, "y_axis"),
        )
        dpg.add_scatter_series(
            [0.0],
            [0.0],
            label="Sensor",
            parent=y_axis,
        )
        dpg.add_scatter_series(
            [],
            [],
            label="Detections",
            tag=_tag(_DETECTIONS, "series"),
            parent=y_axis,
        )
        dpg.set_axis_limits(x_axis, -100.0, 100.0)
        dpg.set_axis_limits(y_axis, -100.0, 100.0)

    dpg.add_text("Detection List", color=(200, 200, 100, 255))
    dpg.add_input_text(
        tag=_tag(_DETECTIONS, "list"),
        multiline=True,
        readonly=True,
        width=-1,
        height=260,
        default_value="(0 detections)",
    )


def _build_novel_view() -> None:
    dpg.add_text(
        "Hover the point cloud for control help.",
        color=(150, 150, 160, 255),
    )
    with dpg.group(horizontal=True):
        dpg.add_text("Camera", tag=_tag(_DETECTIONS, "camera"))
        dpg.add_input_float(
            label="Move Offset",
            tag=_tag(_DETECTIONS, "move_offset"),
            default_value=_camera.move_offset,
            width=100,
            format="%.3f",
            min_value=0.001,
            max_value=10.0,
            min_clamped=True,
            max_clamped=True,
            callback=_on_move_offset,
        )
        dpg.add_button(label="Reset View", width=90, callback=lambda: _reset_camera())

    with dpg.group(horizontal=True):
        with dpg.child_window(
            tag=_tag(_DETECTIONS, "translation_panel"),
            width=510,
            height=82,
            no_scrollbar=True,
        ):
            dpg.add_text("Translation - WASD / R F")
            with dpg.group(horizontal=True):
                _add_camera_button("W Forward", dpg.mvKey_W)
                _add_camera_button("A Left", dpg.mvKey_A)
                _add_camera_button("S Back", dpg.mvKey_S)
                _add_camera_button("D Right", dpg.mvKey_D)
                _add_camera_button("R Up", dpg.mvKey_R)
                _add_camera_button("F Down", dpg.mvKey_F)
        with dpg.child_window(
            tag=_tag(_DETECTIONS, "rotation_panel"),
            width=380,
            height=82,
            no_scrollbar=True,
        ):
            dpg.add_text("Rotation - IJKL")
            with dpg.group(horizontal=True):
                _add_camera_button("I Pitch+", dpg.mvKey_I)
                _add_camera_button("J Yaw-", dpg.mvKey_J)
                _add_camera_button("K Pitch-", dpg.mvKey_K)
                _add_camera_button("L Yaw+", dpg.mvKey_L)

    with dpg.group(horizontal=True):
        dpg.add_text("doppler_velocity_meters_per_second:")
        dpg.add_text(
            "Away (+) = Redshift",
            tag=_tag(_DETECTIONS, "doppler_away"),
            color=_DOPPLER_RED,
        )
        dpg.add_text(
            "Approaching (-) = Blueshift",
            tag=_tag(_DETECTIONS, "doppler_approaching"),
            color=_DOPPLER_BLUE,
        )
        dpg.add_text(
            "Near zero = Stationary",
            tag=_tag(_DETECTIONS, "doppler_stationary"),
            color=_DOPPLER_NEUTRAL,
        )

    with dpg.child_window(
        tag=_tag(_DETECTIONS, "viewport_hover"),
        width=920,
        height=500,
        border=False,
        no_scrollbar=True,
    ):
        dpg.add_drawlist(
            tag=_tag(_DETECTIONS, "viewport"),
            width=900,
            height=480,
        )
    with dpg.tooltip(
        parent=_tag(_DETECTIONS, "viewport_hover"),
        tag=_tag(_DETECTIONS, "tooltip"),
        delay=0.4,
    ):
        dpg.add_text(
            "Detection range/azimuth/elevation is converted to an X/Y/Z point cloud.\n"
            "W/S: forward/back  A/D: left/right  R/F: up/down\n"
            "I/K: pitch up/down  J/L: yaw left/right\n"
            "Move Offset sets the translation step.\n"
            "Doppler: away (+) is redshift; approaching (-) is blueshift."
        )
    _install_3d_handlers()
    _render_detection_view()


def _start_all() -> None:
    for stream in _STREAM_ORDER:
        _start_stream(stream)


def _start_stream(stream: str) -> None:
    state = _streams[stream]
    if state.thread is not None and state.thread.is_alive():
        return

    path = resolve_template_path(_TEMPLATES[stream])
    if path is None:
        _set_status(stream, "No template", (255, 80, 80, 255))
        log.append(f"[RadarSensor] missing template: {_TEMPLATES[stream]}", "ERROR")
        return

    ip = str(dpg.get_value(_tag(stream, "ip"))).strip() or "0.0.0.0"
    port = int(dpg.get_value(_tag(stream, "port")))

    try:
        parser = TemplateParser(path)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((ip, port))
    except Exception as exc:
        _set_status(stream, "Bind failed", (255, 80, 80, 255))
        log.append(f"[RadarSensor:{_stream_title(stream)}] {exc}", "ERROR")
        return

    state.parser = parser
    state.sock = sock
    state.last_update_t = 0.0
    state.thread = UDPThread(
        sock=sock,
        parse_fn=parser.parse,
        on_data=lambda parsed, key=stream: _on_data(key, parsed),
        on_error=lambda key=stream: ui_queue.post(lambda: _on_error(key)),
    )
    state.thread.start()
    _set_status(stream, "Running", (100, 220, 100, 255))
    _set_controls_enabled(stream, False)
    _save_state()
    log.append(
        f"[RadarSensor:{_stream_title(stream)}] start {ip}:{port} "
        f"template={_TEMPLATES[stream]}",
        "INFO",
    )


def _stop_stream(stream: str) -> None:
    state = _streams[stream]
    if state.thread is not None:
        state.thread.stop()
        state.thread = None
    if state.sock is not None:
        try:
            state.sock.close()
        except OSError:
            pass
        state.sock = None
    state.parser = None

    if dpg.does_item_exist(_tag(stream, "status")):
        _set_status(stream, "Stopped", (180, 80, 80, 255))
        _set_controls_enabled(stream, True)


def _on_data(stream: str, parsed: dict) -> None:
    state = _streams[stream]
    now = time.monotonic()
    if now - state.last_update_t < _UPDATE_INTERVAL:
        return
    state.last_update_t = now
    ui_queue.post(
        lambda key=stream, packet=parsed: _apply_data(key, packet)
    )


def _apply_data(stream: str, parsed: dict) -> None:
    display_tag = _tag(stream, "y_axis" if stream == _OBJECTS else "series")
    if not dpg.does_item_exist(display_tag):
        return

    if stream == _OBJECTS:
        view = build_object_view(parsed)
        rows = view["objects"]
        list_text = format_object_list(rows)
        item_label = "objects"
        _render_object_series(rows)
    else:
        global _detection_view
        view = build_detection_view(parsed)
        _detection_view = view
        rows = view["detections"]
        list_text = format_detection_list(rows)
        item_label = "detections"
        _render_detection_view()
        dpg.set_value(display_tag, [view["plot_x"], view["plot_y"]])

    _set_top_view_limits(stream, view["plot_x"], view["plot_y"])
    dpg.set_value(_tag(stream, "list"), list_text)
    dpg.set_value(
        _tag(stream, "summary"),
        f"RX {view['seconds']}.{view['nanos']:09d}  |  "
        f"reported {view['reported_count']} {item_label}  |  parsed {len(rows)}",
    )


def _render_object_series(objects: list) -> None:
    for tag in _object_color_item_tags:
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
    _object_color_item_tags.clear()

    groups = {}
    for item in objects:
        color_hash = item["classification_color_hash_rgba"] & 0xFFFFFFFF
        plot_x, plot_y = groups.setdefault(color_hash, ([], []))
        plot_x.append(item["center_x_meters"])
        plot_y.append(item["center_y_meters"])

    for color_hash, (plot_x, plot_y) in groups.items():
        series_tag = _tag(_OBJECTS, f"color_{color_hash:08x}")
        theme_tag = f"{series_tag}_theme"
        with dpg.theme(tag=theme_tag):
            with dpg.theme_component(dpg.mvScatterSeries):
                color = _rgba_color(color_hash)
                dpg.add_theme_color(
                    dpg.mvPlotCol_MarkerFill,
                    color,
                    category=dpg.mvThemeCat_Plots,
                )
                dpg.add_theme_color(
                    dpg.mvPlotCol_MarkerOutline,
                    color,
                    category=dpg.mvThemeCat_Plots,
                )
        dpg.add_scatter_series(
            plot_x,
            plot_y,
            label=f"0x{color_hash:08X}",
            tag=series_tag,
            parent=_tag(_OBJECTS, "y_axis"),
        )
        dpg.bind_item_theme(series_tag, theme_tag)
        _object_color_item_tags.extend((series_tag, theme_tag))


def _rgba_color(color_hash: int) -> tuple:
    return (
        (color_hash >> 24) & 0xFF,
        (color_hash >> 16) & 0xFF,
        (color_hash >> 8) & 0xFF,
        color_hash & 0xFF,
    )


def _set_top_view_limits(stream: str, plot_x: list, plot_y: list) -> None:
    extent = max([25.0] + [abs(value) for value in plot_x + plot_y])
    extent = min(1000.0, extent * 1.2)
    dpg.set_axis_limits(_tag(stream, "x_axis"), -extent, extent)
    dpg.set_axis_limits(_tag(stream, "y_axis"), -extent, extent)


def _install_3d_handlers() -> None:
    handler_tag = _tag(_DETECTIONS, "handlers")
    if dpg.does_item_exist(handler_tag):
        return
    with dpg.handler_registry(tag=handler_tag):
        for key in (
            dpg.mvKey_W,
            dpg.mvKey_A,
            dpg.mvKey_S,
            dpg.mvKey_D,
            dpg.mvKey_R,
            dpg.mvKey_F,
            dpg.mvKey_I,
            dpg.mvKey_J,
            dpg.mvKey_K,
            dpg.mvKey_L,
        ):
            dpg.add_key_press_handler(key=key, callback=_on_camera_key)


def _on_view_tab(sender=None, app_data=None, user_data=None) -> None:
    viewport = _tag(_DETECTIONS, "viewport")
    if dpg.does_item_exist(viewport):
        _render_detection_view()


def _on_camera_key(sender=None, app_data=None, user_data=None) -> None:
    viewport = _tag(_DETECTIONS, "viewport")
    if not dpg.does_item_exist(viewport) or not dpg.is_item_hovered(viewport):
        return
    if _apply_camera_key(int(app_data)):
        _render_detection_view()


def _on_camera_button(sender=None, app_data=None, user_data=None) -> None:
    if _apply_camera_key(int(user_data)):
        _render_detection_view()


def _on_move_offset(sender=None, app_data=None, user_data=None) -> None:
    _camera.move_offset = float(app_data)


def _add_camera_button(label: str, key: int) -> None:
    dpg.add_button(
        label=label,
        width=72,
        callback=_on_camera_button,
        user_data=key,
    )


def _apply_camera_key(key: int) -> bool:
    yaw = math.radians(_camera.yaw_degrees)
    forward = (math.sin(yaw), math.cos(yaw))
    right = (math.cos(yaw), -math.sin(yaw))
    move = _camera.move_offset

    if key == dpg.mvKey_W:
        _camera.x += forward[0] * move
        _camera.y += forward[1] * move
    elif key == dpg.mvKey_S:
        _camera.x -= forward[0] * move
        _camera.y -= forward[1] * move
    elif key == dpg.mvKey_A:
        _camera.x -= right[0] * move
        _camera.y -= right[1] * move
    elif key == dpg.mvKey_D:
        _camera.x += right[0] * move
        _camera.y += right[1] * move
    elif key == dpg.mvKey_J:
        _camera.yaw_degrees = (_camera.yaw_degrees - 5.0) % 360.0
    elif key == dpg.mvKey_L:
        _camera.yaw_degrees = (_camera.yaw_degrees + 5.0) % 360.0
    elif key == dpg.mvKey_I:
        _camera.pitch_degrees = min(85.0, _camera.pitch_degrees + 5.0)
    elif key == dpg.mvKey_K:
        _camera.pitch_degrees = max(-85.0, _camera.pitch_degrees - 5.0)
    elif key == dpg.mvKey_R:
        _camera.z += move
    elif key == dpg.mvKey_F:
        _camera.z -= move
    else:
        return False
    return True


def _reset_camera() -> None:
    _camera.x = 0.0
    _camera.y = -2.8
    _camera.z = 1.0
    _camera.yaw_degrees = 0.0
    _camera.pitch_degrees = -20.0
    _render_detection_view()


def _render_detection_view() -> None:
    viewport = _tag(_DETECTIONS, "viewport")
    if not dpg.does_item_exist(viewport):
        return

    camera_tag = _tag(_DETECTIONS, "camera")
    if dpg.does_item_exist(camera_tag):
        dpg.set_value(
            camera_tag,
            f"Camera x={_camera.x:.2f} y={_camera.y:.2f} "
            f"z={_camera.z:.2f} yaw={_camera.yaw_degrees:.0f} deg "
            f"pitch={_camera.pitch_degrees:.0f} deg",
        )

    dpg.delete_item(viewport, children_only=True)
    width, height = dpg.get_item_rect_size(viewport)
    width = max(640.0, float(width))
    height = max(360.0, float(height))
    dpg.draw_rectangle((0.0, 0.0), (width, height), fill=(15, 18, 25, 255), parent=viewport)

    points = list(zip(
        _detection_view.get("plot_x", []),
        _detection_view.get("plot_y", []),
        _detection_view.get("plot_z", []),
    ))
    extent = max([25.0] + [math.sqrt(x * x + y * y + z * z) for x, y, z in points])
    project = _make_projector(width, height, extent)

    grid_extent = extent
    for index in range(-5, 6):
        offset = grid_extent * index / 5.0
        _draw_3d_line(project, (-grid_extent, offset, 0.0), (grid_extent, offset, 0.0),
                      (45, 50, 60, 255), viewport)
        _draw_3d_line(project, (offset, -grid_extent, 0.0), (offset, grid_extent, 0.0),
                      (45, 50, 60, 255), viewport)

    axis_extent = extent * 0.65
    for endpoint, color, label in (
        ((axis_extent, 0.0, 0.0), (230, 80, 80, 255), "X"),
        ((0.0, axis_extent, 0.0), (80, 220, 100, 255), "Y"),
        ((0.0, 0.0, axis_extent), (90, 140, 255, 255), "Z"),
    ):
        _draw_3d_line(project, (0.0, 0.0, 0.0), endpoint, color, viewport, thickness=2.0)
        projected = project(endpoint)
        if projected is not None:
            dpg.draw_text(projected[:2], label, color=color, size=16, parent=viewport)

    projected_points = []
    for point, detection in zip(points, _detection_view.get("detections", [])):
        projected = project(point)
        if projected is not None:
            projected_points.append((projected[2], projected, detection))
    for _, projected, detection in sorted(
        projected_points,
        key=lambda item: item[0],
        reverse=True,
    ):
        color = _doppler_color(detection["doppler_velocity_meters_per_second"])
        dpg.draw_circle(projected[:2], 3.5, fill=color, color=color, parent=viewport)

    origin = project((0.0, 0.0, 0.0))
    if origin is not None:
        dpg.draw_circle(origin[:2], 6.0, fill=(255, 255, 255, 255), parent=viewport)
    dpg.draw_text(
        (12.0, 10.0),
        f"{len(projected_points)} / {len(points)} detections visible",
        color=(210, 210, 215, 255),
        size=15,
        parent=viewport,
    )


def _make_projector(width: float, height: float, extent: float):
    yaw = math.radians(_camera.yaw_degrees)
    pitch = math.radians(_camera.pitch_degrees)
    camera = (
        _camera.x * extent,
        _camera.y * extent,
        _camera.z * extent,
    )
    forward = (
        math.cos(pitch) * math.sin(yaw),
        math.cos(pitch) * math.cos(yaw),
        math.sin(pitch),
    )
    right = _normalize(_cross(forward, (0.0, 0.0, 1.0)))
    up = _cross(right, forward)
    focal = min(width, height) * 0.5 / math.tan(math.radians(30.0))

    def project(point):
        relative = tuple(point[index] - camera[index] for index in range(3))
        depth = _dot(relative, forward)
        if depth <= 0.1:
            return None
        return (
            width * 0.5 + focal * _dot(relative, right) / depth,
            height * 0.5 - focal * _dot(relative, up) / depth,
            depth,
        )

    return project


def _doppler_color(velocity_meters_per_second: float) -> tuple:
    if velocity_meters_per_second > 0.1:
        return _DOPPLER_RED
    if velocity_meters_per_second < -0.1:
        return _DOPPLER_BLUE
    return _DOPPLER_NEUTRAL


def _draw_3d_line(project, start, end, color, parent, thickness: float = 1.0) -> None:
    projected_start = project(start)
    projected_end = project(end)
    if projected_start is not None and projected_end is not None:
        dpg.draw_line(
            projected_start[:2],
            projected_end[:2],
            color=color,
            thickness=thickness,
            parent=parent,
        )


def _dot(left, right) -> float:
    return sum(a * b for a, b in zip(left, right))


def _cross(left, right):
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _normalize(vector):
    length = math.sqrt(_dot(vector, vector))
    return tuple(value / length for value in vector)


def _on_error(stream: str) -> None:
    _stop_stream(stream)
    _set_status(stream, "RX error", (255, 80, 80, 255))
    log.append(f"[RadarSensor:{_stream_title(stream)}] receive error", "ERROR")


def _set_controls_enabled(stream: str, enabled: bool) -> None:
    for suffix in ("ip", "port"):
        tag = _tag(stream, suffix)
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=enabled)


def _set_status(stream: str, text: str, color: tuple) -> None:
    tag = _tag(stream, "status")
    if dpg.does_item_exist(tag):
        dpg.set_value(tag, text)
        dpg.configure_item(tag, color=color)


def _save_state() -> None:
    data = {"streams": {}}
    for stream in _STREAM_ORDER:
        ip_tag = _tag(stream, "ip")
        port_tag = _tag(stream, "port")
        if not dpg.does_item_exist(ip_tag) or not dpg.does_item_exist(port_tag):
            return
        data["streams"][stream] = {
            "ip": str(dpg.get_value(ip_tag)).strip() or "0.0.0.0",
            "port": int(dpg.get_value(port_tag)),
        }

    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2)
    except Exception as exc:
        print(f"[RadarSensor] save state error: {exc}")


def _load_state() -> None:
    if not os.path.isfile(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fp:
            streams = json.load(fp).get("streams", {})
        for stream in _STREAM_ORDER:
            values = streams.get(stream, {})
            dpg.set_value(_tag(stream, "ip"), str(values.get("ip", "0.0.0.0")))
            dpg.set_value(
                _tag(stream, "port"),
                int(values.get("port", _DEFAULT_PORTS[stream])),
            )
    except Exception as exc:
        print(f"[RadarSensor] load state error: {exc}")


def _section(title: str) -> None:
    dpg.add_spacer(height=6)
    dpg.add_text(title, color=(200, 200, 100, 255))
    dpg.add_separator()
    dpg.add_spacer(height=2)


def _stream_title(stream: str) -> str:
    return "Object List" if stream == _OBJECTS else "Detection List"


def _tag(stream: str, suffix: str) -> str:
    return f"radar_sensor_{stream}_{suffix}"
