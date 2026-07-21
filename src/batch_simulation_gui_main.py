from __future__ import annotations

import argparse
import ipaddress
import threading
import time
from typing import Callable, Optional, Sequence, Tuple

import dearpygui.dearpygui as dpg

from demo import DemoSession, DemoSessionError, ScenarioStatus
from demo.batch_config import (
    BatchSimulationConfig,
    DEFAULT_CONFIG_PATH,
    load_config,
    save_config,
)
import transport.protocol_defs as proto
import utils.ui_queue as ui_queue


_WINDOW = "batch_main_window"
_IP = "batch_tcp_ip"
_PORT = "batch_tcp_port"
_CONNECTION = "batch_connection_status"
_CONNECT = "batch_connect_button"
_DISCONNECT = "batch_disconnect_button"
_SUITE_PATH = "batch_suite_path"
_SUITE_LOAD = "batch_suite_load_button"
_SUITE_STATUS = "batch_suite_status"
_TIME_STATUS = "batch_time_status"
_TIME_GET = "batch_time_get_button"
_TIME_MODE = "batch_time_mode"
_TIME_SET = "batch_time_set_button"
_TARGET_FPS = "batch_target_fps"
_PHYSICS_DT = "batch_physics_dt"
_VARIABLE_GROUP = "batch_variable_group"
_FIXED_GROUP = "batch_fixed_group"
_RTF = "batch_rtf"
_USER_CONTROL = "batch_user_control"
_ELAPSED = "batch_elapsed"
_SCENARIO_STATUS = "batch_scenario_status"

_CONTROL_BUTTONS = (
    "batch_previous_button",
    "batch_stop_button",
    "batch_play_button",
    "batch_pause_button",
    "batch_next_button",
    "batch_status_button",
)

