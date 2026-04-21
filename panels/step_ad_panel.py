from __future__ import annotations

import threading
from typing import Callable, Optional

import dearpygui.dearpygui as dpg
import utils.ui_queue as ui_queue
import panels.log as log

_start_fn: Optional[Callable] = None
_stop_fn:  Optional[Callable] = None


def init(start_step_ad_fn: Callable, stop_step_ad_fn: Callable) -> None:
    global _start_fn, _stop_fn
    _start_fn = start_step_ad_fn
    _stop_fn  = stop_step_ad_fn


def build(parent) -> None:
    with dpg.group(parent=parent):
        _section("AUTONOMOUS DRIVING (Fixed Step)")

        with dpg.table(header_row=True, borders_innerV=True,
                       policy=dpg.mvTable_SizingFixedFit):
            dpg.add_table_column(label="",          width_fixed=True, init_width_or_weight=68)
            dpg.add_table_column(label="Vehicle 1", width_stretch=True)
            dpg.add_table_column(label="Vehicle 2", width_stretch=True)

            with dpg.table_row():
                dpg.add_text("Path :", color=(180, 180, 180, 255))
                with dpg.group(horizontal=True):
                    _folder_btn(callback=lambda: _browse_path(1))
                    dpg.add_input_text(tag="sad_path_1", width=-1,
                                       hint="CSV", default_value="path_link.csv")
                with dpg.group(horizontal=True):
                    _folder_btn(callback=lambda: _browse_path(2))
                    dpg.add_input_text(tag="sad_path_2", width=-1,
                                       hint="CSV", default_value="path_link.csv")

            with dpg.table_row():
                dpg.add_text("ID :", color=(180, 180, 180, 255))
                dpg.add_input_text(tag="sad_entity_id_1", default_value="Car_1", width=-1)
                dpg.add_input_text(tag="sad_entity_id_2", default_value="Car_2", width=-1)

            with dpg.table_row():
                dpg.add_text("VI Port :", color=(180, 180, 180, 255))
                dpg.add_input_int(tag="sad_vi_port_1", default_value=9097,
                                  min_value=1, max_value=65535, step=0, width=-1)
                dpg.add_input_int(tag="sad_vi_port_2", default_value=9098,
                                  min_value=1, max_value=65535, step=0, width=-1)

        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            dpg.add_text("SaveData  :", color=(180, 180, 180, 255))
            dpg.add_checkbox(tag="sad_save_data", default_value=False)

        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            dpg.add_text("Control   :", color=(180, 180, 180, 255))
            dpg.add_button(label="▶ Start", tag="sad_btn_start", callback=_on_start)
            dpg.add_button(label="■ Stop",  tag="sad_btn_stop",  callback=_on_stop)
            dpg.add_text(" ", tag="sad_status", color=(160, 160, 160, 255))


def reset_ui() -> None:
    def _apply():
        if not dpg.does_item_exist("sad_btn_start"):
            return
        dpg.configure_item("sad_btn_start", enabled=True)
        dpg.set_value("sad_status", "● Stopped")
        dpg.configure_item("sad_status", color=(180, 80, 80, 255))
    ui_queue.post(_apply)


def _browse_path(vehicle: int) -> None:
    tag = f"sad_path_{vehicle}"
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
    if _start_fn is None:
        log.append("[StepAD] 초기화되지 않았습니다.", level="ERROR")
        return
    vehicles = [
        v for v in [
            {
                "path":      dpg.get_value("sad_path_1").strip() or "path_link.csv",
                "entity_id": dpg.get_value("sad_entity_id_1").strip(),
                "vi_port":   dpg.get_value("sad_vi_port_1"),
            },
            {
                "path":      dpg.get_value("sad_path_2").strip() or "path_link.csv",
                "entity_id": dpg.get_value("sad_entity_id_2").strip(),
                "vi_port":   dpg.get_value("sad_vi_port_2"),
            },
        ]
        if v["entity_id"]
    ]
    if not vehicles:
        log.append("[StepAD] entity_id가 없습니다. 차량 ID를 입력해 주세요.", level="WARN")
        return
    save_data = dpg.get_value("sad_save_data")
    dpg.configure_item("sad_btn_start", enabled=False)
    dpg.set_value("sad_status", "● Running")
    dpg.configure_item("sad_status", color=(100, 220, 100, 255))
    _start_fn(vehicles, save_data)


def _on_stop() -> None:
    if _stop_fn:
        _stop_fn()


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
