from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class FieldSpec:
    name: str
    field_type: str
    description: str = ""


@dataclass(frozen=True)
class VariantSpec:
    name: str
    selector_field: str
    selector_value: int
    summary: str = ""
    fields: tuple[FieldSpec, ...] = ()


@dataclass(frozen=True)
class MessageSpec:
    msg_type: int
    name: str
    direction: str
    summary: str
    fields: tuple[FieldSpec, ...] = ()
    variants: tuple[VariantSpec, ...] = ()
    repeat_fields: tuple[FieldSpec, ...] = ()
    handler: str = ""
    parser: str = ""
    notes: tuple[str, ...] = ()

    @property
    def has_payload(self) -> bool:
        return bool(self.fields)


TYPE_LABELS: Dict[str, str] = {
    "uint8": "uint8",
    "int32": "int32",
    "uint32": "uint32",
    "int64": "int64",
    "uint64": "uint64",
    "float32": "float32",
    "float64": "float64",
    "string_u32": "uint32 length + utf-8 bytes",
    "string_raw": "utf-8 bytes",
}

TYPE_SIZES: Dict[str, Optional[int]] = {
    "uint8": 1,
    "int32": 4,
    "uint32": 4,
    "int64": 8,
    "uint64": 8,
    "float32": 4,
    "float64": 8,
    "string_u32": None,
    "string_raw": None,
}

STRUCT_FORMAT_CHARS: Dict[str, str] = {
    "uint8": "B",
    "int32": "i",
    "uint32": "I",
    "int64": "q",
    "uint64": "Q",
    "float32": "f",
    "float64": "d",
}


