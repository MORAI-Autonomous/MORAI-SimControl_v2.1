from __future__ import annotations

from typing import Callable, Optional
import json
import os
import threading
import time

import dearpygui.dearpygui as dpg

import panels.log as log
import transport.object_enums as object_enums
import transport.protocol_defs as proto
import transport.tcp_transport as tcp
from utils import trajectory_samples
from utils import bulk_vehicle_spawn
import utils.ui_queue as ui_queue
from utils.project_paths import ROOT_DIR, SRC_DIR

_STATE_FILE = os.path.join(str(ROOT_DIR), "config", "object_control_state.json")
_LEGACY_COMMANDS_STATE_FILE = os.path.join(str(ROOT_DIR), "config", "commands_state.json")
_MAP_DIR = SRC_DIR / "autonomous_driving" / "config" / "map"
_DEFAULT_BULK_MAP = "Sangam_Track"
_BULK_VEHICLE_SPACING_M = 8.0
_BULK_LANE_OFFSET_M = 4.0
_BULK_SEND_INTERVAL_SEC = 0.05
_MAX_BULK_VEHICLES = 1000

_tcp_sock = None
_dispatch: Optional[Callable] = None
_bulk_create_running = False
_bulk_delete_running = False
_bulk_request_lock = threading.Lock()
_bulk_create_pending = set()
_bulk_delete_pending = {}
_bulk_created_ids = set()


def init(tcp_sock, dispatch_fn: Callable) -> None:
    global _tcp_sock, _dispatch
    _tcp_sock = tcp_sock
    _dispatch = dispatch_fn


def _get_bulk_maps() -> list:
    try:
        return sorted(
            path.name for path in _MAP_DIR.iterdir()
            if path.is_dir() and (path / "path_link.csv").is_file()
        )
    except OSError:
        return []


