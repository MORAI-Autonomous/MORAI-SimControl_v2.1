# panels/monitor.py
import math
import dearpygui.dearpygui as dpg
import ui_queue

_MAX_SPEED = 50.0

_T = {k: f"mon_{k}" for k in [
    "id", "time",
    "loc_x", "loc_y", "loc_z",
    "rot_x", "rot_y", "rot_z",
    "vel_x", "vel_y", "vel_z",
    "acc_x", "acc_y", "acc_z",
    "ang_x", "ang_y", "ang_z",
    "thr", "brk", "steer",
    "speed_bar",
]}


def build(parent: int | str) -> None:
    # child_window 없이 parent(tab)에 직접 추가 — 스크롤은 mon_window 담당
    dpg.add_text("Vehicle Info", color=(200, 200, 100, 255), parent=parent)
    dpg.add_separator(parent=parent)

    with dpg.group(horizontal=True, parent=parent):
        dpg.add_text("ID :")
        dpg.add_text("-", tag=_T["id"])
        dpg.add_spacer(width=20)
        dpg.add_text("Time :")
        dpg.add_text("-", tag=_T["time"])

    dpg.add_spacer(height=6, parent=parent)
    _section(parent, "Location (m)",   "loc")
    _section(parent, "Rotation (deg)", "rot")
    _section(parent, "Velocity (m/s)", "vel")
    _section(parent, "Acceleration",   "acc")
    _section(parent, "Angular Vel",    "ang")

    dpg.add_spacer(height=6, parent=parent)
    dpg.add_text("Control", color=(200, 200, 100, 255), parent=parent)
    dpg.add_separator(parent=parent)
    with dpg.table(parent=parent, header_row=True,
                   borders_innerV=True, resizable=True):
        dpg.add_table_column(label="Throttle")
        dpg.add_table_column(label="Brake")
        dpg.add_table_column(label="Steer")
        with dpg.table_row():
            dpg.add_text("0.000", tag=_T["thr"])
            dpg.add_text("0.000", tag=_T["brk"])
            dpg.add_text("0.000", tag=_T["steer"])

    dpg.add_spacer(height=4, parent=parent)
    dpg.add_text("Speed", parent=parent)
    dpg.add_progress_bar(
        tag=_T["speed_bar"],
        default_value=0.0,
        overlay="0.00 m/s",
        width=-1,
        parent=parent,
    )


def update(parsed: dict) -> None:
    ui_queue.post(lambda p=parsed: _apply(p))


def _apply(p: dict) -> None:
    if not dpg.does_item_exist(_T["id"]):
        return

    dpg.set_value(_T["id"],   p["id"])
    dpg.set_value(_T["time"], f"{p['seconds']}s {p['nanos']}ns")

    for prefix, key in [("loc", "location"), ("rot", "rotation"),
                        ("vel", "local_velocity"), ("acc", "local_acceleration"),
                        ("ang", "angular_velocity")]:
        for axis in ["x", "y", "z"]:
            dpg.set_value(_T[f"{prefix}_{axis}"], f"{p[key][axis]:.3f}")

    ctrl = p["control"]
    dpg.set_value(_T["thr"],   f"{ctrl['throttle']:.3f}")
    dpg.set_value(_T["brk"],   f"{ctrl['brake']:.3f}")
    dpg.set_value(_T["steer"], f"{ctrl['steer_angle']:.3f}")

    vel   = p["local_velocity"]
    speed = math.sqrt(vel["x"]**2 + vel["y"]**2 + vel["z"]**2)
    ratio = min(speed / _MAX_SPEED, 1.0)
    dpg.set_value(_T["speed_bar"], ratio)
    dpg.configure_item(_T["speed_bar"], overlay=f"{speed:.2f} m/s")


def _section(parent, label: str, prefix: str) -> None:
    dpg.add_text(label, color=(180, 180, 180, 255), parent=parent)
    with dpg.table(parent=parent, header_row=True,
                   borders_innerV=True, resizable=True):
        for axis in ["X", "Y", "Z"]:
            dpg.add_table_column(label=axis)
        with dpg.table_row():
            for axis in ["x", "y", "z"]:
                dpg.add_text("0.000", tag=_T[f"{prefix}_{axis}"])
    dpg.add_spacer(height=2, parent=parent)