MESSAGES: tuple[MessageSpec, ...] = (
    MessageSpec(
        msg_type=0x1001,
        name="GetSimulatorStatus",
        direction="request",
        summary="Query the current simulator frontend lifecycle state.",
        handler="tcp.send_get_simulator_status()",
        notes=("No payload.",),
    ),
    MessageSpec(
        msg_type=0x1002,
        name="GetSimulatorMode",
        direction="request",
        summary="Query the current simulator functional mode.",
        handler="tcp.send_get_simulator_mode()",
        notes=("No payload.",),
    ),
    MessageSpec(
        msg_type=0x1003,
        name="SetSimulatorMode",
        direction="request",
        summary="Request a transition to the specified simulator functional mode.",
        handler="tcp.send_set_simulator_mode()",
        fields=(
            FieldSpec("mode", "uint32", "1=SCENARIO, 2=REPLAY, 3=TRAFFIC, 4=MONITORING, 5=COMPETITION"),
        ),
    ),
    MessageSpec(
        msg_type=0x1004,
        name="LoadMap",
        direction="request",
        summary="Request the simulator to load the specified map by name.",
        handler="tcp.send_load_map()",
        fields=(
            FieldSpec("map_name", "string_u32", "Map name string to look up in the map registry"),
        ),
        notes=("Returns InvalidParam if the map name is not found in the registry.",),
    ),
    MessageSpec(
        msg_type=0x1005,
        name="ShutdownSimulator",
        direction="request",
        summary="Request graceful or forced simulator shutdown.",
        handler="tcp.send_shutdown_simulator()",
        fields=(
            FieldSpec("b_force", "uint8", "0=graceful shutdown, 1=forced shutdown"),
        ),
    ),
    MessageSpec(
        msg_type=0x1101,
        name="GetSimulationTimeStatus",
        direction="request",
        summary="Query current simulation time mode and timing state.",
        handler="tcp.send_get_status()",
        notes=("No payload.",),
    ),
    MessageSpec(
        msg_type=0x1102,
        name="SetSimulationTimeModeCommand",
        direction="request",
        summary="Configure how the simulator advances simulation time.",
        handler="tcp.send_simulation_time_mode_command()",
        fields=(
            FieldSpec(
                "mode",
                "int32",
                "1=Variable (simulator-managed timing), 2=Fixed (fixed physics interval)",
            ),
            FieldSpec("target_fps", "int32", "Target frame rate, 10~200 FPS"),
            FieldSpec(
                "physics_delta_time",
                "int32",
                "Physics update interval, 5~100 ms",
            ),
            FieldSpec(
                "rtf",
                "int32",
                "Fixed only: 1=Real-Time, 2=Unlimited. Variable mode must send 0",
            ),
            FieldSpec(
                "user_control",
                "int32",
                "Fixed only: 0=do not wait for external vehicle control, "
                "1=wait for external vehicle-control input over TCP or UDP. "
                "Variable mode must send 0",
            ),
        ),
        notes=(
            "With user_control=1, the simulator can remain paused until an external "
            "vehicle-control input is received over TCP or UDP.",
            "An external controller that waits for its first vehicle-state message "
            "before sending control input can deadlock with user_control=1. Send an "
            "initial control input or otherwise break the startup dependency.",
        ),
    ),
    MessageSpec(
        msg_type=0x1201,
        name="FixedStep",
        direction="request",
        summary="Advance the simulator by a fixed number of steps.",
        handler="tcp.send_fixed_step()",
        fields=(FieldSpec("step_count", "uint32", "Number of simulation steps to execute"),),
    ),
    MessageSpec(
        msg_type=0x1202,
        name="SaveData",
        direction="request",
        summary="Trigger simulator-side data capture.",
        handler="tcp.send_save_data()",
        notes=("No payload.",),
    ),
    MessageSpec(
        msg_type=0x1301,
        name="CreateObject",
        direction="request",
        summary="Create an entity with initial transform and vehicle configuration.",
        handler="tcp.send_create_object()",
        fields=(
            FieldSpec("entity_type", "int32", "EntityType enum value"),
            FieldSpec("pos_x", "float32"),
            FieldSpec("pos_y", "float32"),
            FieldSpec("pos_z", "float32"),
            FieldSpec("rot_x", "float32"),
            FieldSpec("rot_y", "float32"),
            FieldSpec("rot_z", "float32"),
            FieldSpec("driving_mode", "int32", "VehicleDrivingMode enum value"),
            FieldSpec("ground_vehicle_model", "int32", "GroundVehicleModel enum value"),
        ),
    ),
    MessageSpec(
        msg_type=0x1302,
        name="ManualControlById",
        direction="request",
        summary="Send manual throttle, brake, and steering-wheel angle to a target entity.",
        handler="tcp.send_manual_control_by_id()",
        fields=(
            FieldSpec("entity_id", "string_u32", "Control target Entity ID"),
            FieldSpec("throttle", "float64", "Throttle input value"),
            FieldSpec("brake", "float64", "Brake input value"),
            FieldSpec("steer_angle", "float64", "Steering wheel angle value"),
        ),
    ),
    MessageSpec(
        msg_type=0x1303,
        name="TransformControlById",
        direction="request",
        summary="Set target transform, steer angle, and speed for a target entity.",
        handler="tcp.send_transform_control_by_id()",
        fields=(
            FieldSpec("entity_id", "string_u32"),
            FieldSpec("pos_x", "float32"),
            FieldSpec("pos_y", "float32"),
            FieldSpec("pos_z", "float32"),
            FieldSpec("rot_x", "float32"),
            FieldSpec("rot_y", "float32"),
            FieldSpec("rot_z", "float32"),
            FieldSpec("steer_angle", "float32"),
            FieldSpec("speed", "float64", "Currently derived from Vehicle Info local velocity in m/s"),
        ),
    ),
    MessageSpec(
        msg_type=0x1304,
        name="SetTrajectory",
        direction="request",
        summary="Send a named trajectory and follow mode to a target entity.",
        handler="tcp.send_set_trajectory()",
        fields=(
            FieldSpec("entity_id", "string_u32"),
            FieldSpec("follow_mode", "int32", "1 = POSITION, 2 = FOLLOW"),
            FieldSpec("trajectory_name", "string_u32"),
            FieldSpec("point_count", "uint32"),
        ),
        repeat_fields=(
            FieldSpec("points[].x", "float64"),
            FieldSpec("points[].y", "float64"),
            FieldSpec("points[].z", "float64"),
            FieldSpec("points[].time", "float64"),
        ),
        notes=("Each trajectory point is serialized as four float64 values.",),
    ),
    MessageSpec(
        msg_type=0x1305,
        name="DeleteObject",
        direction="request",
        summary="Delete a target entity by identifier.",
        handler="tcp.send_delete_object()",
        fields=(FieldSpec("entity_id", "string_raw", "UTF-8 entity identifier. No length prefix."),),
        notes=("Header payload_size is the UTF-8 byte length of entity_id.",),
    ),
    MessageSpec(
        msg_type=0x1306,
        name="GetVehicleInfo",
        direction="request",
        summary="Query the current state of one ground vehicle entity by ID.",
        handler="tcp.send_get_vehicle_info()",
        fields=(FieldSpec("entity_id", "string_u32", "Target ground vehicle Entity ID"),),
        notes=("Empty entity IDs are rejected client-side.",),
    ),
    MessageSpec(
        msg_type=0x1401,
        name="ActiveSuiteStatus",
        direction="request",
        summary="Query the active suite and scenario list.",
        handler="tcp.send_active_suite_status()",
        notes=("No payload.",),
    ),
    MessageSpec(
        msg_type=0x1402,
        name="LoadSuite",
        direction="request",
        summary="Load a MORAI suite from a path string.",
        handler="tcp.send_load_suite()",
        fields=(FieldSpec("suite_path", "string_u32"),),
    ),
    MessageSpec(
        msg_type=0x1504,
        name="ScenarioStatus",
        direction="request",
        summary="Query current scenario execution state.",
        handler="tcp.send_scenario_status()",
        notes=("No payload.",),
    ),
    MessageSpec(
        msg_type=0x1505,
        name="ScenarioControl",
        direction="request",
        summary="Control scenario playback state and optional target scenario name.",
        handler="tcp.send_scenario_control()",
        fields=(
            FieldSpec("command", "uint32", "1=Play, 2=Pause, 3=Stop, 4=Prev, 5=Next"),
            FieldSpec("scenario_name", "string_u32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1601,
        name="LoadTrafficScenario",
        direction="request",
        summary="Load a traffic scenario from an .anmroutes file path.",
        handler="tcp.send_load_traffic_scenario()",
        fields=(FieldSpec("file_path", "string_u32", ".anmroutes file path encoded as UTF-8"),),
    ),
    MessageSpec(
        msg_type=0x1602,
        name="TrafficGenerate",
        direction="request",
        summary="Generate traffic using the loaded traffic scenario.",
        handler="tcp.send_traffic_generate()",
        fields=(
            FieldSpec("autonomous", "int32", "Autonomous driving flag"),
            FieldSpec("lc_rate", "int32", "Lane-change rate"),
        ),
    ),
)


RESPONSE_MESSAGES: tuple[MessageSpec, ...] = (
    MessageSpec(
        msg_type=0x1001,
        name="GetSimulatorStatus",
        direction="response",
        summary="Return the current simulator frontend lifecycle state.",
        parser="tcp.parse_get_simulator_status_payload()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
            FieldSpec("state", "uint32", "0=UNSPECIFIED, 1=PRE_LOGIN, 2=HOME, 3=LOADING, 4=READY"),
        ),
    ),
    MessageSpec(
        msg_type=0x1002,
        name="GetSimulatorMode",
        direction="response",
        summary="Return result code and the current simulator mode.",
        parser="tcp.parse_get_simulator_mode_payload()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
            FieldSpec("mode", "uint32", "0=UNSPECIFIED, 1=SCENARIO, 2=REPLAY, 3=TRAFFIC, 4=MONITORING, 5=COMPETITION"),
        ),
    ),
    MessageSpec(
        msg_type=0x1003,
        name="SetSimulatorMode",
        direction="response",
        summary="Return result code for a set-simulator-mode request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1004,
        name="LoadMap",
        direction="response",
        summary="Return result code for a load-map request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1005,
        name="ShutdownSimulator",
        direction="response",
        summary="Return result code before the simulator exits.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1101,
        name="GetSimulationTimeStatus",
        direction="response",
        summary="Return result code plus current simulation time mode and simulation clock state.",
        parser="tcp.parse_get_status_payload()",
        fields=(
            FieldSpec("result_code", "uint32", "0=success, nonzero=failure"),
            FieldSpec("detail_code", "uint32", "Additional result detail"),
            FieldSpec(
                "mode",
                "uint32",
                "1=Variable (simulator-managed timing), 2=Fixed (fixed physics interval)",
            ),
            FieldSpec("target_fps", "int32", "Configured target frame rate"),
            FieldSpec(
                "physics_delta_time",
                "int32",
                "Configured physics update interval in ms",
            ),
            FieldSpec(
                "rtf",
                "int32",
                "Fixed only: 1=Real-Time, 2=Unlimited. Variable mode returns 0",
            ),
            FieldSpec(
                "user_control",
                "int32",
                "Fixed only: 0=not waiting for external control, "
                "1=waiting for external vehicle control. Variable mode returns 0",
            ),
            FieldSpec("step_index", "uint64", "Accumulated step count"),
            FieldSpec("seconds", "int64", "Simulation time seconds"),
            FieldSpec("nanos", "int32", "Simulation time nanoseconds remainder"),
        ),
    ),
    MessageSpec(
        msg_type=0x1102,
        name="SetSimulationTimeModeCommand",
        direction="response",
        summary="Return result code and the applied simulation time settings.",
        parser="tcp.parse_set_simulation_time_mode_payload()",
        fields=(
            FieldSpec("result_code", "uint32", "0=success, nonzero=failure"),
            FieldSpec("detail_code", "uint32", "Additional result detail"),
            FieldSpec(
                "mode",
                "uint32",
                "Applied mode: 1=Variable, 2=Fixed",
            ),
            FieldSpec(
                "fixed_delta",
                "float32",
                "Applied fixed time-step value reported by the simulator",
            ),
            FieldSpec(
                "simulation_speed",
                "float32",
                "Applied simulation-speed value reported by the simulator",
            ),
        ),
    ),
    MessageSpec(
        msg_type=0x1201,
        name="FixedStep",
        direction="response",
        summary="Return result code for a fixed-step request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1202,
        name="SaveData",
        direction="response",
        summary="Return result code for a save-data request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1301,
        name="CreateObject",
        direction="response",
        summary="Return result code and the created object identifier.",
        parser="tcp.parse_create_object_payload()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
            FieldSpec("object_id", "string_u32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1302,
        name="ManualControlById",
        direction="response",
        summary="Return result code for a manual-control request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1303,
        name="TransformControlById",
        direction="response",
        summary="Return result code for a transform-control request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1304,
        name="SetTrajectory",
        direction="response",
        summary="Return result code for a set-trajectory request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1305,
        name="DeleteObject",
        direction="response",
        summary="Return result code for a delete-object request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1306,
        name="GetVehicleInfo",
        direction="response",
        summary="Return the current transform, motion, and control state of one ground vehicle.",
        parser="tcp.parse_get_vehicle_info_payload()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
            FieldSpec("seconds", "int64", "Simulation timestamp seconds"),
            FieldSpec("nanos", "int32", "Simulation timestamp nanoseconds remainder"),
            FieldSpec("entity_id", "string_u32", "Echoed ground vehicle Entity ID"),
            FieldSpec("pos_x", "float32"),
            FieldSpec("pos_y", "float32"),
            FieldSpec("pos_z", "float32"),
            FieldSpec("rot_x", "float32"),
            FieldSpec("rot_y", "float32"),
            FieldSpec("rot_z", "float32"),
            FieldSpec("vel_x", "float32"),
            FieldSpec("vel_y", "float32"),
            FieldSpec("vel_z", "float32"),
            FieldSpec("accel_x", "float32"),
            FieldSpec("accel_y", "float32"),
            FieldSpec("accel_z", "float32"),
            FieldSpec("ang_vel_x", "float32"),
            FieldSpec("ang_vel_y", "float32"),
            FieldSpec("ang_vel_z", "float32"),
            FieldSpec("throttle", "float32"),
            FieldSpec("brake", "float32"),
            FieldSpec("steer_angle", "float32"),
        ),
        notes=(
            "Failure responses contain only result_code and detail_code (8 bytes).",
            "Success responses contain 96 bytes plus the UTF-8 entity ID byte length.",
        ),
    ),
    MessageSpec(
        msg_type=0x1401,
        name="ActiveSuiteStatus",
        direction="response",
        summary="Return the active suite, active scenario, and scenario name list.",
        parser="tcp.parse_active_suite_status_payload()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
            FieldSpec("active_suite_name", "string_u32"),
            FieldSpec("active_scenario_name", "string_u32"),
            FieldSpec("scenario_list_size", "uint32"),
        ),
        repeat_fields=(FieldSpec("scenario_list[].name", "string_u32"),),
    ),
    MessageSpec(
        msg_type=0x1402,
        name="LoadSuite",
        direction="response",
        summary="Return result code for a load-suite request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1504,
        name="ScenarioStatus",
        direction="response",
        summary="Return result code, current scenario execution state, and scenario name.",
        parser="tcp.parse_scenario_status_payload()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
            FieldSpec("state", "uint32", "1=Play, 2=Pause, 3=Stop, 4=Completed"),
            FieldSpec("name", "string_u32", "Current scenario name"),
        ),
        notes=(
            "Parser currently accepts both the new payload (result_code/detail_code/state/name) and the legacy 12-byte payload (result_code/detail_code/state).",
            "When the legacy payload is received, `name` is returned as an empty string.",
        ),
    ),
    MessageSpec(
        msg_type=0x1505,
        name="ScenarioControl",
        direction="response",
        summary="Return result code for a scenario-control request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1601,
        name="LoadTrafficScenario",
        direction="response",
        summary="Return result code for a load-traffic-scenario request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
    MessageSpec(
        msg_type=0x1602,
        name="TrafficGenerate",
        direction="response",
        summary="Return result code for a traffic-generate request.",
        parser="tcp.parse_result_code()",
        fields=(
            FieldSpec("result_code", "uint32"),
            FieldSpec("detail_code", "uint32"),
        ),
    ),
)


