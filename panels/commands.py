# panels/commands.py
from __future__ import annotations
from typing import Callable, Optional
import threading

import dearpygui.dearpygui as dpg
import utils.ui_queue as ui_queue
import transport.protocol_defs as proto
import transport.tcp_transport as tcp
import panels.log as log

_tcp_sock                           = None
_dispatch:         Optional[Callable] = None
_toggle_auto:      Optional[Callable] = None

def init(tcp_sock, dispatch_fn: Callable, toggle_auto_fn: Callable) -> None:
    global _tcp_sock, _dispatch, _toggle_auto
    _tcp_sock    = tcp_sock
    _dispatch    = dispatch_fn
    _toggle_auto = toggle_auto_fn


def build(parent: int | str) -> None:
    with dpg.child_window(parent=parent, width=-1, height=-1, border=False):

        # ── Suite ──────────────────────────────────────────
        _section("SUITE")

        # Status : [Get]
        with dpg.group(horizontal=True):
            dpg.add_text("Status    :", color=(180, 180, 180, 255))
            dpg.add_button(label="Get",
                callback=lambda: _dispatch(
                    proto.MSG_TYPE_ACTIVE_SUITE_STATUS,
                    lambda rid: tcp.send_active_suite_status(_tcp_sock, rid)))

        # Browse : [파일 선택]
        # Path   : [경로 표시]
        # Load   : [Load]
        with dpg.group(horizontal=True):
            dpg.add_text("Browse    :", color=(180, 180, 180, 255))
            _folder_btn(callback=_browse_suite)
        with dpg.group(horizontal=True):
            dpg.add_text("Path      :", color=(180, 180, 180, 255))
            dpg.add_input_text(tag="suite_path", width=-1, hint="suite file path")
        with dpg.group(horizontal=True):
            dpg.add_text("Load      :", color=(180, 180, 180, 255))
            dpg.add_button(label="Load", callback=_load_suite)

        # ── Simulation Time ────────────────────────────────
        _section("SIMULATION TIME")

        # Sim Status : [Get]
        with dpg.group(horizontal=True):
            dpg.add_text("Sim Status :", color=(180, 180, 180, 255))
            dpg.add_button(label="Get",
                callback=lambda: _dispatch(
                    proto.MSG_TYPE_GET_SIMULATION_TIME_STATUS,
                    lambda rid: tcp.send_get_status(_tcp_sock, rid)))

        # Mode : [combo] [Hz / speed input] [Set]
        _MODE_ITEMS = ["Variable", "Fixed Delta", "Fixed Step"]
        with dpg.group(horizontal=True):
            dpg.add_text("Mode       :", color=(180, 180, 180, 255))
            dpg.add_combo(tag="sim_mode_combo", items=_MODE_ITEMS,
                          default_value="Fixed Step", width=105,
                          callback=_on_sim_mode_combo)
            dpg.add_input_float(tag="sim_hz", default_value=60.0,
                                min_value=1.0, max_value=1000.0,
                                format="%.1f", step=0, width=65, show=True)
            dpg.add_text("Hz", tag="sim_hz_label",
                         color=(160, 160, 160, 255), show=True)
            dpg.add_input_int(tag="sim_speed", default_value=1,
                              min_value=1, max_value=100,
                              step=0, width=55, show=False)
            dpg.add_text("x", tag="sim_speed_label",
                         color=(160, 160, 160, 255), show=False)
            dpg.add_button(label="Set", callback=_on_set_sim_mode)

        # ── Scenario ───────────────────────────────────────
        _section("SCENARIO")

        # Name : [scenario name input]
        with dpg.group(horizontal=True):
            dpg.add_text("Name      :", color=(180, 180, 180, 255))
            dpg.add_input_text(tag="sc_name", default_value="",
                               width=-1, hint="scenario name")

        # Control : [Prev] [Stop] [Play] [Pause] [Next]
        _SC = {"◀◀": 4, "■": 3, "▶": 1, "II": 2, "▶▶": 5}
        with dpg.group(horizontal=True):
            dpg.add_text("Control   :", color=(180, 180, 180, 255))
            for label, cmd in _SC.items():
                dpg.add_button(
                    label=label,
                    user_data=cmd,
                    callback=lambda s, a, u: _dispatch(
                        proto.MSG_TYPE_SCENARIO_CONTROL,
                        lambda rid, cc=u: tcp.send_scenario_control(
                            _tcp_sock, rid,
                            command=cc,
                            scenario_name=dpg.get_value("sc_name"))))

        # Status : [Get]
        with dpg.group(horizontal=True):
            dpg.add_text("Status    :", color=(180, 180, 180, 255))
            dpg.add_button(label="Get",
                callback=lambda: _dispatch(
                    proto.MSG_TYPE_SCENARIO_STATUS,
                    lambda rid: tcp.send_scenario_status(_tcp_sock, rid)))

        # ── Object Control ─────────────────────────────────
        _section("OBJECT CONTROL")

        # ID : [entity_id input]
        with dpg.group(horizontal=True):
            dpg.add_text("ID        :", color=(180, 180, 180, 255))
            dpg.add_input_text(tag="obj_entity_id",
                               default_value="Car_1", width=140)

        # ── Manual Control (collapsing) ────────────────────
        with dpg.collapsing_header(label="Manual Control", default_open=True):
            dpg.add_spacer(height=2)
            with dpg.group(horizontal=True):
                for tag, label, default in [
                    ("mc_thr",   "Throttle",    0.4),
                    ("mc_brk",   "Brake",       0.0),
                    ("mc_steer", "Steer Angle", 0.0),
                ]:
                    dpg.add_text(label, color=(160, 160, 160, 255))
                    dpg.add_input_float(tag=tag, default_value=default,
                                        min_value=-1.0, max_value=1.0,
                                        step=0, width=60, format="%.2f")
            dpg.add_spacer(height=2)
            dpg.add_button(label="Send",
                callback=lambda: _dispatch(
                    proto.MSG_TYPE_MANUAL_CONTROL_BY_ID_COMMAND,
                    lambda rid: tcp.send_manual_control_by_id(
                        _tcp_sock, rid,
                        entity_id=dpg.get_value("obj_entity_id"),
                        throttle=dpg.get_value("mc_thr"),
                        brake=dpg.get_value("mc_brk"),
                        steer_angle=dpg.get_value("mc_steer"))))

        # ── Transform Control (collapsing) ─────────────────
        with dpg.collapsing_header(label="Transform Control", default_open=True):
            dpg.add_spacer(height=2)
            with dpg.group(horizontal=True):
                for tag, lbl in [("tc_px","px"),("tc_py","py"),("tc_pz","pz")]:
                    dpg.add_text(lbl, color=(160, 160, 160, 255))
                    dpg.add_input_float(tag=tag, default_value=0.0, step=0, width=80)
            with dpg.group(horizontal=True):
                for tag, lbl in [("tc_rx","rx"),("tc_ry","ry"),("tc_rz","rz")]:
                    dpg.add_text(lbl, color=(160, 160, 160, 255))
                    dpg.add_input_float(tag=tag, default_value=0.0, step=0, width=80)
            with dpg.group(horizontal=True):
                dpg.add_text("steer", color=(160, 160, 160, 255))
                dpg.add_input_float(tag="tc_steer", default_value=0.0, step=0, width=80)
            dpg.add_spacer(height=2)
            dpg.add_button(label="Send",
                callback=lambda: _dispatch(
                    proto.MSG_TYPE_TRANSFORM_CONTROL_BY_ID_COMMAND,
                    lambda rid: tcp.send_transform_control_by_id(
                        _tcp_sock, rid,
                        entity_id=dpg.get_value("obj_entity_id"),
                        pos_x=dpg.get_value("tc_px"), pos_y=dpg.get_value("tc_py"),
                        pos_z=dpg.get_value("tc_pz"), rot_x=dpg.get_value("tc_rx"),
                        rot_y=dpg.get_value("tc_ry"), rot_z=dpg.get_value("tc_rz"),
                        steer_angle=dpg.get_value("tc_steer"))))

        # ── Fixed Step ─────────────────────────────────────
        _section("FIXED STEP")

        # Step : count [input] [FixedStep]
        with dpg.group(horizontal=True):
            dpg.add_text("Step      :", color=(180, 180, 180, 255))
            dpg.add_text("count", color=(160, 160, 160, 255))
            dpg.add_input_int(tag="fs_step_count", default_value=1,
                              min_value=1, max_value=9999, width=60, step=0)
            dpg.add_button(label="▶ FixedStep",
                callback=lambda: _dispatch(
                    proto.MSG_TYPE_FIXED_STEP,
                    lambda rid: tcp.send_fixed_step(
                        _tcp_sock, rid,
                        step_count=dpg.get_value("fs_step_count"))))

        # SaveData : [Save]
        with dpg.group(horizontal=True):
            dpg.add_text("SaveData  :", color=(180, 180, 180, 255))
            dpg.add_button(label="Save",
                callback=lambda: _dispatch(
                    proto.MSG_TYPE_SAVE_DATA,
                    lambda rid: tcp.send_save_data(_tcp_sock, rid)))

        # Auto : [max_calls] [▶▶ AutoCaller]
        with dpg.group(horizontal=True):
            dpg.add_text("Auto      :", color=(180, 180, 180, 255))
            dpg.add_input_int(tag="auto_max_calls",
                              default_value=proto.MAX_CALL_NUM,
                              min_value=1, max_value=999999,
                              step=0, width=80)
            dpg.add_button(label="▶▶ AutoCaller", tag="btn_auto",
                           callback=_on_auto_toggle)

        # Progress bar
        with dpg.group(horizontal=True):
            dpg.add_text("          ", color=(180, 180, 180, 255))
            dpg.add_text("0", tag="auto_progress_text")
            dpg.add_text("/", color=(160, 160, 160, 255))
            dpg.add_text(str(proto.MAX_CALL_NUM), tag="auto_total_text",
                         color=(160, 160, 160, 255))
        dpg.add_progress_bar(tag="auto_progress_bar",
                             default_value=0.0, width=-1, overlay="")