def build() -> None:
    _section("OBJECT CONTROL")

    with dpg.group(horizontal=True):
        dpg.add_text("ID        :", color=(180, 180, 180, 255))
        dpg.add_input_text(tag="obj_entity_id", default_value="Car_1", width=140)
        dpg.add_button(label="Delete", callback=_on_delete_object)
        dpg.add_text("0x1305", color=(140, 140, 140, 255))

    _subsection("Create Object")
    with dpg.group():
        dpg.add_spacer(height=2)
        with dpg.group(horizontal=True):
            dpg.add_text("Type", color=(160, 160, 160, 255))
            dpg.add_combo(
                tag="co_entity_type",
                items=object_enums.enum_labels(object_enums.ENTITY_TYPE_ITEMS),
                default_value=object_enums.enum_label_for_value(
                    object_enums.ENTITY_TYPE_ITEMS, 1, 1),
                width=210,
            )
            dpg.add_spacer(width=8)
            dpg.add_text("Mode", color=(160, 160, 160, 255))
            dpg.add_combo(
                tag="co_driving_mode",
                items=object_enums.enum_labels(object_enums.VEHICLE_DRIVING_MODE_ITEMS),
                default_value=object_enums.enum_label_for_value(
                    object_enums.VEHICLE_DRIVING_MODE_ITEMS, 2, 2),
                width=250,
            )
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=8)
            dpg.add_text("Model", color=(160, 160, 160, 255))
            dpg.add_combo(
                tag="co_ground_vehicle_model",
                items=object_enums.enum_labels(object_enums.GROUND_VEHICLE_MODEL_ITEMS),
                default_value=object_enums.enum_label_for_value(
                    object_enums.GROUND_VEHICLE_MODEL_ITEMS, 12, 12),
                width=300,
            )
        with dpg.group(horizontal=True):
            for tag, label, default in [
                ("co_pos_x", "px", 267.5667),
                ("co_pos_y", "py", -299.4991),
                ("co_pos_z", "pz", 0.0522),
            ]:
                dpg.add_text(label, color=(160, 160, 160, 255))
                dpg.add_input_float(tag=tag, default_value=default, step=0, width=82, format="%.4f")
        with dpg.group(horizontal=True):
            for tag, label, default in [
                ("co_rot_x", "rx", -0.18),
                ("co_rot_y", "ry", -179.982),
                ("co_rot_z", "rz", -0.51),
            ]:
                dpg.add_text(label, color=(160, 160, 160, 255))
                dpg.add_input_float(tag=tag, default_value=default, step=0, width=82, format="%.4f")
        dpg.add_spacer(height=2)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Create", callback=_on_create_object)
            dpg.add_text("0x1301", color=(140, 140, 140, 255))

        dpg.add_spacer(height=6)
        bulk_maps = _get_bulk_maps()
        default_bulk_map = (
            _DEFAULT_BULK_MAP if _DEFAULT_BULK_MAP in bulk_maps
            else (bulk_maps[0] if bulk_maps else "")
        )
        with dpg.group(horizontal=True):
            dpg.add_text("Bulk map", color=(160, 160, 160, 255))
            dpg.add_combo(
                tag="co_bulk_map",
                items=bulk_maps,
                default_value=default_bulk_map,
                width=220,
            )
        with dpg.group(horizontal=True):
            dpg.add_text("Bulk count", color=(160, 160, 160, 255))
            dpg.add_input_int(
                tag="co_bulk_count",
                default_value=100,
                min_value=1,
                max_value=_MAX_BULK_VEHICLES,
                min_clamped=True,
                max_clamped=True,
                step=1,
                width=90,
            )
            dpg.add_button(
                label="Create Vehicles",
                tag="co_bulk_create_btn",
                callback=_on_bulk_create_objects,
            )
            dpg.add_button(
                label="Delete Created",
                tag="co_bulk_delete_btn",
                callback=_on_bulk_delete_objects,
            )
        dpg.add_text(
            "Selected map path_link.csv / IONIQ5 / Kinematics / 8 m spacing",
            color=(130, 130, 130, 255),
        )

    _subsection("Manual Control")
    with dpg.group():
        dpg.add_spacer(height=2)
        with dpg.group(horizontal=True):
            for tag, label, default in [
                ("mc_thr", "Throttle", 0.4),
                ("mc_brk", "Brake", 0.0),
                ("mc_steer", "Steer Angle", 0.0),
            ]:
                dpg.add_text(label, color=(160, 160, 160, 255))
                dpg.add_input_float(
                    tag=tag,
                    default_value=default,
                    min_value=-1.0,
                    max_value=1.0,
                    step=0,
                    width=60,
                    format="%.2f",
                )
        dpg.add_spacer(height=2)
        dpg.add_button(label="Send", callback=_on_manual_control)

    _subsection("Transform Control")
    with dpg.group():
        dpg.add_spacer(height=2)
        with dpg.group(horizontal=True):
            for tag, label in [("tc_px", "px"), ("tc_py", "py"), ("tc_pz", "pz")]:
                dpg.add_text(label, color=(160, 160, 160, 255))
                dpg.add_input_float(tag=tag, default_value=0.0, step=0, width=80)
        with dpg.group(horizontal=True):
            for tag, label in [("tc_rx", "rx"), ("tc_ry", "ry"), ("tc_rz", "rz")]:
                dpg.add_text(label, color=(160, 160, 160, 255))
                dpg.add_input_float(tag=tag, default_value=0.0, step=0, width=80)
        with dpg.group(horizontal=True):
            dpg.add_text("steer", color=(160, 160, 160, 255))
            dpg.add_input_float(tag="tc_steer", default_value=0.0, step=0, width=80)
            dpg.add_text("speed", color=(160, 160, 160, 255))
            dpg.add_input_float(tag="tc_speed", default_value=0.0, step=0, width=80)
        dpg.add_spacer(height=2)
        dpg.add_button(label="Send", callback=_on_transform_control)

    _subsection("Set Trajectory")
    with dpg.group():
        dpg.add_spacer(height=2)
        with dpg.group(horizontal=True):
            dpg.add_text("Mode", color=(160, 160, 160, 255))
            dpg.add_combo(
                tag="tr_follow_mode",
                items=object_enums.enum_labels(trajectory_samples.TRAJECTORY_FOLLOW_MODE_ITEMS),
                default_value=object_enums.enum_label_for_value(
                    trajectory_samples.TRAJECTORY_FOLLOW_MODE_ITEMS, 2, 2),
                width=130,
            )
            dpg.add_spacer(width=8)
            dpg.add_text("Name", color=(160, 160, 160, 255))
            dpg.add_input_text(tag="tr_name", default_value="Route_1", width=140)
        with dpg.group(horizontal=True):
            dpg.add_text("Sample", color=(160, 160, 160, 255))
            dpg.add_combo(
                tag="tr_sample",
                items=trajectory_samples.sample_names(),
                default_value=trajectory_samples.TRAJECTORY_SAMPLES[0][0],
                width=210,
            )
            dpg.add_button(label="Load", callback=_load_trajectory_sample)
        for idx, point in enumerate(trajectory_samples.TRAJECTORY_SAMPLES[0][1], start=1):
            with dpg.group(horizontal=True):
                dpg.add_text(f"P{idx}", color=(160, 160, 160, 255))
                for axis, value in zip(("x", "y", "z", "t"), point):
                    dpg.add_text(axis, color=(160, 160, 160, 255))
                    dpg.add_input_float(
                        tag=f"tr_p{idx}_{axis}",
                        default_value=value,
                        step=0,
                        width=82,
                        format="%.4f",
                    )
        dpg.add_spacer(height=2)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Send", callback=_on_set_trajectory)
            dpg.add_text("0x1304", color=(140, 140, 140, 255))

    _load_state()