NOTIFICATION_MESSAGES: tuple[MessageSpec, ...] = (
    MessageSpec(
        msg_type=0x1504,
        name="ScenarioStatus",
        direction="notification",
        summary="Push the current scenario execution state and scenario name without a preceding request.",
        parser="tcp.parse_scenario_status_notification_payload()",
        fields=(
            FieldSpec("state", "uint32", "Protobuf enum value. 1=Play, 2=Pause, 3=Stop, 4=Completed"),
            FieldSpec("name", "string_u32", "Current scenario name"),
        ),
        notes=(
            "Header uses msg_class = 0x03 (NOTI).",
            "Payload is assumed to be protobuf-encoded scenario status data, not the raw request/response layout.",
            "Current parser expects field #1 = varint state, field #2 = length-delimited utf-8 scenario name.",
        ),
    ),
    MessageSpec(
        msg_type=0x1001,
        name="GetSimulatorStatus",
        direction="notification",
        summary="Push the current simulator frontend lifecycle state without a preceding request.",
        parser="tcp.parse_get_simulator_status_notification_payload()",
        fields=(
            FieldSpec("state", "uint32", "Protobuf enum value. 0=UNSPECIFIED, 1=PRE_LOGIN, 2=HOME, 3=LOADING, 4=READY"),
        ),
        notes=(
            "Header uses msg_class = 0x03 (NOTI).",
            "Payload is protobuf-encoded datamodel::SimulatorStatus, not the raw 12-byte response layout.",
            "Current parser expects minimal wire format: 0x08 <varint(state)>.",
        ),
    ),
)