def update_auto_progress(current: int, total: int) -> None:
    def _apply(c=current, t=total):
        if not dpg.does_item_exist("auto_progress_bar"):
            return
        ratio = c / t if t > 0 else 0.0
        dpg.set_value("auto_progress_bar", ratio)
        dpg.configure_item("auto_progress_bar", overlay=f"{c}/{t}")
        dpg.set_value("auto_progress_text", str(c))
        dpg.set_value("auto_total_text", str(t))
    ui_queue.post(_apply)


def reset_auto_ui() -> None:
    def _apply():
        if not dpg.does_item_exist("btn_auto"):
            return
        dpg.configure_item("btn_auto", label="▶▶ AutoCaller")
        dpg.set_value("auto_progress_bar", 0.0)
        dpg.configure_item("auto_progress_bar", overlay="")
        dpg.set_value("auto_progress_text", "0")
    ui_queue.post(_apply)


def _on_auto_toggle() -> None:
    if _toggle_auto is None:
        return
    max_calls = dpg.get_value("auto_max_calls")
    dpg.set_value("auto_total_text", str(max_calls))
    running = _toggle_auto(max_calls)
    label = "■ Stop" if running else "▶▶ AutoCaller"
    dpg.configure_item("btn_auto", label=label)


def _browse_suite() -> None:
    def _open_dialog():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select Suite File",
            filetypes=[("MORAI Suite", "*.msuite"), ("All files", "*.*")],
        )
        root.destroy()
        if path:
            ui_queue.post(lambda p=path: dpg.set_value("suite_path", p))
    threading.Thread(target=_open_dialog, daemon=True).start()