def _on_create_object() -> None:
    _save_state()
    params = {
        "entity_type": object_enums.enum_value_from_label(
            object_enums.ENTITY_TYPE_ITEMS, dpg.get_value("co_entity_type"), 1),
        "pos_x": float(dpg.get_value("co_pos_x")),
        "pos_y": float(dpg.get_value("co_pos_y")),
        "pos_z": float(dpg.get_value("co_pos_z")),
        "rot_x": float(dpg.get_value("co_rot_x")),
        "rot_y": float(dpg.get_value("co_rot_y")),
        "rot_z": float(dpg.get_value("co_rot_z")),
        "driving_mode": object_enums.enum_value_from_label(
            object_enums.VEHICLE_DRIVING_MODE_ITEMS, dpg.get_value("co_driving_mode"), 2),
        "ground_vehicle_model": object_enums.enum_value_from_label(
            object_enums.GROUND_VEHICLE_MODEL_ITEMS,
            dpg.get_value("co_ground_vehicle_model"),
            12,
        ),
    }
    _dispatch(
        proto.MSG_TYPE_CREATE_OBJECT,
        lambda rid, kwargs=params: tcp.send_create_object(_tcp_sock, rid, **kwargs),
    )
    log.append(
        "[Object] CreateObject requested "
        f"type={params['entity_type']} model={params['ground_vehicle_model']} "
        f"pos=({params['pos_x']:.3f}, {params['pos_y']:.3f}, {params['pos_z']:.3f})",
        "INFO",
    )


