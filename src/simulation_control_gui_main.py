from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Callable, Dict, Optional, Sequence, Tuple
import webbrowser

import dearpygui.dearpygui as dpg

from demo import DemoSession, DemoSessionError, ScenarioStatus
from demo.simulation_control_config import (
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    SimulationControlConfig,
    DEFAULT_CONFIG_PATH,
    load_config,
    save_config,
)
from demo.headless_launcher import (
    ActiveSessionError,
    HeadlessLoginError,
    MoraiHeadlessLogin,
    find_running_simulator_pid,
    launch_simulator,
)
from demo.session_store import clear_session, load_session, save_session
import transport.protocol_defs as proto
import utils.ui_queue as ui_queue


_WINDOW = "simulation_control_main_window"
_LOGIN_WINDOW = "simulation_control_login_window"
_LOGIN_CARD = "simulation_control_login_card"
_LOGIN_STATUS = "simulation_control_login_status"
_RUN_MODE = "simulation_control_run_mode"
_HEADLESS_LOGIN_GROUP = "simulation_control_headless_login_group"
_HEADLESS_AUTH_GROUP = "simulation_control_headless_auth_group"
_HEADLESS_START = "simulation_control_headless_start_button"
_LAUNCH_ACTION_SPACER = "simulation_control_launch_action_spacer"
_LOGIN_ID = "simulation_control_login_id"
_LOGIN_PASSWORD = "simulation_control_login_password"
_LOGIN_BUTTON = "simulation_control_login_button"
_REMEMBER_LOGIN = "simulation_control_remember_login"
_LOGOUT_BUTTON = "simulation_control_logout_button"
_GITHUB_BUTTON = "simulation_control_github_button"
_TCP_API_BUTTON = "simulation_control_tcp_api_button"
_SIMULATOR_PATH = "simulation_control_simulator_path"
_SIMULATOR_BROWSE = "simulation_control_simulator_browse_button"
_VERIFICATION_GROUP = "simulation_control_verification_group"
_VERIFICATION_CODE = "simulation_control_verification_code"
_VERIFY_BUTTON = "simulation_control_verify_button"
_HEADLESS_STATUS = "simulation_control_headless_status"
_IP = "simulation_control_tcp_ip"
_PORT = "simulation_control_tcp_port"
_CONNECTION = "simulation_control_connection_status"
_CONNECT = "simulation_control_connect_button"
_DISCONNECT = "simulation_control_disconnect_button"
_SIMULATOR_STATUS = "simulation_control_simulator_status"
_SIMULATOR_STATUS_GET = "simulation_control_simulator_status_get_button"
_SHUTDOWN_BUTTON = "simulation_control_shutdown_button"
_FORCE_SHUTDOWN_BUTTON = "simulation_control_force_shutdown_button"
_SUITE_PATH = "simulation_control_suite_path"
_SUITE_LOAD = "simulation_control_suite_load_button"
_SUITE_STATUS = "simulation_control_suite_status"
_TIME_STATUS = "simulation_control_time_status"
_TIME_GET = "simulation_control_time_get_button"
_TIME_MODE = "simulation_control_time_mode"
_TIME_SET = "simulation_control_time_set_button"
_TARGET_FPS = "simulation_control_target_fps"
_PHYSICS_DT = "simulation_control_physics_dt"
_VARIABLE_GROUP = "simulation_control_variable_group"
_FIXED_GROUP = "simulation_control_fixed_group"
_RTF = "simulation_control_rtf"
_USER_CONTROL = "simulation_control_user_control"
_SIMULATION_TIME = "simulation_control_simulation_time"
_SCENARIO_STATUS = "simulation_control_scenario_status"
_ACTIVE_SUITE = "simulation_control_active_suite"
_ACTIVE_SCENARIO = "simulation_control_active_scenario"
_SCENARIO_PROGRESS = "simulation_control_scenario_progress"

_CONTROL_BUTTONS = (
    "simulation_control_previous_button",
    "simulation_control_stop_button",
    "simulation_control_play_button",
    "simulation_control_pause_button",
    "simulation_control_next_button",
    "simulation_control_status_button",
)

_STATE_NAMES = {1: "PLAY", 2: "PAUSE", 3: "STOP", 4: "COMPLETED"}
_SIMULATOR_STATUS_AUTO_POLL = False
_SIMULATOR_STATUS_POLL_INTERVAL = 1.0
_SIMULATION_TIME_POLL_INTERVAL = 0.5
_SCENARIO_TRANSITION_REFRESH_DELAY = 0.25
_SCENARIO_TRANSITION_MAX_ATTEMPTS = 5
_PLAY_STATUS_MAX_ATTEMPTS = 12
_GITHUB_URL = "https://github.com/MORAI-Autonomous/MORAI-SimControl_v2.1"
_TCP_API_URL = (
    "https://github.com/MORAI-Autonomous/MORAI-SimControl_v2.1/"
    "blob/main/docs/tcp-api.md"
)
_RTF_VALUES = {"Real-Time": 1, "Unlimited": 2}
_ICON_SIZE = 16
_ICON_TEXTURES = {
    "previous": "simulation_control_icon_previous",
    "stop": "simulation_control_icon_stop",
    "play": "simulation_control_icon_play",
    "pause": "simulation_control_icon_pause",
    "next": "simulation_control_icon_next",
}
_SIMULATION_CONTROL_TITLE = "MORAI Simulation Control"
_TITLE_FONT = "simulation_control_title_font"
_SECTION_FONT = "simulation_control_section_font"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MORAI simulation control GUI")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Configuration JSON path (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser


def _format_scenario_progress(suite_status: Dict[str, object]) -> str:
    scenario_list = suite_status.get("scenario_list")
    if not isinstance(scenario_list, list) or not scenario_list:
        return "- / -"

    names = [str(name).strip() for name in scenario_list]
    active_name = str(suite_status.get("active_scenario_name", "")).strip()
    if not active_name:
        return f"- / {len(names)}"
    try:
        current_index = names.index(active_name) + 1
    except ValueError:
        return f"- / {len(names)}"
    return f"{current_index} / {len(names)}"


def _suite_load_block_reason(connected: bool, simulator_state: Optional[int]) -> str:
    if not connected:
        return "TCP is not connected"
    if simulator_state == 1:
        return "Suite cannot be loaded while the simulator is in PRE_LOGIN"
    return ""


def _bind_unicode_font() -> None:
    font_candidates = (
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/gulim.ttc"),
        Path("/mnt/c/Windows/Fonts/malgun.ttf"),
        Path("/mnt/c/Windows/Fonts/gulim.ttc"),
    )
    for font_path in font_candidates:
        if not font_path.is_file():
            continue
        with dpg.font_registry():
            with dpg.font(str(font_path), 14) as font:
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Korean)
                dpg.add_font_range(0x2000, 0x27FF)
            with dpg.font(str(font_path), 16, tag=_SECTION_FONT):
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Korean)
                dpg.add_font_range(0x2000, 0x27FF)
            with dpg.font(str(font_path), 18, tag=_TITLE_FONT):
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Korean)
                dpg.add_font_range(0x2000, 0x27FF)
        dpg.bind_font(font)
        return