def _load_suite() -> None:
    path = dpg.get_value("suite_path").strip()
    if not path:
        log.append("[Suite] 파일 경로가 없습니다. Browse로 파일을 선택해 주세요.", level="WARN")
        return
    _dispatch(
        proto.MSG_TYPE_LOAD_SUITE,
        lambda rid: tcp.send_load_suite(_tcp_sock, rid, suite_path=path),
    )


def _on_sim_mode_combo(sender, app_data) -> None:
    is_variable = (app_data == "Variable")
    dpg.configure_item("sim_hz",          show=not is_variable)
    dpg.configure_item("sim_hz_label",    show=not is_variable)
    dpg.configure_item("sim_speed",       show=is_variable)
    dpg.configure_item("sim_speed_label", show=is_variable)


def _on_set_sim_mode() -> None:
    _MODE_MAP = {
        "Variable":    proto.TIME_MODE_VARIABLE,
        "Fixed Delta": proto.TIME_MODE_FIXED_DELTA,
        "Fixed Step":  proto.TIME_MODE_FIXED_STEP,
    }
    mode_str = dpg.get_value("sim_mode_combo")
    mode     = _MODE_MAP[mode_str]

    if mode == proto.TIME_MODE_VARIABLE:
        speed       = float(dpg.get_value("sim_speed"))
        fixed_delta = 0.0
    else:
        speed       = 1.0
        fixed_delta = 1000.0 / max(dpg.get_value("sim_hz"), 1.0)

    _dispatch(
        proto.MSG_TYPE_SET_SIMULATION_TIME_MODE_COMMAND,
        lambda rid, m=mode, fd=fixed_delta, sp=speed:
            tcp.send_simulation_time_mode_command(
                _tcp_sock, rid, mode=m, fixed_delta=fd, simulation_speed=sp),
    )


def _folder_btn(callback) -> None:
    """폴더 아이콘 버튼 — 텍스처가 없으면 텍스트 버튼으로 폴백."""
    import dearpygui.dearpygui as _dpg
    if _dpg.does_alias_exist("folder_icon"):
        _dpg.add_image_button("folder_icon", width=22, height=22, callback=callback)
    else:
        _dpg.add_button(label="...", callback=callback)


def _section(label: str) -> None:
    dpg.add_spacer(height=6)
    dpg.add_text(label, color=(200, 200, 100, 255))
    dpg.add_separator()
    dpg.add_spacer(height=2)