def _on_bulk_create_objects() -> None:
    global _bulk_create_running
    if _bulk_create_running:
        log.append("[Object] Bulk Create is already running", "WARN")
        return
    if _dispatch is None or _tcp_sock is None:
        log.append("[Object] Bulk Create skipped: TCP is not connected", "WARN")
        return

    count = int(dpg.get_value("co_bulk_count"))
    map_name = str(dpg.get_value("co_bulk_map")).strip()
    if count < 1 or count > _MAX_BULK_VEHICLES:
        log.append(
            f"[Object] Bulk Create count must be 1..{_MAX_BULK_VEHICLES}",
            "WARN",
        )
        return

    _save_state()
    try:
        path_file = _MAP_DIR / map_name / "path_link.csv"
        if map_name not in _get_bulk_maps():
            raise ValueError(f"unknown bulk map: {map_name!r}")
        points = bulk_vehicle_spawn.load_csv_path(path_file)
        poses = bulk_vehicle_spawn.build_spawn_poses(
            points,
            count,
            spacing=_BULK_VEHICLE_SPACING_M,
            lane_offset=_BULK_LANE_OFFSET_M,
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        log.append(f"[Object] Bulk Create path error: {exc}", "ERROR")
        return

    _bulk_create_running = True
    dpg.configure_item("co_bulk_create_btn", enabled=False)
    log.append(
        f"[Object] Bulk Create started count={count} map={map_name} path={path_file.name}",
        "INFO",
    )
    threading.Thread(
        target=_run_bulk_create,
        args=(poses,),
        daemon=True,
        name="BulkVehicleCreate",
    ).start()


def _run_bulk_create(poses: list) -> None:
    global _bulk_create_running
    try:
        for index, (pos_x, pos_y, pos_z, yaw) in enumerate(poses, start=1):
            params = {
                "entity_type": 1,
                "pos_x": pos_x,
                "pos_y": pos_y,
                "pos_z": pos_z,
                "rot_x": 0.0,
                "rot_y": 0.0,
                "rot_z": yaw,
                "driving_mode": 2,
                "ground_vehicle_model": 1,
            }
            _dispatch(
                proto.MSG_TYPE_CREATE_OBJECT,
                lambda rid, kwargs=params: tcp.send_create_object(_tcp_sock, rid, **kwargs),
                on_registered=_register_bulk_create_request,
            )
            if index < len(poses):
                time.sleep(_BULK_SEND_INTERVAL_SEC)
        log.append(f"[Object] Bulk Create dispatched count={len(poses)}", "INFO")
    except Exception as exc:
        log.append(f"[Object] Bulk Create stopped: {exc}", "ERROR")
    finally:
        _bulk_create_running = False
        ui_queue.post(lambda: dpg.configure_item("co_bulk_create_btn", enabled=True))


def _register_bulk_create_request(request_id: int) -> None:
    with _bulk_request_lock:
        _bulk_create_pending.add(request_id)


def on_create_object_response(request_id: int, parsed: dict) -> None:
    with _bulk_request_lock:
        if request_id not in _bulk_create_pending:
            return
        _bulk_create_pending.remove(request_id)
        if parsed.get("result_code") == 0 and parsed.get("object_id"):
            _bulk_created_ids.add(str(parsed["object_id"]))


def _on_bulk_delete_objects() -> None:
    global _bulk_delete_running
    if _bulk_create_running:
        log.append("[Object] Delete Created skipped: Bulk Create is still dispatching", "WARN")
        return
    with _bulk_request_lock:
        create_pending_count = len(_bulk_create_pending)
        delete_pending_count = len(_bulk_delete_pending)
        entity_ids = sorted(_bulk_created_ids)
    if create_pending_count:
        log.append(
            f"[Object] Delete Created skipped: waiting for {create_pending_count} create response(s)",
            "WARN",
        )
        return
    if _bulk_delete_running or delete_pending_count:
        log.append("[Object] Delete Created is already running", "WARN")
        return
    if not entity_ids:
        log.append("[Object] Delete Created skipped: no tracked vehicle IDs", "WARN")
        return

    _bulk_delete_running = True
    dpg.configure_item("co_bulk_delete_btn", enabled=False)
    log.append(f"[Object] Delete Created started count={len(entity_ids)}", "INFO")
    threading.Thread(
        target=_run_bulk_delete,
        args=(entity_ids,),
        daemon=True,
        name="BulkVehicleDelete",
    ).start()


def _run_bulk_delete(entity_ids: list) -> None:
    global _bulk_delete_running
    try:
        for index, entity_id in enumerate(entity_ids, start=1):
            _dispatch(
                proto.MSG_TYPE_DELETE_OBJECT,
                lambda rid, eid=entity_id: tcp.send_delete_object(_tcp_sock, rid, eid),
                on_registered=lambda rid, eid=entity_id: _register_bulk_delete_request(rid, eid),
            )
            if index < len(entity_ids):
                time.sleep(_BULK_SEND_INTERVAL_SEC)
        log.append(f"[Object] Delete Created dispatched count={len(entity_ids)}", "INFO")
    except Exception as exc:
        log.append(f"[Object] Delete Created stopped: {exc}", "ERROR")
    finally:
        _bulk_delete_running = False
        ui_queue.post(lambda: dpg.configure_item("co_bulk_delete_btn", enabled=True))


def _register_bulk_delete_request(request_id: int, entity_id: str) -> None:
    with _bulk_request_lock:
        _bulk_delete_pending[request_id] = entity_id


def on_delete_object_response(
    request_id: int,
    result_code: Optional[int],
    detail_code: Optional[int],
) -> None:
    with _bulk_request_lock:
        entity_id = _bulk_delete_pending.pop(request_id, None)
        if entity_id is None:
            return
        if result_code == 0:
            _bulk_created_ids.discard(entity_id)
            remaining = len(_bulk_created_ids)
        else:
            remaining = len(_bulk_created_ids)
    if result_code != 0:
        log.append(
            f"[Object] Delete Created failed id={entity_id} "
            f"result={result_code} detail={detail_code}",
            "WARN",
        )
    elif remaining == 0:
        log.append("[Object] Delete Created completed", "INFO")


def _on_delete_object() -> None:
    entity_id = str(dpg.get_value("obj_entity_id")).strip()
    if not entity_id:
        log.append("[Object] DeleteObject skipped: empty entity id", "WARN")
        return
    _save_state()
    _dispatch(
        proto.MSG_TYPE_DELETE_OBJECT,
        lambda rid, eid=entity_id: tcp.send_delete_object(_tcp_sock, rid, eid),
    )
    log.append(f"[Object] DeleteObject requested id={entity_id}", "INFO")


def _on_manual_control() -> None:
    _save_state()
    _dispatch(
        proto.MSG_TYPE_MANUAL_CONTROL_BY_ID_COMMAND,
        lambda rid: tcp.send_manual_control_by_id(
            _tcp_sock,
            rid,
            entity_id=dpg.get_value("obj_entity_id"),
            throttle=dpg.get_value("mc_thr"),
            brake=dpg.get_value("mc_brk"),
            steer_angle=dpg.get_value("mc_steer"),
        ),
    )


def _on_transform_control() -> None:
    _save_state()
    _dispatch(
        proto.MSG_TYPE_TRANSFORM_CONTROL_BY_ID_COMMAND,
        lambda rid: tcp.send_transform_control_by_id(
            _tcp_sock,
            rid,
            entity_id=dpg.get_value("obj_entity_id"),
            pos_x=dpg.get_value("tc_px"),
            pos_y=dpg.get_value("tc_py"),
            pos_z=dpg.get_value("tc_pz"),
            rot_x=dpg.get_value("tc_rx"),
            rot_y=dpg.get_value("tc_ry"),
            rot_z=dpg.get_value("tc_rz"),
            steer_angle=dpg.get_value("tc_steer"),
            speed=dpg.get_value("tc_speed"),
        ),
    )


def _load_trajectory_sample() -> None:
    sample_name = dpg.get_value("tr_sample")
    points = trajectory_samples.get_sample(sample_name)
    for idx, point in enumerate(points, start=1):
        for axis, value in zip(("x", "y", "z", "t"), point):
            tag = f"tr_p{idx}_{axis}"
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, value)


