from __future__ import annotations

import csv
import json
import os
import threading
from typing import Callable, Optional

import dearpygui.dearpygui as dpg
import utils.ui_queue as ui_queue
import panels.log as log

_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "fp_state.json"
)

_start_fn: Optional[Callable] = None
_stop_fn:  Optional[Callable] = None


def init(start_fp_fn: Callable, stop_fp_fn: Callable) -> None:
    global _start_fn, _stop_fn
    _start_fn = start_fp_fn
    _stop_fn  = stop_fp_fn


def build(parent) -> None:
    with dpg.group(parent=parent):
        _section("FILE PLAYBACK (Fixed Step Mode)")

        with dpg.group(horizontal=True):
            dpg.add_text("Browse    :", color=(180, 180, 180, 255))
            _folder_btn(callback=_browse_file)

        with dpg.group(horizontal=True):
            dpg.add_text("Path      :", color=(180, 180, 180, 255))
            dpg.add_input_text(tag="fp_path", width=-1, hint="CSV file path")

        with dpg.group(horizontal=True):
            dpg.add_text("ID        :", color=(180, 180, 180, 255))
            dpg.add_input_text(tag="fp_entity_id", default_value="Car_1", width=80)

        with dpg.group(horizontal=True):
            dpg.add_text("Control   :", color=(180, 180, 180, 255))
            dpg.add_button(label="▶ Play", tag="fp_btn_play", callback=_on_play)
            dpg.add_button(label="■ Stop", tag="fp_btn_stop", callback=_on_stop)
            dpg.add_text(" ", tag="fp_status", color=(160, 160, 160, 255))

        dpg.add_progress_bar(tag="fp_progress_bar",
                             default_value=0.0, width=-1, overlay="")

        _load_state()


def update_progress(current: int, total: int) -> None:
    def _apply(c=current, t=total):
        if not dpg.does_item_exist("fp_progress_bar"):
            return
        ratio = c / t if t > 0 else 0.0
        dpg.set_value("fp_progress_bar", ratio)
        dpg.configure_item("fp_progress_bar", overlay=f"{c}/{t}")
        dpg.set_value("fp_status", f"{c} / {t}")
    ui_queue.post(_apply)


def reset_ui(stopped: bool = False) -> None:
    def _apply(s=stopped):
        if not dpg.does_item_exist("fp_btn_play"):
            return
        dpg.configure_item("fp_btn_play", enabled=True)
        dpg.set_value("fp_progress_bar", 0.0)
        dpg.configure_item("fp_progress_bar", overlay="")
        dpg.set_value("fp_status", "Stopped" if s else "Done")
        log.append(f"[FilePlay] {'중단됨' if s else '재생 완료'}")
    ui_queue.post(_apply)


def _browse_file() -> None:
    def _open():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select CMD CSV File",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        root.destroy()
        if path:
            ui_queue.post(lambda p=path: (
                dpg.set_value("fp_path", p),
                _save_state(),
            ))
    threading.Thread(target=_open, daemon=True).start()


def _load_csv(path: str) -> list:
    rows = []
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    'time':     float(row['Time [sec]']),
                    'throttle': float(row['Acc [0~1]']),
                    'brake':    float(row['Brk [0~1]']),
                    'swa':      float(row['SWA [deg]']),
                })
    except Exception as e:
        log.append(f"[FilePlay] CSV 파싱 오류: {e}", level="ERROR")
        return []
    log.append(f"[FilePlay] {len(rows)}행 로드 완료: {path}")
    return rows


def _on_play() -> None:
    if _start_fn is None:
        log.append("[FilePlay] 초기화되지 않았습니다.", level="ERROR")
        return
    path = dpg.get_value("fp_path").strip()
    if not path:
        log.append("[FilePlay] CSV 파일 경로가 없습니다.", level="WARN")
        return
    rows = _load_csv(path)
    if not rows:
        return
    entity_id = dpg.get_value("fp_entity_id").strip() or "Car_1"
    _save_state()
    dpg.configure_item("fp_btn_play", enabled=False)
    dpg.set_value("fp_status", f"0 / {len(rows)}")
    _start_fn(rows, entity_id)


def _on_stop() -> None:
    if _stop_fn:
        _stop_fn()


def _save_state() -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        data = {
            "fp_path":      dpg.get_value("fp_path"),
            "fp_entity_id": dpg.get_value("fp_entity_id"),
        }
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[FilePlay] save state error: {e}")


def _load_state() -> None:
    if not os.path.isfile(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("fp_path") and dpg.does_item_exist("fp_path"):
            dpg.set_value("fp_path", data["fp_path"])
        if data.get("fp_entity_id") and dpg.does_item_exist("fp_entity_id"):
            dpg.set_value("fp_entity_id", data["fp_entity_id"])
    except Exception as e:
        print(f"[FilePlay] load state error: {e}")


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