_STATE_NAMES = {1: "PLAY", 2: "PAUSE", 3: "STOP", 4: "COMPLETED"}
_RTF_VALUES = {"Real-Time": 1, "Unlimited": 2}
_ICON_SIZE = 16
_ICON_TEXTURES = {
    "previous": "batch_icon_previous",
    "stop": "batch_icon_stop",
    "play": "batch_icon_play",
    "pause": "batch_icon_pause",
    "next": "batch_icon_next",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MORAI batch simulation GUI")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Configuration JSON path (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser


class BatchSimulationGui:
    def __init__(self, config: BatchSimulationConfig, config_path: str) -> None:
        self.config = config
        self.config_path = config_path
        self.session = self._create_session(config.host, config.port)
        self._task_lock = threading.Lock()
        self._task_running = False
        self._worker: Optional[threading.Thread] = None
        self._elapsed_accumulated = 0.0
        self._elapsed_started: Optional[float] = None

    def _create_session(self, host: str, port: int) -> DemoSession:
        session = DemoSession(
            host=host,
            port=port,
            request_timeout=self.config.request_timeout,
            connect_timeout=self.config.connect_timeout,
        )
        session.add_scenario_status_listener(self._on_scenario_status)
        return session

    def build(self) -> None:
        self._create_icon_textures()
        with dpg.window(tag=_WINDOW, label="MORAI Batch Simulation"):
            dpg.add_text("MORAI Batch Simulation", color=(80, 170, 255, 255))
            dpg.add_separator()

            self._section("TCP")
            with dpg.group(horizontal=True):
                dpg.add_text("IP   :", color=(180, 180, 180, 255))
                dpg.add_input_text(tag=_IP, default_value=self.config.host, width=150)
                dpg.add_text("PORT :", color=(180, 180, 180, 255))
                dpg.add_input_int(
                    tag=_PORT,
                    default_value=self.config.port,
                    min_value=1,
                    max_value=65535,
                    step=0,
                    width=90,
                )
                dpg.add_button(label="Connect", tag=_CONNECT, callback=self._on_connect, width=90)
                dpg.add_button(
                    label="Disconnect",
                    tag=_DISCONNECT,
                    callback=self._on_disconnect,
                    width=90,
                    show=False,
                )
                dpg.add_text("Disconnected", tag=_CONNECTION, color=(255, 120, 120, 255))

            self._section("SUITE")
            with dpg.group(horizontal=True):
                dpg.add_text("Browse :", color=(180, 180, 180, 255))
                dpg.add_button(label="...", callback=self._on_browse_suite, width=35)
            with dpg.group(horizontal=True):
                dpg.add_text("Path   :", color=(180, 180, 180, 255))
                dpg.add_input_text(
                    tag=_SUITE_PATH,
                    default_value=self.config.suite_path,
                    hint="suite file path",
                    width=-1,
                )
            with dpg.group(horizontal=True):
                dpg.add_text("Load   :", color=(180, 180, 180, 255))
                dpg.add_button(
                    label="Load",
                    tag=_SUITE_LOAD,
                    callback=self._on_load_suite,
                    width=75,
                    enabled=False,
                )
                dpg.add_text("-", tag=_SUITE_STATUS, color=(140, 140, 140, 255))

            self._section("SIMULATION TIME")
            with dpg.group(horizontal=True):
                dpg.add_text("Sim Status :", color=(180, 180, 180, 255))
                dpg.add_button(
                    label="Get",
                    tag=_TIME_GET,
                    callback=self._on_get_time_status,
                    width=75,
                    enabled=False,
                )
                dpg.add_text("-", tag=_TIME_STATUS, color=(140, 140, 140, 255))
            with dpg.group(horizontal=True):
                dpg.add_text("Mode       :", color=(180, 180, 180, 255))
                dpg.add_combo(
                    tag=_TIME_MODE,
                    items=["Variable", "Fixed"],
                    default_value=self.config.time_mode,
                    width=105,
                    callback=self._on_time_mode_changed,
                )
                dpg.add_button(
                    label="Set",
                    tag=_TIME_SET,
                    callback=self._on_set_time_mode,
                    width=75,
                    enabled=False,
                )
            with dpg.group(horizontal=True):
                dpg.add_text("Target FPS :", color=(180, 180, 180, 255))
                dpg.add_input_int(
                    tag=_TARGET_FPS,
                    default_value=self.config.target_fps,
                    min_value=10,
                    max_value=200,
                    step=0,
                    width=80,
                )
                dpg.add_spacer(width=12)
                dpg.add_text("Physics DT :", color=(180, 180, 180, 255))
                dpg.add_input_int(
                    tag=_PHYSICS_DT,
                    default_value=self.config.physics_delta_time,
                    min_value=5,
                    max_value=100,
                    step=0,
                    width=80,
                )
                dpg.add_text("ms", color=(160, 160, 160, 255))
            with dpg.group(tag=_VARIABLE_GROUP, show=self.config.time_mode == "Variable"):
                dpg.add_text(
                    "Variable mode sends rtf=0 and user_control=0.",
                    color=(160, 160, 160, 255),
                )
            with dpg.group(tag=_FIXED_GROUP, show=self.config.time_mode == "Fixed"):
                with dpg.group(horizontal=True):
                    dpg.add_text("RTF        :", color=(180, 180, 180, 255))
                    dpg.add_combo(
                        tag=_RTF,
                        items=["Real-Time", "Unlimited"],
                        default_value="Unlimited" if self.config.rtf == 2 else "Real-Time",
                        width=105,
                    )
                    dpg.add_spacer(width=12)
                    dpg.add_checkbox(
                        tag=_USER_CONTROL,
                        label="User Control",
                        default_value=self.config.user_control,
                    )

            self._section("SCENARIO")
            with dpg.group(horizontal=True):
                dpg.add_text("Elapsed   :", color=(180, 180, 180, 255))
                dpg.add_text("0:00", tag=_ELAPSED, color=(160, 200, 160, 255))
            with dpg.group(horizontal=True):
                dpg.add_text("Control   :", color=(180, 180, 180, 255))
                self._control_button("Previous", "batch_previous_button", "previous")
                self._control_button("Stop", "batch_stop_button", "stop")
                self._control_button("Play", "batch_play_button", "play")
                self._control_button("Pause", "batch_pause_button", "pause")
                self._control_button("Next", "batch_next_button", "next")
            with dpg.group(horizontal=True):
                dpg.add_text("Status    :", color=(180, 180, 180, 255))
                dpg.add_button(
                    label="Get",
                    tag="batch_status_button",
                    callback=self._on_get_status,
                    width=75,
                    enabled=False,
                )
                dpg.add_text("-", tag=_SCENARIO_STATUS, color=(140, 140, 140, 255))

    def start(self) -> None:
        self._on_connect()

    def close(self) -> None:
        self._save_preferences()
        self.session.close()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.5)

    def _save_preferences(self) -> None:
        if not dpg.does_item_exist(_WINDOW):
            return
        try:
            saved = BatchSimulationConfig(
                suite_path=str(dpg.get_value(_SUITE_PATH)).strip(),
                scenario_name=self.config.scenario_name,
                host=str(dpg.get_value(_IP)).strip(),
                port=int(dpg.get_value(_PORT)),
                connect_timeout=self.config.connect_timeout,
                request_timeout=self.config.request_timeout,
                load_timeout=self.config.load_timeout,
                time_mode=str(dpg.get_value(_TIME_MODE)),
                target_fps=int(dpg.get_value(_TARGET_FPS)),
                physics_delta_time=int(dpg.get_value(_PHYSICS_DT)),
                rtf=_RTF_VALUES.get(str(dpg.get_value(_RTF)), 1),
                user_control=bool(dpg.get_value(_USER_CONTROL)),
            )
            save_config(self.config_path, saved)
            self._log(f"Saved preferences: {self.config_path}")
        except (OSError, TypeError, ValueError) as exc:
            self._log(f"Failed to save preferences: {exc}", "ERROR")

    def tick(self) -> None:
        elapsed = self._current_elapsed()
        dpg.set_value(_ELAPSED, self._format_seconds(int(elapsed)))

    def _section(self, label: str) -> None:
        dpg.add_spacer(height=6)
        dpg.add_text(label, color=(100, 180, 255, 255))

    def _control_button(self, label: str, tag: str, command: str) -> None:
        dpg.add_image_button(
            _ICON_TEXTURES[command],
            tag=tag,
            callback=lambda sender, app_data, user_data: self._on_control(user_data),
            user_data=command,
            width=20,
            height=20,
            enabled=False,
        )
        with dpg.tooltip(tag):
            dpg.add_text(label)

    def _create_icon_textures(self) -> None:
        with dpg.texture_registry(show=False):
            for command, texture_tag in _ICON_TEXTURES.items():
                dpg.add_static_texture(
                    _ICON_SIZE,
                    _ICON_SIZE,
                    self._icon_pixels(command),
                    tag=texture_tag,
                )

    @staticmethod
    def _icon_pixels(command: str):
        size = _ICON_SIZE
        pixels = [0.0] * (size * size * 4)

        def paint(x: int, y: int) -> None:
            if 0 <= x < size and 0 <= y < size:
                offset = (y * size + x) * 4
                pixels[offset:offset + 4] = [0.82, 0.82, 0.86, 1.0]

        def triangle_right(left: int) -> None:
            for x in range(6):
                half_height = 5 - x
                for y in range(7 - half_height, 9 + half_height):
                    paint(left + x, y)

        def triangle_left(left: int) -> None:
            for x in range(6):
                half_height = x
                for y in range(7 - half_height, 9 + half_height):
                    paint(left + x, y)

        if command == "play":
            triangle_right(5)
        elif command == "stop":
            for y in range(5, 12):
                for x in range(5, 12):
                    paint(x, y)
        elif command == "pause":
            for y in range(4, 13):
                for x in (5, 6, 10, 11):
                    paint(x, y)
        elif command == "previous":
            triangle_left(2)
            triangle_left(8)
        elif command == "next":
            triangle_right(2)
            triangle_right(8)
        return pixels

    def _on_connect(self) -> None:
        try:
            host, port = self._read_tcp_endpoint()
        except ValueError as exc:
            self._set_connection("Invalid IP/PORT", (255, 170, 80, 255))
            self._log(str(exc), "ERROR")
            return

        def work() -> None:
            self.session.close()
            self.session = self._create_session(host, port)
            ui_queue.post(lambda: self._set_connection("Connecting...", (255, 190, 90, 255)))
            self._log(f"Connecting {host}:{port}...")
            self.session.connect()
            self._log(f"Connected {host}:{port}")
            ui_queue.post(lambda: self._set_connection("Connected", (100, 220, 100, 255)))

        self._start_task("Connect", work)

    def _on_disconnect(self) -> None:
        def work() -> None:
            self.session.close()
            self._log("Disconnected")
            ui_queue.post(self._apply_disconnected)

        self._start_task("Disconnect", work)

    def _on_browse_suite(self) -> None:
        def browse() -> None:
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
                ui_queue.post(lambda p=path: dpg.set_value(_SUITE_PATH, p))

        threading.Thread(target=browse, name="BatchGui-SuiteBrowse", daemon=True).start()

    def _on_load_suite(self) -> None:
        path = str(dpg.get_value(_SUITE_PATH)).strip()
        if not path:
            self._log("Suite path is required", "WARN")
            return

        def work() -> None:
            ui_queue.post(lambda: self._set_suite_status("Loading...", (255, 190, 90, 255)))
            started = time.monotonic()
            self._log(f"Loading suite: {path}")
            self.session.load_suite(path, timeout=self.config.load_timeout)
            elapsed = time.monotonic() - started
            self._log(f"Suite loaded in {elapsed:.1f}s")
            ui_queue.post(
                lambda e=elapsed: self._set_suite_status(
                    f"Complete ({e:.1f}s)",
                    (100, 220, 100, 255),
                )
            )

        self._start_task("Load Suite", work)

    def _on_time_mode_changed(self, sender=None, app_data=None) -> None:
        mode = str(app_data if app_data is not None else dpg.get_value(_TIME_MODE))
        is_variable = mode == "Variable"
        dpg.configure_item(_VARIABLE_GROUP, show=is_variable)
        dpg.configure_item(_FIXED_GROUP, show=not is_variable)

    def _on_set_time_mode(self) -> None:
        mode_name = str(dpg.get_value(_TIME_MODE))
        mode = proto.TIME_MODE_VARIABLE if mode_name == "Variable" else proto.TIME_MODE_FIXED
        target_fps = int(dpg.get_value(_TARGET_FPS))
        physics_dt = int(dpg.get_value(_PHYSICS_DT))
        rtf = _RTF_VALUES.get(str(dpg.get_value(_RTF)), 1) if mode == proto.TIME_MODE_FIXED else 0
        user_control = bool(dpg.get_value(_USER_CONTROL)) if mode == proto.TIME_MODE_FIXED else False

        def work() -> None:
            response = self.session.set_time_mode(
                mode=mode,
                target_fps=target_fps,
                physics_delta_time=physics_dt,
                rtf=rtf,
                user_control=user_control,
            )
            self._log(
                f"Simulation time mode set: {mode_name} "
                f"fps={target_fps} physics_dt={physics_dt} rtf={rtf} "
                f"user_control={int(user_control)}"
            )
            ui_queue.post(
                lambda r=response: self._set_time_status(
                    self._time_mode_name(int(r.get("mode", mode))),
                    (100, 220, 100, 255),
                )
            )

        self._start_task("Set Simulation Time", work)

    def _on_get_time_status(self) -> None:
        def work() -> None:
            response = self.session.get_time_status()
            self._log(
                f"Simulation time status: mode={self._time_mode_name(response['mode'])} "
                f"fps={response['target_fps']} physics_dt={response['physics_delta_time']} "
                f"rtf={response['rtf']} user_control={response['user_control']} "
                f"step={response['step_index']}"
            )
            ui_queue.post(lambda r=response: self._apply_time_status(r))

        self._start_task("Get Simulation Time", work)

    def _on_control(self, command: str) -> None:
        def work() -> None:
            action = getattr(self.session, command)
            action("")
            self._log(f"Scenario {command} accepted")
            ui_queue.post(lambda: self._control_succeeded(command))

        self._start_task(f"Scenario {command}", work)

    def _on_get_status(self) -> None:
        def work() -> None:
            self.session.get_scenario_status()

        self._start_task("Scenario Status", work)

    def _start_task(self, label: str, work: Callable[[], None]) -> None:
        with self._task_lock:
            if self._task_running:
                self._log(f"Busy; {label} was not started", "WARN")
                return
            self._task_running = True
        self._apply_button_state()

        def run() -> None:
            try:
                work()
            except (DemoSessionError, OSError, ValueError) as exc:
                self._log(str(exc), "ERROR")
                ui_queue.post(lambda e=str(exc): self._handle_task_error(e))
            finally:
                with self._task_lock:
                    self._task_running = False
                ui_queue.post(self._apply_button_state)

        self._worker = threading.Thread(target=run, name=f"BatchGui-{label}", daemon=True)
        self._worker.start()

    def _read_tcp_endpoint(self) -> Tuple[str, int]:
        host = str(dpg.get_value(_IP)).strip()
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError(f"Invalid TCP IP: {host!r}") from exc
        if address.version != 4:
            raise ValueError(f"TCP IP must be IPv4: {host!r}")
        port = int(dpg.get_value(_PORT))
        if not 1 <= port <= 65535:
            raise ValueError(f"TCP port out of range: {port}")
        return str(address), port

    def _handle_task_error(self, message: str) -> None:
        if not self.session.is_connected:
            self._apply_disconnected()
        if dpg.get_value(_SUITE_STATUS) == "Loading...":
            self._set_suite_status("Failed", (255, 120, 120, 255))

    def _apply_disconnected(self) -> None:
        self._set_connection("Disconnected", (255, 120, 120, 255))
        self._reset_elapsed()

    def _set_connection(self, text: str, color) -> None:
        connected = text == "Connected"
        dpg.set_value(_CONNECTION, text)
        dpg.configure_item(_CONNECTION, color=color)
        dpg.configure_item(_IP, enabled=not connected)
        dpg.configure_item(_PORT, enabled=not connected)
        dpg.configure_item(_CONNECT, show=not connected)
        dpg.configure_item(_DISCONNECT, show=connected)
        self._apply_button_state()

    def _set_suite_status(self, text: str, color) -> None:
        dpg.set_value(_SUITE_STATUS, text)
        dpg.configure_item(_SUITE_STATUS, color=color)

    def _set_time_status(self, text: str, color) -> None:
        dpg.set_value(_TIME_STATUS, text)
        dpg.configure_item(_TIME_STATUS, color=color)

    def _apply_time_status(self, response) -> None:
        mode = int(response["mode"])
        mode_name = self._time_mode_name(mode)
        dpg.set_value(_TIME_MODE, mode_name)
        dpg.set_value(_TARGET_FPS, int(response["target_fps"]))
        dpg.set_value(_PHYSICS_DT, int(response["physics_delta_time"]))
        dpg.set_value(_RTF, "Unlimited" if int(response["rtf"]) == 2 else "Real-Time")
        dpg.set_value(_USER_CONTROL, bool(response["user_control"]))
        self._on_time_mode_changed(app_data=mode_name)
        self._set_time_status(mode_name, (100, 220, 100, 255))

    @staticmethod
    def _time_mode_name(mode: int) -> str:
        if mode == proto.TIME_MODE_VARIABLE:
            return "Variable"
        if mode == proto.TIME_MODE_FIXED:
            return "Fixed"
        return f"UNKNOWN({mode})"

    def _apply_button_state(self) -> None:
        with self._task_lock:
            busy = self._task_running
        connected = self.session.is_connected
        dpg.configure_item(_CONNECT, enabled=not busy)
        dpg.configure_item(_DISCONNECT, enabled=not busy)
        dpg.configure_item(_SUITE_LOAD, enabled=connected and not busy)
        dpg.configure_item(_TIME_GET, enabled=connected and not busy)
        dpg.configure_item(_TIME_SET, enabled=connected and not busy)
        for tag in _CONTROL_BUTTONS:
            dpg.configure_item(tag, enabled=connected and not busy)

    def _on_scenario_status(self, status: ScenarioStatus) -> None:
        ui_queue.post(lambda s=status: self._apply_scenario_status(s))

    def _apply_scenario_status(self, status: ScenarioStatus) -> None:
        state = _STATE_NAMES.get(status.state, f"UNKNOWN({status.state})")
        text = state if not status.name else f"{state} ({status.name})"
        dpg.set_value(_SCENARIO_STATUS, text)
        dpg.configure_item(_SCENARIO_STATUS, color=(100, 220, 100, 255))
        if status.state == 2:
            self._pause_elapsed()
        elif status.state in (3, 4):
            self._reset_elapsed()
        self._log(f"Scenario status: {text}")

    def _control_succeeded(self, command: str) -> None:
        if command == "play":
            if self._elapsed_started is None:
                self._elapsed_started = time.monotonic()
        elif command == "pause":
            self._pause_elapsed()
        elif command in ("stop", "previous", "next"):
            self._reset_elapsed()

    def _pause_elapsed(self) -> None:
        if self._elapsed_started is not None:
            self._elapsed_accumulated += max(0.0, time.monotonic() - self._elapsed_started)
            self._elapsed_started = None

    def _reset_elapsed(self) -> None:
        self._elapsed_accumulated = 0.0
        self._elapsed_started = None
        if dpg.does_item_exist(_ELAPSED):
            dpg.set_value(_ELAPSED, "0:00")

    def _current_elapsed(self) -> float:
        elapsed = self._elapsed_accumulated
        if self._elapsed_started is not None:
            elapsed += max(0.0, time.monotonic() - self._elapsed_started)
        return elapsed

    @staticmethod
    def _format_seconds(seconds: int) -> str:
        return f"{seconds // 60}:{seconds % 60:02d}"

    @staticmethod
    def _log(message: str, level: str = "INFO") -> None:
        print(f"[{level}] {message}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 2

    dpg.create_context()
    gui = BatchSimulationGui(config, args.config)
    try:
        gui.build()
        dpg.create_viewport(
            title="MORAI Batch Simulation",
            width=720,
            height=600,
            min_width=640,
            min_height=540,
            resizable=True,
        )
        dpg.setup_dearpygui()
        dpg.set_primary_window(_WINDOW, True)
        dpg.show_viewport()
        gui.start()

        try:
            while dpg.is_dearpygui_running():
                ui_queue.drain()
                gui.tick()
                dpg.render_dearpygui_frame()
            return 0
        except KeyboardInterrupt:
            return 130
    finally:
        gui.close()
        ui_queue.drain()
        dpg.destroy_context()


if __name__ == "__main__":
    raise SystemExit(main())