def iter_messages() -> Iterable[MessageSpec]:
    return MESSAGES


def iter_response_messages() -> Iterable[MessageSpec]:
    return RESPONSE_MESSAGES


def iter_notification_messages() -> Iterable[MessageSpec]:
    return NOTIFICATION_MESSAGES


def get_message(msg_type: int) -> MessageSpec:
    for message in MESSAGES:
        if message.msg_type == msg_type:
            return message
    raise KeyError(msg_type)


def get_response_message(msg_type: int) -> MessageSpec:
    for message in RESPONSE_MESSAGES:
        if message.msg_type == msg_type:
            return message
    raise KeyError(msg_type)


def get_static_payload_size(message: MessageSpec) -> Optional[int]:
    if message.variants:
        sizes = []
        for variant in message.variants:
            total = 0
            for field in variant.fields:
                size = TYPE_SIZES[field.field_type]
                if size is None:
                    return None
                total += size
            sizes.append(total)
        return sizes[0] if sizes and all(size == sizes[0] for size in sizes) else None
    total = 0
    for field in message.fields:
        size = TYPE_SIZES[field.field_type]
        if size is None:
            return None
        total += size
    return total


def get_min_payload_size(message: MessageSpec) -> int:
    if message.variants:
        totals = []
        for variant in message.variants:
            total = 0
            for field in variant.fields:
                size = TYPE_SIZES[field.field_type]
                if field.field_type == "string_raw":
                    total += 0
                else:
                    total += 4 if size is None else size
            totals.append(total)
        return min(totals) if totals else 0
    total = 0
    for field in message.fields:
        size = TYPE_SIZES[field.field_type]
        if field.field_type == "string_raw":
            total += 0
        elif size is None:
            total += 4
        else:
            total += size
    return total


