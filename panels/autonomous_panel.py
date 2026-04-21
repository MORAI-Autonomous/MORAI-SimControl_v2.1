from __future__ import annotations

import threading
from typing import Callable, Optional

import dearpygui.dearpygui as dpg
import utils.ui_queue as ui_queue
import panels.log as log

_MAX_VEHICLES = 6

_start_ad_fn:      Optional[Callable] = None
_stop_ad_fn:       Optional[Callable] = None
_start_step_ad_fn: Optional[Callable] = None
_stop_step_ad_fn:  Optional[Callable] = None
_running_step_mode = False
_entity_slot: dict = {}   # entity_id → slot index (1-based)


def init(
    start_ad_fn:      Callable,
    stop_ad_fn:       Callable,
    start_step_ad_fn: Callable,
    stop_step_ad_fn:  Callable,
) -> None:
    global _start_ad_fn, _stop_ad_fn, _start_step_ad_fn, _stop_step_ad_fn
    _start_ad_fn      = start_ad_fn
    _stop_ad_fn       = stop_ad_fn
    _start_step_ad_fn = start_step_ad_fn
    _stop_step_ad_fn  = stop_step_ad_fn


def build(parent) -> None:
    with dpg.group(parent=parent):

        # ── CONTROL ──────────────────────────────────────────
        _section("CONTROL")

        dpg.add_text(
            "* 기본 경로(path_link.csv)는 상암맵 기준으로 설정되어 있습니다.",
            color=(220, 160, 60, 255),
        )
        dpg.add_spacer(height=6)

        with dpg.group(horizontal=True):
            dpg.add_checkbox(tag="au_fixed_step", label="Fixed Step",
                             default_value=False,
                             callback=_on_fixed_step_toggle)
            dpg.add_spacer(width=16)
            dpg.add_checkbox(tag="au_save_data", label="Save Data",
                             default_value=False, show=False)

        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            dpg.add_button(label="▶ Start", tag="au_btn_start", callback=_on_start)
            dpg.add_button(label="■ Stop",  tag="au_btn_stop",  callback=_on_stop)
            dpg.add_text(" ", tag="au_status", color=(160, 160, 160, 255))

        # ── VEHICLES ─────────────────────────────────────────
        _section("VEHICLES")

        with dpg.group(horizontal=True):
            dpg.add_text("차량 수 :", color=(180, 180, 180, 255))
            dpg.add_input_int(
                tag="au_vehicle_count",
                default_value=2,
                min_value=1, max_value=_MAX_VEHICLES,
                step=1, width=70,
                callback=_on_vehicle_count_change,
            )

        dpg.add_spacer(height=6)
        dpg.add_group(tag="au_vehicles_area")
        _build_vehicles(2)


# ── 동적 차량 목록 빌드 ───────────────────────────────────────

def _build_vehicles(count: int) -> None:
    """au_vehicles_area 내 차량 설정 위젯을 (재)생성한다."""
    dpg.delete_item("au_vehicles_area", children_only=True)
    for i in range(1, count + 1):
        with dpg.group(tag=f"au_vehicle_group_{i}", parent="au_vehicles_area"):
            dpg.add_text(f"[ Vehicle {i} ]", color=(160, 200, 255, 255))

            # Path
            with dpg.group(horizontal=True):
                dpg.add_text("Path  :", color=(180, 180, 180, 255))
                _folder_btn(callback=lambda v=i: _browse_path(v))
                dpg.add_input_text(tag=f"au_path_{i}", width=-1,
                                   hint="CSV", default_value="path_link.csv")

            # ID / Port
            with dpg.group(horizontal=True):
                dpg.add_text("ID    :", color=(180, 180, 180, 255))
                dpg.add_input_text(tag=f"au_entity_id_{i}",
                                   default_value=f"Car_{i}", width=100)
                dpg.add_spacer(width=10)
                dpg.add_text("Port  :", color=(180, 180, 180, 255))
                dpg.add_input_int(tag=f"au_vi_port_{i}",
                                  default_value=9090 + i,
                                  min_value=1, max_value=65535, step=0, width=80)

            # Vehicle Status
            with dpg.group(horizontal=True):
                for key, label in [
                    ("pos",   "Pos"),
                    ("vel",   "Vel"),
                    ("accel", "Accel"),
                    ("brake", "Brake"),
                    ("steer", "Steer"),
                ]:
                    dpg.add_text(f"{label}:", color=(140, 140, 140, 255))
                    dpg.add_text("-", tag=f"au_sv{i}_{key}",
                                 color=(200, 200, 200, 255))
                    dpg.add_spacer(width=4)

            if i < count:
                dpg.add_spacer(height=4)
                dpg.add_separator()
                dpg.add_spacer(height=4)