def _on_set_trajectory() -> None:
    entity_id = str(dpg.get_value("obj_entity_id")).strip()
    trajectory_name = str(dpg.get_value("tr_name")).strip()
    if not entity_id:
        log.append("[Object] SetTrajectory skipped: empty entity id", "WARN")
        return
    if not trajectory_name:
        log.append("[Object] SetTrajectory skipped: empty trajectory name", "WARN")
        return

    _save_state()
    follow_mode = object_enums.enum_value_from_label(
        trajectory_samples.TRAJECTORY_FOLLOW_MODE_ITEMS,
        dpg.get_value("tr_follow_mode"),
        2,
    )
    points = []
    for idx in range(1, len(trajectory_samples.TRAJECTORY_SAMPLES[0][1]) + 1):
        points.append((
            float(dpg.get_value(f"tr_p{idx}_x")),
            float(dpg.get_value(f"tr_p{idx}_y")),
            float(dpg.get_value(f"tr_p{idx}_z")),
            float(dpg.get_value(f"tr_p{idx}_t")),
        ))

    _dispatch(
        proto.MSG_TYPE_SET_TRAJECTORY_COMMAND,
        lambda rid, eid=entity_id, mode=follow_mode, name=trajectory_name, pts=points:
            tcp.send_set_trajectory(_tcp_sock, rid, eid, mode, name, pts),
    )
    log.append(
        "[Object] SetTrajectory requested "
        f"id={entity_id} mode={follow_mode} name={trajectory_name!r} points={len(points)}",
        "INFO",
    )