def _string_length_label(index: int, total: int) -> str:
    return "N" if total == 1 else f"N{index}"


def _format_payload_size_for_fields(fields: Sequence[FieldSpec]) -> str:
    string_fields = [field for field in fields if field.field_type in ("string_u32", "string_raw")]
    string_count = len(string_fields)
    string_index = 0
    fixed_total = 0
    terms: List[str] = []
    notes: List[str] = []

    def flush_fixed() -> None:
        nonlocal fixed_total
        if fixed_total:
            terms.append(str(fixed_total))
            fixed_total = 0

    for field in fields:
        size = TYPE_SIZES[field.field_type]
        if field.field_type == "string_u32":
            flush_fixed()
            string_index += 1
            length_label = _string_length_label(string_index, string_count)
            terms.extend(("4", length_label))
            notes.append(f"{length_label} = {field.name} UTF-8 byte length")
        elif field.field_type == "string_raw":
            flush_fixed()
            string_index += 1
            length_label = _string_length_label(string_index, string_count)
            terms.append(length_label)
            notes.append(f"{length_label} = {field.name} UTF-8 byte length")
        elif size is not None:
            fixed_total += size
        else:
            flush_fixed()
            terms.append("?")

    flush_fixed()
    if not terms:
        return "0 bytes"

    size_text = " + ".join(terms) + " bytes"
    if notes:
        size_text += " (" + ", ".join(notes) + ")"
    return size_text


