from __future__ import annotations

from typing import Callable, Optional
import json
import os
import threading

import dearpygui.dearpygui as dpg

import panels.log as log
import transport.protocol_defs as proto
import transport.tcp_transport as tcp
import utils.ui_queue as ui_queue
from utils.project_paths import ROOT_DIR

_STATE_FILE = os.path.join(str(ROOT_DIR), "config", "traffic_scenario_state.json")
_LEGACY_COMMANDS_STATE_FILE = os.path.join(str(ROOT_DIR), "config", "commands_state.json")

_tcp_sock = None
_dispatch: Optional[Callable] = None


def init(tcp_sock, dispatch_fn: Callable) -> None:
    global _tcp_sock, _dispatch
    _tcp_sock = tcp_sock
    _dispatch = dispatch_fn


def build() -> None:
    _section("TRAFFIC SCENARIO")

    with dpg.group(horizontal=True):
        dpg.add_text("Browse    :", color=(180, 180, 180, 255))
        _folder_btn(callback=_browse_traffic_scenario)

    with dpg.group(horizontal=True):
        dpg.add_text("Path      :", color=(180, 180, 180, 255))
        dpg.add_input_text(
            tag="traffic_scenario_path",
            width=-1,
            hint=".anmroutes file path",
        )

    with dpg.group(horizontal=True):
        dpg.add_text("Generate  :", color=(180, 180, 180, 255))
        dpg.add_text("Autonomous", color=(160, 160, 160, 255))
        dpg.add_input_int(tag="traffic_autonomous", default_value=1, step=0, width=70)
        dpg.add_text("LC Rate", color=(160, 160, 160, 255))
        dpg.add_input_int(tag="traffic_lc_rate", default_value=0, step=0, width=70)

    with dpg.group(horizontal=True):
        dpg.add_text("Action    :", color=(180, 180, 180, 255))
        dpg.add_button(label="Load", callback=_load_traffic_scenario)
        dpg.add_text("0x1601", color=(140, 140, 140, 255))
        dpg.add_spacer(width=8)
        dpg.add_button(label="Generate", callback=_traffic_generate)
        dpg.add_text("0x1602", color=(140, 140, 140, 255))

    _load_state()


def _section(title: str) -> None:
    dpg.add_separator()
    dpg.add_text(title, color=(200, 200, 80, 255))


def _folder_btn(callback) -> None:
    import dearpygui.dearpygui as _dpg
    if _dpg.does_alias_exist("folder_icon"):
        _dpg.add_image_button("folder_icon", width=22, height=22, callback=callback)
    else:
        _dpg.add_button(label="...", callback=callback)


def _browse_traffic_scenario() -> None:
    def _open_dialog():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select Traffic Scenario File",
            filetypes=[("MORAI Traffic Scenario", "*.anmroutes"), ("All files", "*.*")],
        )
        root.destroy()
        if path:
            ui_queue.post(lambda p=path: (
                dpg.set_value("traffic_scenario_path", p),
                _save_state(),
            ))
    threading.Thread(target=_open_dialog, daemon=True).start()


def _load_traffic_scenario() -> None:
    path = dpg.get_value("traffic_scenario_path").strip()
    if not path:
        log.append("[Traffic] .anmroutes file path is required.", level="WARN")
        return
    _save_state()
    _dispatch(
        proto.MSG_TYPE_LOAD_TRAFFIC_SCENARIO,
        lambda rid: tcp.send_load_traffic_scenario(_tcp_sock, rid, file_path=path),
    )


def _traffic_generate() -> None:
    autonomous = int(dpg.get_value("traffic_autonomous"))
    lc_rate = int(dpg.get_value("traffic_lc_rate"))
    _save_state()
    _dispatch(
        proto.MSG_TYPE_TRAFFIC_GENERATE,
        lambda rid, auto=autonomous, rate=lc_rate:
            tcp.send_traffic_generate(_tcp_sock, rid, autonomous=auto, lc_rate=rate),
    )


def _save_state() -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        data = {
            "traffic_scenario_path": dpg.get_value("traffic_scenario_path"),
            "traffic_autonomous": dpg.get_value("traffic_autonomous"),
            "traffic_lc_rate": dpg.get_value("traffic_lc_rate"),
        }
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[TrafficScenario] save state error: {exc}")


def _load_state() -> None:
    data = _read_state_file(_STATE_FILE)
    if not data:
        data = _read_state_file(_LEGACY_COMMANDS_STATE_FILE)

    if not data:
        return

    if data.get("traffic_scenario_path") and dpg.does_item_exist("traffic_scenario_path"):
        dpg.set_value("traffic_scenario_path", data["traffic_scenario_path"])
    if dpg.does_item_exist("traffic_autonomous"):
        dpg.set_value("traffic_autonomous", int(data.get("traffic_autonomous", 1)))
    if dpg.does_item_exist("traffic_lc_rate"):
        dpg.set_value("traffic_lc_rate", int(data.get("traffic_lc_rate", 0)))


def _read_state_file(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[TrafficScenario] load state error: {exc}")
        return {}