def _on_vehicle_count_change(sender, app_data) -> None:
    _build_vehicles(app_data)


# ── Public callbacks ──────────────────────────────────────────

def update_status(
    entity_id: str,
    x: float, y: float,
    vel_kmh: float,
    accel: float,
    brake: float,
    steer: float,
) -> None:
    slot = _entity_slot.get(entity_id)
    if slot is None:
        return
    def _apply(s=slot, _x=x, _y=y, v=vel_kmh, a=accel, b=brake, st=steer):
        pfx = f"au_sv{s}_"
        if not dpg.does_item_exist(pfx + "pos"):
            return
        dpg.set_value(pfx + "pos",   f"({_x:.1f}, {_y:.1f})")
        dpg.set_value(pfx + "vel",   f"{v:.1f} km/h")
        dpg.set_value(pfx + "accel", f"{a:.3f}")
        dpg.set_value(pfx + "brake", f"{b:.3f}")
        dpg.set_value(pfx + "steer", f"{st:.3f}")
    ui_queue.post(_apply)


def reset_ui() -> None:
    def _apply():
        if not dpg.does_item_exist("au_btn_start"):
            return
        dpg.configure_item("au_btn_start", enabled=True)
        dpg.set_value("au_status", "● Stopped")
        dpg.configure_item("au_status", color=(180, 80, 80, 255))
        count = dpg.get_value("au_vehicle_count") if dpg.does_item_exist("au_vehicle_count") else 0
        for i in range(1, count + 1):
            for key in ("pos", "vel", "accel", "brake", "steer"):
                tag = f"au_sv{i}_{key}"
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, "-")
    ui_queue.post(_apply)


# ── Internal ──────────────────────────────────────────────────

def _on_fixed_step_toggle(sender, app_data) -> None:
    dpg.configure_item("au_save_data", show=app_data)
    if app_data:
        dpg.set_value("au_save_data", True)


def _browse_path(vehicle: int) -> None:
    tag = f"au_path_{vehicle}"
    def _open():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title=f"Select Path CSV File (Vehicle {vehicle})",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        root.destroy()
        if path:
            ui_queue.post(lambda p=path, t=tag: dpg.set_value(t, p))
    threading.Thread(target=_open, daemon=True).start()


def _on_start() -> None:
    global _running_step_mode, _entity_slot
    count = dpg.get_value("au_vehicle_count")
    vehicles = []
    for i in range(1, count + 1):
        eid = dpg.get_value(f"au_entity_id_{i}").strip()
        if not eid:
            continue
        vehicles.append({
            "path":      dpg.get_value(f"au_path_{i}").strip() or "path_link.csv",
            "entity_id": eid,
            "vi_port":   dpg.get_value(f"au_vi_port_{i}"),
        })

    if not vehicles:
        log.append("[AD] entity_id가 없습니다. 차량 ID를 입력해 주세요.", level="WARN")
        return

    _entity_slot = {v["entity_id"]: i for i, v in enumerate(vehicles, 1)}
    _running_step_mode = dpg.get_value("au_fixed_step")
    dpg.configure_item("au_btn_start", enabled=False)
    dpg.set_value("au_status", "● Running")
    dpg.configure_item("au_status", color=(100, 220, 100, 255))

    if _running_step_mode:
        if _start_step_ad_fn is None:
            log.append("[AD] 초기화되지 않았습니다.", level="ERROR")
            return
        _start_step_ad_fn(vehicles, dpg.get_value("au_save_data"))
    else:
        if _start_ad_fn is None:
            log.append("[AD] 초기화되지 않았습니다.", level="ERROR")
            return
        _start_ad_fn(vehicles)


def _on_stop() -> None:
    if _running_step_mode:
        if _stop_step_ad_fn:
            _stop_step_ad_fn()
    else:
        if _stop_ad_fn:
            _stop_ad_fn()


def _folder_btn(callback) -> None:
    if dpg.does_alias_exist("folder_icon"):
        dpg.add_image_button("folder_icon", width=22, height=22, callback=callback)
    else:
        dpg.add_button(label="...", callback=callback)


def _section(label: str) -> None:
    dpg.add_spacer(height=6)
    dpg.add_text(label, color=(200, 200, 100, 255))
    dpg.add_separator()
    dpg.add_spacer(height=2)