def describe_payload_size(message: MessageSpec) -> str:
    if message.variants:
        variant_desc = []
        for variant in message.variants:
            size_text = _format_payload_size_for_fields(variant.fields)
            variant_desc.append(f"{size_text} ({variant.summary or variant.name})")
        return " / ".join(variant_desc)
    static_size = get_static_payload_size(message)
    if static_size is not None:
        return f"{static_size} bytes"
    base = _format_payload_size_for_fields(message.fields)
    if message.repeat_fields:
        per_item_sizes = [TYPE_SIZES[field.field_type] for field in message.repeat_fields]
        if all(size is not None for size in per_item_sizes):
            per_item = sum(size or 0 for size in per_item_sizes)
            return f"{base} + {per_item} bytes * item_count"
        return f"{base} + variable bytes * item_count"
    return base


def render_wire_type(field_type: str) -> str:
    return TYPE_LABELS[field_type]


def render_struct_format(fields: Iterable[FieldSpec]) -> str:
    fmt_parts: List[str] = []
    for field in fields:
        if field.field_type == "string_u32":
            fmt_parts.append(f"[uint32 {field.name}_len][utf-8 * {field.name}_len]")
        elif field.field_type == "string_raw":
            fmt_parts.append(f"[utf-8 bytes {field.name}]")
        else:
            fmt_parts.append(f"[{render_wire_type(field.field_type)} {field.name}]")
    return " ".join(fmt_parts) if fmt_parts else "(no payload)"


def get_variant_for_values(message: MessageSpec, values: Mapping[str, Any]) -> VariantSpec:
    selector_field = message.variants[0].selector_field if message.variants else "selector"
    selector_value = values.get(selector_field)
    for variant in message.variants:
        if selector_value == variant.selector_value:
            return variant
    raise ValueError(
        f"message 0x{message.msg_type:04X} does not define a variant for "
        f"{selector_field}={selector_value}"
    )


def fixed_fields(fields: Iterable[FieldSpec]) -> tuple[FieldSpec, ...]:
    return tuple(field for field in fields if field.field_type not in ("string_u32", "string_raw"))


def prefixed_string_fields(fields: Iterable[FieldSpec]) -> tuple[FieldSpec, ...]:
    return tuple(field for field in fields if field.field_type == "string_u32")


def build_struct_format(fields: Sequence[FieldSpec], endian: str = "<") -> str:
    return endian + "".join(STRUCT_FORMAT_CHARS[field.field_type] for field in fields)


def pack_value(field_type: str, value: Any) -> bytes:
    if field_type == "string_u32":
        encoded = str(value).encode("utf-8")
        return struct.pack("<I", len(encoded)) + encoded
    if field_type == "string_raw":
        return str(value).encode("utf-8")
    return struct.pack("<" + STRUCT_FORMAT_CHARS[field_type], value)


def pack_fields(fields: Sequence[FieldSpec], values: Mapping[str, Any]) -> bytes:
    payload_parts: List[bytes] = []
    for field in fields:
        if field.name not in values:
            raise KeyError(field.name)
        payload_parts.append(pack_value(field.field_type, values[field.name]))
    return b"".join(payload_parts)


