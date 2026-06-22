from __future__ import annotations
from __future__ import annotations

import sys
import transport.object_enums as object_enums
import transport.protocol_defs as proto
from utils import trajectory_samples


# ============================================================
# Low-level line reader for Windows and Unix terminals
# ============================================================

def _read_line(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()

    if sys.platform.startswith("win"):
        import msvcrt
        buf = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                break
            elif ch == "\x08":          # Backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            elif ch == "\x03":          # Ctrl+C
                raise KeyboardInterrupt
            else:
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
        return "".join(buf).strip()
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            termios.tcflow(fd, termios.TCIFLUSH)
            line = sys.stdin.readline()
        finally:
            tty.setcbreak(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return line.strip()


# ============================================================
# Typed input helpers
# ============================================================

def _ask_str(prompt: str, default: str) -> str:
    raw = _read_line(f"  {prompt} [{default}]: ")
    return raw if raw else default


def _ask_int(prompt: str, default: int) -> int:
    raw = _read_line(f"  {prompt} [{default}]: ")
    return int(raw) if raw else default


def _ask_float(prompt: str, default: float) -> float:
    raw = _read_line(f"  {prompt} [{default}]: ")
    return float(raw) if raw else default


def _ask_select(prompt: str, options: dict[int, str], default: int) -> int:
    """Select an integer option from a small menu."""
    print(f"\n  {prompt}")
    for k, v in options.items():
        print(f"    {k}: {v}")
    while True:
        raw = _read_line(f"  select [{default}]: ")
        if not raw:
            return default
        try:
            val = int(raw)
            if val in options:
                return val
        except ValueError:
            pass
        print("  invalid input. try again.")


# ============================================================
# Prompt functions
# ============================================================

def prompt_create_object() -> dict:
    print("\n-- Create Object ------------------------------")
    return {
        "entity_type": _ask_select(
            "entity_type",
            object_enums.enum_options(object_enums.ENTITY_TYPE_ITEMS),
            1,
        ),
        "pos_x": _ask_float("pos x", 267.5667),
        "pos_y": _ask_float("pos y", -299.4991),
        "pos_z": _ask_float("pos z", 0.0522),
        "rot_x": _ask_float("rot x", -0.18),
        "rot_y": _ask_float("rot y", -179.982),
        "rot_z": _ask_float("rot z", -0.51),
        "driving_mode": _ask_select(
            "driving_mode",
            object_enums.enum_options(object_enums.VEHICLE_DRIVING_MODE_ITEMS),
            2,
        ),
        "ground_vehicle_model": _ask_select(
            "ground_vehicle_model",
            object_enums.enum_options(object_enums.GROUND_VEHICLE_MODEL_ITEMS),
            12,
        ),
    }


def prompt_set_simulator_mode() -> dict:
    print("\n-- Set Simulator Mode -------------------------")
    mode = _ask_select(
        "mode",
        {
            proto.SIMULATOR_MODE_SCENARIO: "SCENARIO",
            proto.SIMULATOR_MODE_REPLAY: "REPLAY",
            proto.SIMULATOR_MODE_TRAFFIC: "TRAFFIC",
            proto.SIMULATOR_MODE_MONITORING: "MONITORING",
            proto.SIMULATOR_MODE_COMPETITION: "COMPETITION",
        },
        proto.SIMULATOR_MODE_SCENARIO,
    )
    return {"mode": mode}


def prompt_load_map() -> dict:
    print("\n-- Load Map -----------------------------------")
    options = {idx + 1: name for idx, name in enumerate(proto.SIMULATOR_MAP_NAMES)}
    selected = _ask_select("map", options, 1)
    return {"map_name": options[selected]}


def prompt_load_traffic_scenario() -> dict:
    print("\n-- Load Traffic Scenario ----------------------")
    return {
        "file_path": _ask_str("file path", "C:/MORAI/traffic/example.anmroutes"),
    }


def prompt_traffic_generate() -> dict:
    print("\n-- Traffic Generate ---------------------------")
    return {
        "autonomous": _ask_int("autonomous", 1),
        "lc_rate": _ask_int("lc_rate", 0),
    }


def prompt_manual_control_by_id() -> dict:
    print("\n-- Manual Control By Id -----------------------")
    return {
        "entity_id": _ask_str("entity id", "Car_1"),
        "throttle": _ask_float("throttle", 0.4),
        "brake": _ask_float("brake", 0.0),
        "steer_angle": _ask_float("steer angle", 0.0),
    }


def prompt_delete_object() -> dict:
    print("\n-- Delete Object ------------------------------")
    return {
        "entity_id": _ask_str("entity id", "Car_1"),
    }


def prompt_set_trajectory() -> dict:
    print("\n-- Set Trajectory -----------------------------")
    sample_options = {
        idx: name
        for idx, (name, _) in enumerate(trajectory_samples.TRAJECTORY_SAMPLES, start=1)
    }
    sample_index = _ask_select("sample", sample_options, 1)
    sample_name = sample_options[sample_index]
    points = list(trajectory_samples.get_sample(sample_name))
    return {
        "entity_id": _ask_str("entity id", "Car_1"),
        "follow_mode": _ask_select(
            "follow_mode",
            object_enums.enum_options(trajectory_samples.TRAJECTORY_FOLLOW_MODE_ITEMS),
            2,
        ),
        "trajectory_name": _ask_str("trajectory name", "Route_1"),
        "points": points,
    }


def prompt_transform_control_by_id() -> dict:
    print("\n-- Transform Control By Id --------------------")
    return {
        "entity_id": _ask_str("entity id", "Car_2"),
        "pos_x": _ask_float("pos x", 0.0),
        "pos_y": _ask_float("pos y", 0.0),
        "pos_z": _ask_float("pos z", 0.0),
        "rot_x": _ask_float("rot x", 0.0),
        "rot_y": _ask_float("rot y", 0.0),
        "rot_z": _ask_float("rot z", 0.0),
        "steer_angle": _ask_float("steer angle", 0.0),
    }


def prompt_transform_control() -> dict:
    print("\n-- Transform Control --------------------------")
    return {
        "pos_x": _ask_float("pos x", 0.0),
        "pos_y": _ask_float("pos y", 0.0),
        "pos_z": _ask_float("pos z", 0.0),
        "rot_x": _ask_float("rot x", 0.0),
        "rot_y": _ask_float("rot y", 0.0),
        "rot_z": _ask_float("rot z", 0.0),
        "steer_angle": _ask_float("steer angle", 0.0),
    }


_SCENARIO_COMMANDS = {
    1: "PLAY",
    2: "PAUSE",
    3: "STOP",
    4: "PREV",
    5: "NEXT",
}


# ============================================================
# Scenario list buffer
# Updated by ActiveSuiteStatus handling in the receiver thread.
# ============================================================

_scenario_list_cache: list[str] = []


def update_scenario_list(scenario_list: list[str]) -> None:
    """Update the cached scenario list from ActiveSuiteStatus."""
    global _scenario_list_cache
    _scenario_list_cache = list(scenario_list)


def prompt_scenario_control() -> dict:
    """
    Returns:
        {"command": int, "scenario_name": str}

    For PLAY, a scenario can be selected from the cached suite list.
    Other commands use an empty scenario_name.
    """
    print("\n-- Scenario Control ---------------------------")
    command = _ask_select("Scenario Command:", _SCENARIO_COMMANDS, default=1)
    print(f"  selected: {_SCENARIO_COMMANDS[command]} ({command})")

    scenario_name = ""

    if command == 1:  # SCENARIO_STATE_PLAYING
        if _scenario_list_cache:
            print("\n-- Select Target Scenario (Enter to skip) -----")
            for i, name in enumerate(_scenario_list_cache):
                print(f"  [{i}] {name}")
            raw = _read_line("  index: ")
            if raw.isdigit():
                idx = int(raw)
                if 0 <= idx < len(_scenario_list_cache):
                    scenario_name = _scenario_list_cache[idx]
                    print(f"  target: {scenario_name!r}")
                else:
                    print("  [WARN] index out of range; sending without target scenario")
        else:
            print("  [INFO] scenario cache is empty; query ActiveSuiteStatus first with [c]")

    return {"command": command, "scenario_name": scenario_name}