def _save_state() -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        data = {
            "obj_entity_id": dpg.get_value("obj_entity_id"),
            "co_entity_type": dpg.get_value("co_entity_type"),
            "co_pos_x": dpg.get_value("co_pos_x"),
            "co_pos_y": dpg.get_value("co_pos_y"),
            "co_pos_z": dpg.get_value("co_pos_z"),
            "co_rot_x": dpg.get_value("co_rot_x"),
            "co_rot_y": dpg.get_value("co_rot_y"),
            "co_rot_z": dpg.get_value("co_rot_z"),
            "co_driving_mode": dpg.get_value("co_driving_mode"),
            "co_ground_vehicle_model": dpg.get_value("co_ground_vehicle_model"),
            "co_bulk_count": dpg.get_value("co_bulk_count"),
            "co_bulk_map": dpg.get_value("co_bulk_map"),
            "mc_thr": dpg.get_value("mc_thr"),
            "mc_brk": dpg.get_value("mc_brk"),
            "mc_steer": dpg.get_value("mc_steer"),
            "tc_px": dpg.get_value("tc_px"),
            "tc_py": dpg.get_value("tc_py"),
            "tc_pz": dpg.get_value("tc_pz"),
            "tc_rx": dpg.get_value("tc_rx"),
            "tc_ry": dpg.get_value("tc_ry"),
            "tc_rz": dpg.get_value("tc_rz"),
            "tc_steer": dpg.get_value("tc_steer"),
            "tc_speed": dpg.get_value("tc_speed"),
            "tr_follow_mode": dpg.get_value("tr_follow_mode"),
            "tr_name": dpg.get_value("tr_name"),
            "tr_sample": dpg.get_value("tr_sample"),
            "tr_p1_x": dpg.get_value("tr_p1_x"),
            "tr_p1_y": dpg.get_value("tr_p1_y"),
            "tr_p1_z": dpg.get_value("tr_p1_z"),
            "tr_p1_t": dpg.get_value("tr_p1_t"),
            "tr_p2_x": dpg.get_value("tr_p2_x"),
            "tr_p2_y": dpg.get_value("tr_p2_y"),
            "tr_p2_z": dpg.get_value("tr_p2_z"),
            "tr_p2_t": dpg.get_value("tr_p2_t"),
        }
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ObjectControl] save state error: {e}")


def _load_state() -> None:
    state_file = _STATE_FILE if os.path.isfile(_STATE_FILE) else _LEGACY_COMMANDS_STATE_FILE
    if not os.path.isfile(state_file):
        return
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for tag in [
            "obj_entity_id",
            "co_pos_x",
            "co_pos_y",
            "co_pos_z",
            "co_rot_x",
            "co_rot_y",
            "co_rot_z",
            "co_bulk_count",
            "co_bulk_map",
            "mc_thr",
            "mc_brk",
            "mc_steer",
            "tc_px",
            "tc_py",
            "tc_pz",
            "tc_rx",
            "tc_ry",
            "tc_rz",
            "tc_steer",
            "tc_speed",
            "tr_name",
            "tr_sample",
            "tr_p1_x",
            "tr_p1_y",
            "tr_p1_z",
            "tr_p1_t",
            "tr_p2_x",
            "tr_p2_y",
            "tr_p2_z",
            "tr_p2_t",
        ]:
            if tag in data and dpg.does_item_exist(tag):
                dpg.set_value(tag, data[tag])
        _load_enum_state(data, "co_entity_type", object_enums.ENTITY_TYPE_ITEMS, 1)
        _load_enum_state(data, "co_driving_mode", object_enums.VEHICLE_DRIVING_MODE_ITEMS, 2)
        _load_enum_state(data, "co_ground_vehicle_model", object_enums.GROUND_VEHICLE_MODEL_ITEMS, 12)
        _load_enum_state(data, "tr_follow_mode", trajectory_samples.TRAJECTORY_FOLLOW_MODE_ITEMS, 2)
    except Exception as e:
        print(f"[ObjectControl] load state error: {e}")


def _load_enum_state(
    data: dict,
    tag: str,
    items: object_enums.EnumItems,
    default: int,
) -> None:
    if tag not in data or not dpg.does_item_exist(tag):
        return
    value = object_enums.enum_value_from_label(items, data[tag], default)
    dpg.set_value(tag, object_enums.enum_label_for_value(items, value, default))


def _section(label: str) -> None:
    dpg.add_spacer(height=6)
    dpg.add_text(label, color=(200, 200, 100, 255))
    dpg.add_separator()
    dpg.add_spacer(height=2)


def _subsection(label: str) -> None:
    dpg.add_spacer(height=10)
    dpg.add_text(
        f"[ {label.upper()} ]",
        color=(105, 175, 235, 255),
    )
    dpg.add_separator()
    dpg.add_spacer(height=4)