def pack_repeated_fields(
    fields: Sequence[FieldSpec],
    items: Sequence[Mapping[str, Any]],
) -> bytes:
    payload_parts: List[bytes] = []
    for item in items:
        payload_parts.append(pack_fields(fields, item))
    return b"".join(payload_parts)


def pack_message_payload(
    msg_type: int,
    values: Mapping[str, Any],
    repeated_items: Optional[Sequence[Mapping[str, Any]]] = None,
) -> bytes:
    message = get_message(msg_type)
    if message.variants:
        variant = get_variant_for_values(message, values)
        payload = pack_fields(variant.fields, values)
    else:
        payload = pack_fields(message.fields, values)
    if message.repeat_fields:
        if repeated_items is None:
            raise ValueError(f"message 0x{msg_type:04X} requires repeated_items")
        payload += pack_repeated_fields(message.repeat_fields, repeated_items)
    elif repeated_items:
        raise ValueError(f"message 0x{msg_type:04X} does not support repeated_items")
    return payload


def unpack_value(field_type: str, payload: bytes, offset: int = 0) -> Tuple[Any, int]:
    if field_type == "string_u32":
        if offset + 4 > len(payload):
            raise ValueError(f"not enough bytes for string length at offset {offset}")
        (str_len,) = struct.unpack_from("<I", payload, offset)
        offset += 4
        end = offset + str_len
        if end > len(payload):
            raise ValueError(f"not enough bytes for string value at offset {offset}")
        return payload[offset:end].decode("utf-8", errors="replace"), end

    if field_type == "string_raw":
        return payload[offset:].decode("utf-8", errors="replace"), len(payload)

    size = TYPE_SIZES[field_type]
    if size is None or offset + size > len(payload):
        raise ValueError(f"not enough bytes for {field_type} at offset {offset}")
    value = struct.unpack_from("<" + STRUCT_FORMAT_CHARS[field_type], payload, offset)[0]
    return value, offset + size


def unpack_fields(
    fields: Sequence[FieldSpec],
    payload: bytes,
    offset: int = 0,
) -> Tuple[Dict[str, Any], int]:
    values: Dict[str, Any] = {}
    for field in fields:
        value, offset = unpack_value(field.field_type, payload, offset)
        values[field.name] = value
    return values, offset


def unpack_repeated_fields(
    fields: Sequence[FieldSpec],
    payload: bytes,
    count: int,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    items: List[Dict[str, Any]] = []
    for _ in range(count):
        item, offset = unpack_fields(fields, payload, offset)
        items.append(item)
    return items, offset


def unpack_message_payload(
    msg_type: int,
    payload: bytes,
    direction: str = "request",
    repeated_count_field: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], int]:
    message = get_message(msg_type) if direction == "request" else get_response_message(msg_type)
    if message.variants:
        selector_field = message.variants[0].selector_field
        selector_fields = message.variants[0].fields
        selector_offset = 0
        selector_type = None
        for field in selector_fields:
            if field.name == selector_field:
                selector_type = field.field_type
                break
            field_size = TYPE_SIZES[field.field_type]
            if field_size is None:
                raise ValueError(
                    f"message 0x{msg_type:04X} selector_field {selector_field} "
                    f"cannot follow variable-length field {field.name}"
                )
            selector_offset += field_size
        if selector_type is None:
            raise ValueError(f"message 0x{msg_type:04X} is missing selector_field {selector_field}")

        selector_value, _ = unpack_value(selector_type, payload, selector_offset)
        variant = next((v for v in message.variants if v.selector_value == selector_value), None)
        if variant is None:
            raise ValueError(
                f"message 0x{msg_type:04X} does not define a variant for "
                f"{selector_field}={selector_value}"
            )
        values, offset = unpack_fields(variant.fields, payload, 0)
    else:
        values, offset = unpack_fields(message.fields, payload, 0)

    repeated_items: List[Dict[str, Any]] = []
    if message.repeat_fields:
        if repeated_count_field is None:
            raise ValueError(f"message 0x{msg_type:04X} requires repeated_count_field")
        count = values.get(repeated_count_field)
        if not isinstance(count, int):
            raise ValueError(f"field {repeated_count_field} must be decoded before repeated fields")
        repeated_items, offset = unpack_repeated_fields(message.repeat_fields, payload, count, offset)

    return values, repeated_items, offset
