from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict

import transport.protocol_defs as proto
from demo.headless_launcher import DEFAULT_API_BASE_URL


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "simulation_control.json"


@dataclass(frozen=True)
class SimulationControlConfig:
    suite_path: str
    scenario_name: str
    host: str
    port: int
    connect_timeout: float
    request_timeout: float
    load_timeout: float
    time_mode: str
    target_fps: int
    physics_delta_time: int
    rtf: int
    user_control: bool
    simulator_path: str
    api_base_url: str
    login_id: str
    remember_login: bool


def load_config(config_path: str) -> SimulationControlConfig:
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        _create_default_config(path)
        print(f"[INFO] Created default simulation control config: {path}")

    try:
        with path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to read configuration file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be a JSON object")

    server = _object_value(data, "server")
    timeouts = _object_value(data, "timeouts")
    simulation_time = _object_value(data, "simulation_time")
    suite_value = str(data.get("suite_path", "")).strip()
    suite_path = Path(suite_value).expanduser() if suite_value else None
    if suite_path is not None and not suite_path.is_absolute():
        suite_path = path.parent / suite_path

    config = SimulationControlConfig(
        suite_path=str(suite_path.resolve()) if suite_path is not None else "",
        scenario_name=str(data.get("scenario_name", "")).strip(),
        host=str(server.get("host", proto.TCP_SERVER_IP)).strip(),
        port=int(server.get("port", proto.TCP_SERVER_PORT)),
        connect_timeout=float(timeouts.get("connect", 5.0)),
        request_timeout=float(timeouts.get("request", 10.0)),
        load_timeout=float(timeouts.get("load_suite", 120.0)),
        time_mode=str(simulation_time.get("mode", "Fixed")),
        target_fps=int(simulation_time.get("target_fps", 60)),
        physics_delta_time=int(simulation_time.get("physics_delta_time", 10)),
        rtf=int(simulation_time.get("rtf", 1)),
        user_control=bool(simulation_time.get("user_control", False)),
        simulator_path=str(data.get("simulator_path", "")).strip(),
        api_base_url=str(data.get("api_base_url", DEFAULT_API_BASE_URL)).strip(),
        login_id=str(data.get("login_id", "")).strip(),
        remember_login=bool(data.get("remember_login", False)),
    )
    if not config.host:
        raise ValueError("Configuration field 'server.host' must not be empty")
    if not config.api_base_url.startswith(("http://", "https://")):
        raise ValueError("Configuration field 'api_base_url' must be an HTTP(S) URL")
    if not 1 <= config.port <= 65535:
        raise ValueError("Configuration field 'server.port' must be between 1 and 65535")
    if min(config.connect_timeout, config.request_timeout, config.load_timeout) <= 0:
        raise ValueError("All configuration timeout values must be greater than zero")
    if config.time_mode not in ("Variable", "Fixed"):
        raise ValueError("Configuration field 'simulation_time.mode' must be Variable or Fixed")
    if not 10 <= config.target_fps <= 200:
        raise ValueError("Configuration field 'simulation_time.target_fps' must be between 10 and 200")
    if not 5 <= config.physics_delta_time <= 100:
        raise ValueError("Configuration field 'simulation_time.physics_delta_time' must be between 5 and 100")
    if config.rtf not in (1, 2):
        raise ValueError("Configuration field 'simulation_time.rtf' must be 1 or 2")
    return config


def _create_default_config(path: Path) -> None:
    data = {
        "suite_path": "",
        "scenario_name": "",
        "simulator_path": "",
        "api_base_url": DEFAULT_API_BASE_URL,
        "login_id": "",
        "remember_login": False,
        "server": {
            "host": proto.TCP_SERVER_IP,
            "port": proto.TCP_SERVER_PORT,
        },
        "timeouts": {
            "connect": 5,
            "request": 10,
            "load_suite": 120,
        },
        "simulation_time": {
            "mode": "Fixed",
            "target_fps": 60,
            "physics_delta_time": 10,
            "rtf": 1,
            "user_control": False,
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2, ensure_ascii=False)
            config_file.write("\n")
    except OSError as exc:
        raise ValueError(f"Failed to create configuration file {path}: {exc}") from exc


def save_config(config_path: str, config: SimulationControlConfig) -> None:
    path = Path(config_path).expanduser().resolve()
    data = {
        "suite_path": config.suite_path,
        "scenario_name": config.scenario_name,
        "simulator_path": config.simulator_path,
        "api_base_url": config.api_base_url,
        "login_id": config.login_id,
        "remember_login": config.remember_login,
        "server": {"host": config.host, "port": config.port},
        "timeouts": {
            "connect": config.connect_timeout,
            "request": config.request_timeout,
            "load_suite": config.load_timeout,
        },
        "simulation_time": {
            "mode": config.time_mode,
            "target_fps": config.target_fps,
            "physics_delta_time": config.physics_delta_time,
            "rtf": config.rtf,
            "user_control": config.user_control,
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2, ensure_ascii=False)
            config_file.write("\n")
    except OSError as exc:
        raise ValueError(f"Failed to save configuration file {path}: {exc}") from exc


def _object_value(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Configuration field '{key}' must be a JSON object")
    return value