class SimulationControlGui:
    def __init__(self, config: SimulationControlConfig, config_path: str) -> None:
        self.config = config
        self.config_path = config_path
        self.session = self._create_session(config.host, config.port)
        self._task_lock = threading.Lock()
        self._task_running = False
        self._worker: Optional[threading.Thread] = None
        self._time_poll_lock = threading.Lock()
        self._time_poll_in_flight = False
        self._time_poll_worker: Optional[threading.Thread] = None
        self._next_time_poll = time.monotonic() + _SIMULATION_TIME_POLL_INTERVAL
        self._suite_loaded = False
        self._closing = False
        self._completed_refresh_armed = False
        self._active_suite_name = ""
        self._active_scenario_name = ""
        self._scenario_refresh_generation = 0
        self._scenario_refresh_worker: Optional[threading.Thread] = None
        self._headless_login: Optional[MoraiHeadlessLogin] = None
        self._force_login_required = False
        self._headless_user_id = ""
        self._headless_tokens: Optional[Dict[str, str]] = None
        self._headless_process: Optional[subprocess.Popen] = None
        self._simulator_state: Optional[int] = None
        self._saved_login_id = config.login_id
        self._next_simulator_status_poll = (
            time.monotonic() + _SIMULATOR_STATUS_POLL_INTERVAL
        )

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
        with dpg.window(tag=_LOGIN_WINDOW, label="MORAI Login"):
            with dpg.child_window(
                tag=_LOGIN_CARD,
                width=430,
                height=350,
                pos=(145, 110),
                border=True,
                no_scrollbar=True,
            ):
                dpg.add_spacer(height=18)
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=157)
                    dpg.add_text("MORAI LOGIN", color=(80, 170, 255, 255))
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=114)
                    dpg.add_text("Sign in to use the simulator", color=(150, 150, 150, 255))
                dpg.add_spacer(height=12)
                dpg.add_separator()
                dpg.add_spacer(height=12)
                with dpg.group(tag=_HEADLESS_AUTH_GROUP):
                    with dpg.group(horizontal=True):
                        dpg.add_spacer(width=36)
                        dpg.add_text("ID :", color=(180, 180, 180, 255))
                        dpg.add_input_text(
                            tag=_LOGIN_ID,
                            default_value=self.config.login_id,
                            hint="Account ID",
                            width=300,
                        )
                    dpg.add_spacer(height=4)
                    with dpg.group(horizontal=True):
                        dpg.add_spacer(width=36)
                        dpg.add_text("PW :", color=(180, 180, 180, 255))
                        dpg.add_input_text(
                            tag=_LOGIN_PASSWORD,
                            hint="Password",
                            password=True,
                            width=300,
                        )
                    dpg.add_spacer(height=10)
                    with dpg.group(horizontal=True):
                        dpg.add_spacer(width=75)
                        dpg.add_checkbox(
                            label="Remember this device",
                            tag=_REMEMBER_LOGIN,
                            default_value=self.config.remember_login,
                        )
                    dpg.add_spacer(height=6)
                    with dpg.group(horizontal=True):
                        dpg.add_spacer(width=75)
                        dpg.add_button(
                            label="Login",
                            tag=_LOGIN_BUTTON,
                            callback=self._on_headless_login,
                            width=280,
                            height=30,
                        )
                    with dpg.group(tag=_VERIFICATION_GROUP, show=False):
                        dpg.add_spacer(height=8)
                        with dpg.group(horizontal=True):
                            dpg.add_spacer(width=36)
                            dpg.add_text("2FA:", color=(180, 180, 180, 255))
                            dpg.add_input_text(tag=_VERIFICATION_CODE, hint="6-digit code", width=154)
                            dpg.add_button(
                                label="Confirm Login",
                                tag=_VERIFY_BUTTON,
                                callback=self._on_verify_and_launch,
                                width=140,
                            )
                dpg.add_spacer(height=10)
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=75)
                    dpg.add_text(
                        "Enter your account",
                        tag=_LOGIN_STATUS,
                        color=(140, 140, 140, 255),
                        wrap=280,
                    )

        with dpg.window(tag=_WINDOW, label=_SIMULATION_CONTROL_TITLE, show=False):
            with dpg.menu_bar():
                with dpg.menu(label="Links"):
                    dpg.add_menu_item(
                        label="GitHub",
                        tag=_GITHUB_BUTTON,
                        callback=self._on_open_link,
                        user_data=_GITHUB_URL,
                    )
                    dpg.add_menu_item(
                        label="TCP API",
                        tag=_TCP_API_BUTTON,
                        callback=self._on_open_link,
                        user_data=_TCP_API_URL,
                    )
                with dpg.menu(label="Account"):
                    dpg.add_menu_item(
                        label="Logout",
                        tag=_LOGOUT_BUTTON,
                        callback=self._on_logout,
                    )
            title_item = dpg.add_text(
                _SIMULATION_CONTROL_TITLE,
                color=(80, 170, 255, 255),
            )
            if dpg.does_item_exist(_TITLE_FONT):
                dpg.bind_item_font(title_item, _TITLE_FONT)
            dpg.add_separator()

            self._section("Simulation Launch")
            with dpg.group(horizontal=True):
                dpg.add_text("Mode           :", color=(180, 180, 180, 255))
                dpg.add_combo(
                    tag=_RUN_MODE,
                    items=["Rendering Mode", "Headless Mode"],
                    default_value="Rendering Mode",
                    width=160,
                    callback=self._on_run_mode_changed,
                )
            with dpg.group(tag=_HEADLESS_LOGIN_GROUP):
                with dpg.group(horizontal=True):
                    dpg.add_text("Simulator Path :", color=(180, 180, 180, 255))
                    dpg.add_input_text(
                        tag=_SIMULATOR_PATH,
                        default_value=self.config.simulator_path,
                        width=-80,
                    )
                    dpg.add_button(
                        label="...",
                        tag=_SIMULATOR_BROWSE,
                        callback=self._on_browse_simulator,
                        width=35,
                    )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Start",
                        tag=_HEADLESS_START,
                        callback=self._on_headless_start,
                        width=90,
                    )
                    dpg.add_spacer(tag=_LAUNCH_ACTION_SPACER, width=400)
                    dpg.add_button(
                        label="Shutdown",
                        tag=_SHUTDOWN_BUTTON,
                        callback=self._on_shutdown_simulator,
                        user_data=False,
                        width=90,
                        enabled=False,
                    )
                    dpg.add_button(
                        label="Force Shutdown",
                        tag=_FORCE_SHUTDOWN_BUTTON,
                        callback=self._on_shutdown_simulator,
                        user_data=True,
                        width=120,
                        enabled=False,
                    )
                with dpg.group(horizontal=True):
                    dpg.add_text("Status :", color=(180, 180, 180, 255))
                    dpg.add_text("Ready", tag=_HEADLESS_STATUS, color=(140, 140, 140, 255))

            self._section("TCP Connection")
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

            with dpg.group(horizontal=True):
                dpg.add_text("Simulator Status :", color=(180, 180, 180, 255))
                dpg.add_button(
                    label="Get",
                    tag=_SIMULATOR_STATUS_GET,
                    callback=self._on_get_simulator_status,
                    width=75,
                    enabled=False,
                )
                dpg.add_text("-", tag=_SIMULATOR_STATUS, color=(140, 140, 140, 255))

            self._section("Suite Load")
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

            self._section("Simulation Time")
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
                    "Variable: simulator-managed timing; RTF and external control are disabled.",
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
                        label="Wait for External Control",
                        default_value=self.config.user_control,
                    )
                    with dpg.tooltip(_USER_CONTROL):
                        dpg.add_text(
                            "Fixed mode only.\n"
                            "Waits for external vehicle-control input over TCP or UDP.\n"
                            "The simulator may remain paused until the first input arrives."
                        )
                dpg.add_text(
                    "External Control can start paused until TCP or UDP control input arrives.",
                    color=(160, 160, 160, 255),
                )

            self._section("Scenario Control")
            with dpg.group(horizontal=True):
                dpg.add_text("Simulation Time :", color=(180, 180, 180, 255))
                dpg.add_text(
                    "0:00.000",
                    tag=_SIMULATION_TIME,
                    color=(160, 200, 160, 255),
                )
            with dpg.group(horizontal=True):
                dpg.add_text("Control   :", color=(180, 180, 180, 255))
                self._control_button("Previous", "simulation_control_previous_button", "previous")
                self._control_button("Stop", "simulation_control_stop_button", "stop")
                self._control_button("Play", "simulation_control_play_button", "play")
                self._control_button("Pause", "simulation_control_pause_button", "pause")
                self._control_button("Next", "simulation_control_next_button", "next")
            with dpg.group(horizontal=True):
                dpg.add_text("Control Status  :", color=(180, 180, 180, 255))
                dpg.add_button(
                    label="Get",
                    tag="simulation_control_status_button",
                    callback=self._on_get_status,
                    width=75,
                    enabled=False,
                )
                dpg.add_text("-", tag=_SCENARIO_STATUS, color=(140, 140, 140, 255))
            with dpg.group(horizontal=True):
                dpg.add_text("Active Suite    :", color=(180, 180, 180, 255))
                dpg.add_text("-", tag=_ACTIVE_SUITE, color=(140, 140, 140, 255))
            with dpg.group(horizontal=True):
                dpg.add_text("Active Scenario :", color=(180, 180, 180, 255))
                dpg.add_text("-", tag=_ACTIVE_SCENARIO, color=(140, 140, 140, 255))
            with dpg.group(horizontal=True):
                dpg.add_text("Scenario Progress:", color=(180, 180, 180, 255))
                dpg.add_text("-", tag=_SCENARIO_PROGRESS, color=(140, 140, 140, 255))

    def start(self) -> None:
        if self.config.remember_login:
            self._restore_remembered_login()

    def close(self) -> None:
        self._closing = True
        self._save_preferences()
        self.session.close()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.5)
        time_worker = self._time_poll_worker
        if time_worker is not None and time_worker is not threading.current_thread():
            time_worker.join(timeout=1.5)
        scenario_worker = self._scenario_refresh_worker
        if scenario_worker is not None and scenario_worker is not threading.current_thread():
            scenario_worker.join(timeout=1.5)

    def _save_preferences(self) -> None:
        if not dpg.does_item_exist(_WINDOW):
            return
        try:
            saved = SimulationControlConfig(
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
                simulator_path=str(dpg.get_value(_SIMULATOR_PATH)).strip(),
                api_base_url=self.config.api_base_url,
                login_id=self._saved_login_id,
                remember_login=bool(dpg.get_value(_REMEMBER_LOGIN)),
                window_width=max(
                    MIN_WINDOW_WIDTH,
                    int(dpg.get_viewport_width()),
                ),
                window_height=max(
                    MIN_WINDOW_HEIGHT,
                    int(dpg.get_viewport_height()),
                ),
            )
            save_config(self.config_path, saved)
            if not saved.remember_login:
                clear_session()
            self._log(f"Saved preferences: {self.config_path}")
        except (OSError, TypeError, ValueError) as exc:
            self._log(f"Failed to save preferences: {exc}", "ERROR")

    def tick(self) -> None:
        if dpg.is_item_shown(_LOGIN_WINDOW):
            self._center_login_card()
        self._align_launch_actions()
        if _SIMULATOR_STATUS_AUTO_POLL:
            self._poll_simulator_status()
        self._poll_simulation_time()
        process = self._headless_process
        if process is not None:
            exit_code = process.poll()
            if exit_code is not None:
                self._headless_process = None
                self._set_headless_status(
                    f"Stopped (exit {exit_code})",
                    (255, 170, 80, 255),
                )

    @staticmethod
    def _center_login_card() -> None:
        viewport_width = dpg.get_viewport_client_width()
        viewport_height = dpg.get_viewport_client_height()
        x = max(20, (viewport_width - 430) // 2)
        y = max(20, (viewport_height - 350) // 2)
        dpg.set_item_pos(_LOGIN_CARD, (x, y))

    @staticmethod
    def _align_launch_actions() -> None:
        available_width = dpg.get_viewport_client_width()
        spacer_width = max(20, available_width - 360)
        dpg.configure_item(_LAUNCH_ACTION_SPACER, width=spacer_width)

    def _section(self, label: str) -> None:
        dpg.add_spacer(height=3)
        section_item = dpg.add_text(label, color=(100, 180, 255, 255))
        if dpg.does_item_exist(_SECTION_FONT):
            dpg.bind_item_font(section_item, _SECTION_FONT)

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
            response = self.session.get_simulator_status()
            state = int(response["state"])
            label = proto.SIMULATOR_STATE_MAP.get(state, f"UNKNOWN({state})")
            self._log(f"Simulator status after connect: {label}")
            ui_queue.post(lambda s=state: self._apply_simulator_status(s))

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

        threading.Thread(target=browse, name="SimulationControl-SuiteBrowse", daemon=True).start()

    def _on_browse_simulator(self) -> None:
        def browse() -> None:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Select MORAI Simulator",
                filetypes=[("MORAI Simulator", "MoraiSimulator.exe"), ("Executable", "*.exe")],
            )
            root.destroy()
            if path:
                ui_queue.post(lambda p=path: dpg.set_value(_SIMULATOR_PATH, p))

        threading.Thread(target=browse, name="SimulationControl-SimulatorBrowse", daemon=True).start()

    def _on_load_suite(self) -> None:
        path = str(dpg.get_value(_SUITE_PATH)).strip()
        if not path:
            self._log("Suite path is required", "WARN")
            return
        block_reason = _suite_load_block_reason(
            self.session.is_connected,
            self._simulator_state,
        )
        if block_reason:
            self._set_suite_status(block_reason, (255, 170, 80, 255))
            self._log(block_reason, "WARN")
            return
        self._prepare_suite_load()

        def work() -> None:
            self._suite_loaded = False
            status_response = self.session.get_simulator_status()
            simulator_state = int(status_response["state"])
            ui_queue.post(lambda s=simulator_state: self._apply_simulator_status(s))
            block_reason = _suite_load_block_reason(True, simulator_state)
            if block_reason:
                self._log(block_reason, "WARN")
                ui_queue.post(
                    lambda reason=block_reason: self._set_suite_status(
                        reason,
                        (255, 170, 80, 255),
                    )
                )
                return
            started = time.monotonic()
            self._log(f"Loading suite: {path}")
            response = self.session.load_suite(path, timeout=self.config.load_timeout)
            result_code = int(response.get("result_code", -1))
            detail_code = int(response.get("detail_code", -1))
            if result_code != 0 or detail_code != 0:
                raise ValueError(
                    f"LoadSuite failed (result={result_code}, detail={detail_code})"
                )
            elapsed = time.monotonic() - started
            self._suite_loaded = True
            self._log(f"Suite loaded in {elapsed:.1f}s")
            ui_queue.post(
                lambda e=elapsed: self._set_suite_status(
                    f"Complete ({e:.1f}s)",
                    (100, 220, 100, 255),
                )
            )
            self._schedule_active_suite_refresh(
                previous_name="",
                max_attempts=_PLAY_STATUS_MAX_ATTEMPTS,
            )

        self._start_task("Load Suite", work)

    def _prepare_suite_load(self) -> None:
        self._scenario_refresh_generation += 1
        self._completed_refresh_armed = False
        self._active_suite_name = ""
        self._active_scenario_name = ""
        self._set_suite_status("Loading...", (255, 190, 90, 255))
        dpg.set_value(_SCENARIO_STATUS, "-")
        dpg.configure_item(_SCENARIO_STATUS, color=(140, 140, 140, 255))
        dpg.set_value(_ACTIVE_SUITE, "-")
        dpg.configure_item(_ACTIVE_SUITE, color=(140, 140, 140, 255))
        dpg.set_value(_ACTIVE_SCENARIO, "-")
        dpg.configure_item(_ACTIVE_SCENARIO, color=(140, 140, 140, 255))
        dpg.set_value(_SCENARIO_PROGRESS, "-")
        dpg.configure_item(_SCENARIO_PROGRESS, color=(140, 140, 140, 255))
        dpg.set_value(_SIMULATION_TIME, "0:00.000")

    def _on_time_mode_changed(self, sender=None, app_data=None) -> None:
        mode = str(app_data if app_data is not None else dpg.get_value(_TIME_MODE))
        is_variable = mode == "Variable"
        dpg.configure_item(_VARIABLE_GROUP, show=is_variable)
        dpg.configure_item(_FIXED_GROUP, show=not is_variable)

    def _on_run_mode_changed(self, sender=None, app_data=None) -> None:
        mode = str(app_data if app_data is not None else dpg.get_value(_RUN_MODE))
        self._set_headless_status(mode, (140, 140, 140, 255))

    def _on_headless_start(self) -> None:
        simulator_path = str(dpg.get_value(_SIMULATOR_PATH)).strip()
        try:
            self._validate_simulator_path(simulator_path)
        except ValueError as exc:
            self._set_headless_status(str(exc), (255, 170, 80, 255))
            return
        running_pid = find_running_simulator_pid()
        if running_pid is not None:
            self._set_headless_status(
                f"Already running (PID {running_pid})",
                (255, 170, 80, 255),
            )
            return
        process = self._headless_process
        if process is not None and process.poll() is None:
            self._set_headless_status(
                f"Already running (PID {process.pid})",
                (255, 170, 80, 255),
            )
            return
        if self._headless_tokens is None or not self._headless_user_id:
            self._show_login_view("Login required")
            return
        run_mode = str(dpg.get_value(_RUN_MODE))
        headless = run_mode == "Headless Mode"

        def work() -> None:
            ui_queue.post(lambda: self._set_headless_status("Starting...", (255, 190, 90, 255)))
            process = self._launch_with_tokens(
                self._headless_user_id,
                self._headless_tokens,
                simulator_path,
                headless,
            )
            self._log(f"{run_mode} simulator launched. PID: {process.pid}")
            ui_queue.post(lambda pid=process.pid: self._headless_launched(pid))

        self._start_task("Start Simulator", work)

    def _on_headless_login(self) -> None:
        user_id = str(dpg.get_value(_LOGIN_ID)).strip()
        password = str(dpg.get_value(_LOGIN_PASSWORD))
        remember_login = bool(dpg.get_value(_REMEMBER_LOGIN))
        if not user_id:
            self._set_login_status("ID is required", (255, 170, 80, 255))
            return
        if not password:
            self._set_login_status("PW is required", (255, 170, 80, 255))
            return

        def work() -> None:
            login = MoraiHeadlessLogin(user_id, api_base_url=self.config.api_base_url)
            ui_queue.post(lambda: self._set_login_status("Logging in...", (255, 190, 90, 255)))
            tokens = login.login(password)
            if tokens is None:
                self._headless_login = login
                self._force_login_required = False
                self._log(f"Verification code requested for {user_id}")
                ui_queue.post(self._verification_code_requested)
                return
            self._remember_credentials(login, tokens, remember_login)
            self._log("Trusted-device login succeeded")
            ui_queue.post(self._login_succeeded)

        self._start_task("Headless Login", work)

    def _on_verify_and_launch(self) -> None:
        code = str(dpg.get_value(_VERIFICATION_CODE)).strip()
        login = self._headless_login
        remember_login = bool(dpg.get_value(_REMEMBER_LOGIN))
        if login is None:
            self._set_login_status("Request a verification code first", (255, 170, 80, 255))
            return
        if re.fullmatch(r"[0-9]{6}", code) is None:
            self._set_login_status("Enter the 6-digit verification code", (255, 170, 80, 255))
            return

        def work() -> None:
            ui_queue.post(lambda: self._set_login_status("Verifying...", (255, 190, 90, 255)))
            try:
                tokens = login.force_verify(code) if self._force_login_required else login.verify(code)
            except ActiveSessionError:
                self._force_login_required = True
                ui_queue.post(self._force_login_confirmation_required)
                return
            self._remember_credentials(login, tokens, remember_login)
            self._log("Login verification succeeded")
            ui_queue.post(self._login_succeeded)

        self._start_task("Verify Login", work)

    @staticmethod
    def _validate_simulator_path(simulator_path: str) -> None:
        if not simulator_path:
            raise ValueError("Simulator path is required")
        executable = Path(simulator_path).expanduser()
        if not executable.is_file():
            raise ValueError("Simulator executable was not found")
        if executable.suffix.lower() != ".exe":
            raise ValueError("Simulator path must point to an .exe file")

    def _verification_code_requested(self) -> None:
        dpg.set_value(_LOGIN_PASSWORD, "")
        dpg.set_value(_VERIFICATION_CODE, "")
        dpg.configure_item(_VERIFICATION_GROUP, show=True)
        dpg.configure_item(_VERIFY_BUTTON, label="Confirm Login")
        self._set_login_status("Code sent", (100, 220, 100, 255))

    def _force_login_confirmation_required(self) -> None:
        dpg.configure_item(_VERIFY_BUTTON, label="Force Login")
        self._set_login_status(
            "Active session exists; confirm force login",
            (255, 170, 80, 255),
        )

    def _login_succeeded(self) -> None:
        self._saved_login_id = str(dpg.get_value(_LOGIN_ID)).strip()
        self._save_preferences()
        dpg.set_value(_LOGIN_PASSWORD, "")
        dpg.set_value(_VERIFICATION_CODE, "")
        dpg.configure_item(_VERIFICATION_GROUP, show=False)
        dpg.configure_item(_VERIFY_BUTTON, label="Confirm Login")
        self._headless_login = None
        self._force_login_required = False
        dpg.configure_item(_LOGIN_WINDOW, show=False)
        dpg.configure_item(_WINDOW, show=True)
        dpg.set_primary_window(_WINDOW, True)
        self._set_headless_status("Ready", (140, 140, 140, 255))

    def _show_login_view(self, status: str) -> None:
        dpg.configure_item(_WINDOW, show=False)
        dpg.configure_item(_LOGIN_WINDOW, show=True)
        dpg.set_primary_window(_LOGIN_WINDOW, True)
        self._set_login_status(status, (255, 190, 90, 255))

    def _on_logout(self) -> None:
        dpg.set_value(_REMEMBER_LOGIN, False)
        dpg.set_value(_LOGIN_PASSWORD, "")
        dpg.set_value(_VERIFICATION_CODE, "")
        dpg.configure_item(_VERIFICATION_GROUP, show=False)
        dpg.configure_item(_VERIFY_BUTTON, label="Confirm Login")
        clear_session()
        self._headless_login = None
        self._headless_user_id = ""
        self._headless_tokens = None
        self._force_login_required = False
        self.session.close()
        self._apply_disconnected()
        self._save_preferences()
        self._show_login_view("Signed out")

    @staticmethod
    def _on_open_link(sender=None, app_data=None, user_data=None) -> None:
        url = str(user_data or "").strip()
        if url:
            webbrowser.open(url, new=2)

    def _headless_launched(self, pid: int) -> None:
        self._set_headless_status(f"Launched (PID {pid})", (100, 220, 100, 255))

    def _remember_credentials(self, login, tokens, remember_login: bool) -> None:
        launch_credentials = login.resolve_launch_credentials(tokens)
        self._headless_user_id = launch_credentials["user_id"]
        self._headless_tokens = dict(launch_credentials)
        if remember_login:
            save_session({"email": login.email, **launch_credentials})
        else:
            clear_session()

    def _restore_remembered_login(self) -> None:
        def work() -> None:
            ui_queue.post(
                lambda: self._set_login_status(
                    "Restoring saved login...", (255, 190, 90, 255)
                )
            )
            try:
                saved = load_session()
                if saved is None:
                    raise ValueError("Saved login is unavailable")
                login = MoraiHeadlessLogin(
                    saved["email"], api_base_url=self.config.api_base_url
                )
                credentials = login.resolve_launch_credentials(
                    {
                        "access_token": saved["access_token"],
                        "refresh_token": saved["refresh_token"],
                    }
                )
            except (HeadlessLoginError, OSError, ValueError, KeyError):
                clear_session()
                ui_queue.post(self._remembered_login_expired)
                return

            self._headless_user_id = credentials["user_id"]
            self._headless_tokens = dict(credentials)
            ui_queue.post(
                lambda email=saved["email"]: self._remembered_login_succeeded(email)
            )

        self._start_task("Restore Login", work)

    def _remembered_login_succeeded(self, email: str) -> None:
        dpg.set_value(_LOGIN_ID, email)
        dpg.set_value(_REMEMBER_LOGIN, True)
        self._login_succeeded()

    def _remembered_login_expired(self) -> None:
        dpg.set_value(_REMEMBER_LOGIN, False)
        self._save_preferences()
        self._set_login_status(
            "Saved login expired. Sign in again.", (255, 170, 80, 255)
        )

    def _launch_with_tokens(self, user_id, tokens, simulator_path, headless):
        process = launch_simulator(
            simulator_path=simulator_path,
            user_id=user_id,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            product_uid=tokens["product_uid"],
            headless=headless,
        )
        self._headless_process = process
        return process

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
                f"step={response['step_index']} seconds={response['seconds']} "
                f"nanos={response['nanos']}"
            )
            ui_queue.post(lambda r=response: self._apply_time_status(r))

        self._start_task("Get Simulation Time", work)

    def _poll_simulation_time(self) -> None:
        now = time.monotonic()
        if (
            not self._suite_loaded
            or not self.session.is_connected
            or now < self._next_time_poll
        ):
            return
        with self._time_poll_lock:
            if self._time_poll_in_flight:
                return
            self._time_poll_in_flight = True
        self._next_time_poll = now + _SIMULATION_TIME_POLL_INTERVAL

        def work() -> None:
            try:
                response = self.session.get_time_status(log_send=False)
                ui_queue.post(lambda r=response: self._apply_simulation_time(r))
            except (DemoSessionError, OSError, ValueError):
                if not self.session.is_connected:
                    ui_queue.post(self._apply_disconnected)
            finally:
                with self._time_poll_lock:
                    self._time_poll_in_flight = False

        self._time_poll_worker = threading.Thread(
            target=work,
            name="SimulationControl-SimulationTime",
            daemon=True,
        )
        self._time_poll_worker.start()

    def _on_get_simulator_status(self) -> None:
        self._request_simulator_status(log_result=True)

    def _on_shutdown_simulator(self, sender=None, app_data=None, user_data=None) -> None:
        force = bool(user_data)

        def work() -> None:
            self.session.shutdown_simulator(force=force)
            mode = "force" if force else "graceful"
            self._log(f"Simulator {mode} shutdown accepted")
            self.session.close()
            ui_queue.post(lambda f=force: self._shutdown_succeeded(f))

        self._start_task("Shutdown Simulator", work)

    def _shutdown_succeeded(self, force: bool) -> None:
        self._headless_process = None
        self._apply_disconnected()
        mode = "Force shutdown" if force else "Shutdown"
        self._set_headless_status(f"{mode} complete", (100, 220, 100, 255))

    def _poll_simulator_status(self) -> None:
        now = time.monotonic()
        if now < self._next_simulator_status_poll:
            return
        self._next_simulator_status_poll = now + _SIMULATOR_STATUS_POLL_INTERVAL
        with self._task_lock:
            busy = self._task_running
        if self.session.is_connected and not busy:
            self._request_simulator_status(log_result=False)

    def _request_simulator_status(self, log_result: bool) -> None:
        def work() -> None:
            if log_result:
                ui_queue.post(
                    lambda: self._set_simulator_status(
                        "Querying...", (255, 190, 90, 255)
                    )
                )
            response = self.session.get_simulator_status()
            state = int(response["state"])
            label = proto.SIMULATOR_STATE_MAP.get(state, f"UNKNOWN({state})")
            if log_result:
                self._log(f"Simulator status: {label}")
            ui_queue.post(lambda s=state: self._apply_simulator_status(s))

        self._start_task("Get Simulator Status", work)

    def _on_control(self, command: str) -> None:
        def work() -> None:
            action = getattr(self.session, command)
            action("")
            self._log(f"Scenario {command} accepted")
            if command == "stop":
                ui_queue.post(self._reset_simulation_time)

        self._start_task(f"Scenario {command}", work)

    def _on_get_status(self) -> None:
        def work() -> None:
            scenario_status = self.session.get_scenario_status(publish=False)
            suite_status = self.session.get_active_suite_status()
            ui_queue.post(
                lambda scenario=scenario_status, suite=suite_status:
                    self._apply_scenario_snapshot(scenario, suite)
            )

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

        self._worker = threading.Thread(target=run, name=f"SimulationControl-{label}", daemon=True)
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
            error_codes = [
                int(code)
                for code in re.findall(r"(?:result|detail)=(\d+)", message)
                if int(code) != 0
            ]
            suffix = f" ({error_codes[0]})" if error_codes else ""
            self._set_suite_status(f"Failed{suffix}", (255, 120, 120, 255))
        if dpg.get_value(_SIMULATOR_STATUS) == "Querying...":
            self._set_simulator_status("Failed", (255, 120, 120, 255))
        if dpg.is_item_shown(_LOGIN_WINDOW):
            self._set_login_status(message, (255, 120, 120, 255))
        elif dpg.does_item_exist(_HEADLESS_STATUS):
            self._set_headless_status(message, (255, 120, 120, 255))

    def _apply_disconnected(self) -> None:
        self._suite_loaded = False
        self._simulator_state = None
        self._set_connection("Disconnected", (255, 120, 120, 255))
        self._set_simulator_status("-", (140, 140, 140, 255))
        dpg.set_value(_SIMULATION_TIME, "--:--.---")

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

    def _set_simulator_status(self, text: str, color) -> None:
        dpg.set_value(_SIMULATOR_STATUS, text)
        dpg.configure_item(_SIMULATOR_STATUS, color=color)

    def _apply_simulator_status(self, state: int) -> None:
        if (
            self._simulator_state == state
            and dpg.get_value(_SIMULATOR_STATUS) != "Querying..."
        ):
            return
        self._simulator_state = state
        label = proto.SIMULATOR_STATE_MAP.get(state, f"UNKNOWN({state})")
        color = (140, 140, 140, 255)
        if state == 3:
            color = (255, 190, 90, 255)
        elif state == 4:
            color = (100, 220, 100, 255)
        self._set_simulator_status(label, color)
        self._apply_button_state()

    def _set_headless_status(self, text: str, color) -> None:
        dpg.set_value(_HEADLESS_STATUS, text)
        dpg.configure_item(_HEADLESS_STATUS, color=color)

    def _set_login_status(self, text: str, color) -> None:
        dpg.set_value(_LOGIN_STATUS, text)
        dpg.configure_item(_LOGIN_STATUS, color=color)

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
        self._apply_simulation_time(response)

    def _apply_simulation_time(self, response) -> None:
        seconds = int(response["seconds"])
        nanos = int(response["nanos"])
        dpg.set_value(
            _SIMULATION_TIME,
            self._format_simulation_time(seconds, nanos),
        )

    def _reset_simulation_time(self) -> None:
        dpg.set_value(_SIMULATION_TIME, "0:00.000")
        self._next_time_poll = time.monotonic() + _SIMULATION_TIME_POLL_INTERVAL

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
        dpg.configure_item(_SIMULATOR_STATUS_GET, enabled=connected and not busy)
        dpg.configure_item(_SHUTDOWN_BUTTON, enabled=connected and not busy)
        dpg.configure_item(_FORCE_SHUTDOWN_BUTTON, enabled=connected and not busy)
        dpg.configure_item(_TIME_GET, enabled=connected and not busy)
        dpg.configure_item(_TIME_SET, enabled=connected and not busy)
        dpg.configure_item(_HEADLESS_START, enabled=not busy)
        dpg.configure_item(_LOGIN_BUTTON, enabled=not busy)
        dpg.configure_item(_LOGOUT_BUTTON, enabled=not busy)
        dpg.configure_item(_SIMULATOR_BROWSE, enabled=not busy)
        dpg.configure_item(_VERIFY_BUTTON, enabled=not busy)
        for tag in _CONTROL_BUTTONS:
            dpg.configure_item(tag, enabled=connected and not busy)

    def _on_scenario_status(self, status: ScenarioStatus) -> None:
        ui_queue.post(lambda s=status: self._apply_scenario_status(s))
        if status.state == 1:
            self._schedule_active_suite_refresh(
                previous_name="",
                max_attempts=1,
            )

    def _apply_scenario_status(self, status: ScenarioStatus) -> None:
        text = _STATE_NAMES.get(status.state, f"UNKNOWN({status.state})")
        if status.state == 4:
            if not self._completed_refresh_armed:
                self._completed_refresh_armed = True
                self._schedule_active_suite_refresh(
                    previous_name=self._active_scenario_name,
                    max_attempts=_SCENARIO_TRANSITION_MAX_ATTEMPTS,
                )
        else:
            self._completed_refresh_armed = False
        dpg.set_value(_SCENARIO_STATUS, text)
        dpg.configure_item(_SCENARIO_STATUS, color=(100, 220, 100, 255))
        self._log(f"Scenario control status: {text}")

    def _apply_active_suite_status(self, suite_status: Dict[str, object]) -> None:
        suite_name = str(suite_status.get("active_suite_name", "")).strip()
        scenario_name = str(suite_status.get("active_scenario_name", "")).strip()
        self._active_suite_name = suite_name
        self._active_scenario_name = scenario_name
        dpg.set_value(_ACTIVE_SUITE, suite_name or "-")
        dpg.configure_item(_ACTIVE_SUITE, color=(100, 220, 100, 255))
        dpg.set_value(_ACTIVE_SCENARIO, scenario_name or "-")
        dpg.configure_item(_ACTIVE_SCENARIO, color=(100, 220, 100, 255))
        dpg.set_value(_SCENARIO_PROGRESS, _format_scenario_progress(suite_status))
        dpg.configure_item(_SCENARIO_PROGRESS, color=(100, 220, 100, 255))
        self._log(
            f"Active suite status: suite={suite_name or '-'} "
            f"scenario={scenario_name or '-'}"
        )

    def _apply_scenario_snapshot(
        self,
        scenario_status: ScenarioStatus,
        suite_status: Dict[str, object],
    ) -> None:
        self._apply_scenario_status(scenario_status)
        self._apply_active_suite_status(suite_status)

    def _schedule_active_suite_refresh(
        self,
        previous_name: str,
        max_attempts: int,
        attempt: int = 0,
        generation: Optional[int] = None,
    ) -> None:
        refresh_generation = (
            self._scenario_refresh_generation
            if generation is None
            else generation
        )

        def work() -> None:
            time.sleep(_SCENARIO_TRANSITION_REFRESH_DELAY)
            if (
                self._closing
                or refresh_generation != self._scenario_refresh_generation
                or not self.session.is_connected
            ):
                return
            suite_status: Optional[Dict[str, object]] = None
            try:
                suite_status = self.session.get_active_suite_status()
            except (DemoSessionError, OSError, ValueError) as exc:
                self._log(f"Active suite status refresh failed: {exc}", "WARN")
            else:
                ui_queue.post(
                    lambda status=suite_status: self._apply_active_suite_status(status)
                )

            active_name = (
                str(suite_status.get("active_scenario_name", "")).strip()
                if suite_status is not None
                else ""
            )
            if active_name and active_name != previous_name:
                return
            if attempt + 1 < max_attempts:
                self._schedule_active_suite_refresh(
                    previous_name=previous_name,
                    max_attempts=max_attempts,
                    attempt=attempt + 1,
                    generation=refresh_generation,
                )
                return

        self._scenario_refresh_worker = threading.Thread(
            target=work,
            name="SimulationControl-ActiveScenario",
            daemon=True,
        )
        self._scenario_refresh_worker.start()

    @staticmethod
    def _format_simulation_time(seconds: int, nanos: int) -> str:
        total_milliseconds = max(0, seconds * 1000 + nanos // 1_000_000)
        hours, remainder = divmod(total_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        whole_seconds, milliseconds = divmod(remainder, 1000)
        if hours:
            return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"
        return f"{minutes}:{whole_seconds:02d}.{milliseconds:03d}"

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
    _bind_unicode_font()
    gui = SimulationControlGui(config, args.config)
    try:
        gui.build()
        dpg.create_viewport(
            title=_SIMULATION_CONTROL_TITLE,
            width=config.window_width,
            height=config.window_height,
            min_width=MIN_WINDOW_WIDTH,
            min_height=MIN_WINDOW_HEIGHT,
            resizable=True,
        )
        dpg.setup_dearpygui()
        dpg.set_primary_window(_LOGIN_WINDOW, True)
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
