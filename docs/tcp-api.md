# TCP API Reference

> 이 문서는 자동 생성됩니다. Confluence에서 직접 편집하지 말고 코드와 스크립트에서 수정한 뒤 다시 생성하세요.
>
> - 생성 시각: `2026-06-22 14:07 +0900`
> - 기준 브랜치: `origin/v1.0-Official-26.H1`

## Common Header

Every TCP packet uses this 16-byte header before the payload described below.

| Offset | Type | Field | Description |
|--------|------|-------|-------------|
| `+0` | `uint8` | `magic` | Fixed magic byte `0x4D` (`'M'`) |
| `+1` | `uint8` | `msg_class` | `0x01` = request, `0x02` = response, `0x03` = notification |
| `+2` | `uint32` | `msg_type` | Command / response type such as `0x1102` |
| `+6` | `uint32` | `payload_size` | Payload size in bytes, excluding the 16-byte header |
| `+10` | `uint32` | `request_id` | Request / response correlation id |
| `+14` | `uint16` | `flag` | Reserved, currently `0` |

- Header format: `proto.HEADER_FMT = <BBIIIH`
- Header size: `16 bytes`
- Payload sizes shown in this document do not include the 16-byte header.

## Summary

| Msg Type | Name | Request Payload | Response Payload |
|----------|------|-----------------|------------------|
| [`0x1001`](#api-0x1001) | [`GetSimulatorStatus`](#api-0x1001) | `0 bytes` | `12 bytes` |
| [`0x1002`](#api-0x1002) | [`GetSimulatorMode`](#api-0x1002) | `0 bytes` | `12 bytes` |
| [`0x1003`](#api-0x1003) | [`SetSimulatorMode`](#api-0x1003) | `4 bytes` | `8 bytes` |
| [`0x1004`](#api-0x1004) | [`LoadMap`](#api-0x1004) | `4 + N bytes (N = map_name UTF-8 byte length)` | `8 bytes` |
| [`0x1101`](#api-0x1101) | [`GetSimulationTimeStatus`](#api-0x1101) | `0 bytes` | `48 bytes` |
| [`0x1102`](#api-0x1102) | [`SetSimulationTimeModeCommand`](#api-0x1102) | `20 bytes` | `20 bytes` |
| [`0x1201`](#api-0x1201) | [`FixedStep`](#api-0x1201) | `4 bytes` | `8 bytes` |
| [`0x1202`](#api-0x1202) | [`SaveData`](#api-0x1202) | `0 bytes` | `8 bytes` |
| [`0x1301`](#api-0x1301) | [`CreateObject`](#api-0x1301) | `36 bytes` | `8 + 4 + N bytes (N = object_id UTF-8 byte length)` |
| [`0x1302`](#api-0x1302) | [`ManualControlById`](#api-0x1302) | `4 + N + 24 bytes (N = entity_id UTF-8 byte length)` | `8 bytes` |
| [`0x1303`](#api-0x1303) | [`TransformControlById`](#api-0x1303) | `4 + N + 36 bytes (N = entity_id UTF-8 byte length)` | `8 bytes` |
| [`0x1304`](#api-0x1304) | [`SetTrajectory`](#api-0x1304) | `4 + N1 + 4 + 4 + N2 + 4 bytes (N1 = entity_id UTF-8 byte length, N2 = trajectory_name UTF-8 byte length) + 32 bytes * item_count` | `8 bytes` |
| [`0x1305`](#api-0x1305) | [`DeleteObject`](#api-0x1305) | `N bytes (N = entity_id UTF-8 byte length)` | `8 bytes` |
| [`0x1401`](#api-0x1401) | [`ActiveSuiteStatus`](#api-0x1401) | `0 bytes` | `8 + 4 + N1 + 4 + N2 + 4 bytes (N1 = active_suite_name UTF-8 byte length, N2 = active_scenario_name UTF-8 byte length) + variable bytes * item_count` |
| [`0x1402`](#api-0x1402) | [`LoadSuite`](#api-0x1402) | `4 + N bytes (N = suite_path UTF-8 byte length)` | `8 bytes` |
| [`0x1504`](#api-0x1504) | [`ScenarioStatus`](#api-0x1504) | `0 bytes` | `12 + 4 + N bytes (N = name UTF-8 byte length)` |
| [`0x1505`](#api-0x1505) | [`ScenarioControl`](#api-0x1505) | `4 + 4 + N bytes (N = scenario_name UTF-8 byte length)` | `8 bytes` |
| [`0x1601`](#api-0x1601) | [`LoadTrafficScenario`](#api-0x1601) | `4 + N bytes (N = file_path UTF-8 byte length)` | `8 bytes` |
| [`0x1602`](#api-0x1602) | [`TrafficGenerate`](#api-0x1602) | `8 bytes` | `8 bytes` |

## APIs

<a id="api-0x1001"></a>
## `0x1001` GetSimulatorStatus

### Req

- Payload: `0 bytes`
- Builder: `tcp.send_get_simulator_status()`

Query the current simulator frontend lifecycle state.

Wire layout: variant-specific

This message has no payload.

Notes:
- No payload.

### Resp

- Payload: `12 bytes`
- Parser: `tcp.parse_get_simulator_status_payload()`

Return the current simulator frontend lifecycle state.

Wire layout: `[uint32 result_code] [uint32 detail_code] [uint32 state]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
| `state` | `uint32` | 0=UNSPECIFIED, 1=PRE_LOGIN, 2=HOME, 3=LOADING, 4=READY |

### Noti

- Payload: `4 bytes`
- Parser: `tcp.parse_get_simulator_status_notification_payload()`

Push the current simulator frontend lifecycle state without a preceding request.

Wire layout: `[uint32 state]`

| Field | Type | Description |
|------|------|-------------|
| `state` | `uint32` | Protobuf enum value. 0=UNSPECIFIED, 1=PRE_LOGIN, 2=HOME, 3=LOADING, 4=READY |

Notes:
- Header uses msg_class = 0x03 (NOTI).
- Payload is protobuf-encoded datamodel::SimulatorStatus, not the raw 12-byte response layout.
- Current parser expects minimal wire format: 0x08 <varint(state)>.

<a id="api-0x1002"></a>
## `0x1002` GetSimulatorMode

### Req

- Payload: `0 bytes`
- Builder: `tcp.send_get_simulator_mode()`

Query the current simulator functional mode.

Wire layout: variant-specific

This message has no payload.

Notes:
- No payload.

### Resp

- Payload: `12 bytes`
- Parser: `tcp.parse_get_simulator_mode_payload()`

Return result code and the current simulator mode.

Wire layout: `[uint32 result_code] [uint32 detail_code] [uint32 mode]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
| `mode` | `uint32` | 0=UNSPECIFIED, 1=SCENARIO, 2=REPLAY, 3=TRAFFIC, 4=MONITORING, 5=COMPETITION |

<a id="api-0x1003"></a>
## `0x1003` SetSimulatorMode

### Req

- Payload: `4 bytes`
- Builder: `tcp.send_set_simulator_mode()`

Request a transition to the specified simulator functional mode.

Wire layout: `[uint32 mode]`

| Field | Type | Description |
|------|------|-------------|
| `mode` | `uint32` | 1=SCENARIO, 2=REPLAY, 3=TRAFFIC, 4=MONITORING, 5=COMPETITION |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a set-simulator-mode request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1004"></a>
## `0x1004` LoadMap

### Req

- Payload: `4 + N bytes (N = map_name UTF-8 byte length)`
- Builder: `tcp.send_load_map()`

Request the simulator to load the specified map by name.

Wire layout: `[uint32 map_name_len][utf-8 * map_name_len]`

| Field | Type | Description |
|------|------|-------------|
| `map_name_len` | `uint32` | map_name UTF-8 byte length |
| `map_name` | `utf-8 bytes` | Map name string to look up in the map registry |

Notes:
- Returns InvalidParam if the map name is not found in the registry.

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a load-map request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1101"></a>
## `0x1101` GetSimulationTimeStatus

### Req

- Payload: `0 bytes`
- Builder: `tcp.send_get_status()`

Query current simulation time mode and timing state.

Wire layout: variant-specific

This message has no payload.

Notes:
- No payload.

### Resp

- Payload: `48 bytes`
- Parser: `tcp.parse_get_status_payload()`

Return result code plus current simulation time mode and simulation clock state.

Wire layout: `[uint32 result_code] [uint32 detail_code] [uint32 mode] [int32 target_fps] [int32 physics_delta_time] [int32 rtf] [int32 user_control] [uint64 step_index] [int64 seconds] [int32 nanos]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
| `mode` | `uint32` | 1 = TIME_MODE_VARIABLE, 2 = TIME_MODE_FIXED |
| `target_fps` | `int32` | Target FPS |
| `physics_delta_time` | `int32` | Physics delta time in ms |
| `rtf` | `int32` | Fixed only. Variable mode returns 0 |
| `user_control` | `int32` | Fixed only. Variable mode returns 0 |
| `step_index` | `uint64` | Accumulated step count |
| `seconds` | `int64` | Simulation time seconds |
| `nanos` | `int32` | Simulation time nanoseconds remainder |

<a id="api-0x1102"></a>
## `0x1102` SetSimulationTimeModeCommand

### Req

- Payload: `20 bytes`
- Builder: `tcp.send_simulation_time_mode_command()`

Set simulation time mode using a fixed 20-byte payload.

Wire layout: `[int32 mode] [int32 target_fps] [int32 physics_delta_time] [int32 rtf] [int32 user_control]`

| Field | Type | Description |
|------|------|-------------|
| `mode` | `int32` | 1 = TIME_MODE_VARIABLE, 2 = TIME_MODE_FIXED |
| `target_fps` | `int32` | Target FPS (10~200) |
| `physics_delta_time` | `int32` | Physics delta time in ms (5~100) |
| `rtf` | `int32` | Fixed only. Variable mode must send 0 |
| `user_control` | `int32` | Fixed only. Variable mode sends 0 |

### Resp

- Payload: `20 bytes`
- Parser: `tcp.parse_set_simulation_time_mode_payload()`

Return result code and the applied simulation time settings.

Wire layout: `[uint32 result_code] [uint32 detail_code] [uint32 mode] [float32 fixed_delta] [float32 simulation_speed]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
| `mode` | `uint32` | - |
| `fixed_delta` | `float32` | - |
| `simulation_speed` | `float32` | - |

<a id="api-0x1201"></a>
## `0x1201` FixedStep

### Req

- Payload: `4 bytes`
- Builder: `tcp.send_fixed_step()`

Advance the simulator by a fixed number of steps.

Wire layout: `[uint32 step_count]`

| Field | Type | Description |
|------|------|-------------|
| `step_count` | `uint32` | Number of simulation steps to execute |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a fixed-step request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1202"></a>
## `0x1202` SaveData

### Req

- Payload: `0 bytes`
- Builder: `tcp.send_save_data()`

Trigger simulator-side data capture.

Wire layout: variant-specific

This message has no payload.

Notes:
- No payload.

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a save-data request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1301"></a>
## `0x1301` CreateObject

### Req

- Payload: `36 bytes`
- Builder: `tcp.send_create_object()`

Create an entity with initial transform and vehicle configuration.

Wire layout: `[int32 entity_type] [float32 pos_x] [float32 pos_y] [float32 pos_z] [float32 rot_x] [float32 rot_y] [float32 rot_z] [int32 driving_mode] [int32 ground_vehicle_model]`

| Field | Type | Description |
|------|------|-------------|
| `entity_type` | `int32` | EntityType enum value |
| `pos_x` | `float32` | - |
| `pos_y` | `float32` | - |
| `pos_z` | `float32` | - |
| `rot_x` | `float32` | - |
| `rot_y` | `float32` | - |
| `rot_z` | `float32` | - |
| `driving_mode` | `int32` | VehicleDrivingMode enum value |
| `ground_vehicle_model` | `int32` | GroundVehicleModel enum value |

### Resp

- Payload: `8 + 4 + N bytes (N = object_id UTF-8 byte length)`
- Parser: `tcp.parse_create_object_payload()`

Return result code and the created object identifier.

Wire layout: `[uint32 result_code] [uint32 detail_code] [uint32 object_id_len][utf-8 * object_id_len]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
| `object_id_len` | `uint32` | object_id UTF-8 byte length |
| `object_id` | `utf-8 bytes` | - |

<a id="api-0x1302"></a>
## `0x1302` ManualControlById

### Req

- Payload: `4 + N + 24 bytes (N = entity_id UTF-8 byte length)`
- Builder: `tcp.send_manual_control_by_id()`

Send manual throttle, brake, and steering-wheel angle to a target entity.

Wire layout: `[uint32 entity_id_len][utf-8 * entity_id_len] [float64 throttle] [float64 brake] [float64 steer_angle]`

| Field | Type | Description |
|------|------|-------------|
| `entity_id_len` | `uint32` | entity_id UTF-8 byte length |
| `entity_id` | `utf-8 bytes` | Control target Entity ID |
| `throttle` | `float64` | Throttle input value |
| `brake` | `float64` | Brake input value |
| `steer_angle` | `float64` | Steering wheel angle value |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a manual-control request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1303"></a>
## `0x1303` TransformControlById

### Req

- Payload: `4 + N + 36 bytes (N = entity_id UTF-8 byte length)`
- Builder: `tcp.send_transform_control_by_id()`

Set target transform, steer angle, and speed for a target entity.

Wire layout: `[uint32 entity_id_len][utf-8 * entity_id_len] [float32 pos_x] [float32 pos_y] [float32 pos_z] [float32 rot_x] [float32 rot_y] [float32 rot_z] [float32 steer_angle] [float64 speed]`

| Field | Type | Description |
|------|------|-------------|
| `entity_id_len` | `uint32` | entity_id UTF-8 byte length |
| `entity_id` | `utf-8 bytes` | - |
| `pos_x` | `float32` | - |
| `pos_y` | `float32` | - |
| `pos_z` | `float32` | - |
| `rot_x` | `float32` | - |
| `rot_y` | `float32` | - |
| `rot_z` | `float32` | - |
| `steer_angle` | `float32` | - |
| `speed` | `float64` | Currently derived from Vehicle Info local velocity in m/s |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a transform-control request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1304"></a>
## `0x1304` SetTrajectory

### Req

- Payload: `4 + N1 + 4 + 4 + N2 + 4 bytes (N1 = entity_id UTF-8 byte length, N2 = trajectory_name UTF-8 byte length) + 32 bytes * item_count`
- Builder: `tcp.send_set_trajectory()`

Send a named trajectory and follow mode to a target entity.

Wire layout: `[uint32 entity_id_len][utf-8 * entity_id_len] [int32 follow_mode] [uint32 trajectory_name_len][utf-8 * trajectory_name_len] [uint32 point_count]`

| Field | Type | Description |
|------|------|-------------|
| `entity_id_len` | `uint32` | entity_id UTF-8 byte length |
| `entity_id` | `utf-8 bytes` | - |
| `follow_mode` | `int32` | 1 = POSITION, 2 = FOLLOW |
| `trajectory_name_len` | `uint32` | trajectory_name UTF-8 byte length |
| `trajectory_name` | `utf-8 bytes` | - |
| `point_count` | `uint32` | - |

Repeat layout:

| Field | Type | Description |
|------|------|-------------|
| `points[].x` | `float64` | - |
| `points[].y` | `float64` | - |
| `points[].z` | `float64` | - |
| `points[].time` | `float64` | - |

Notes:
- Each trajectory point is serialized as four float64 values.

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a set-trajectory request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1305"></a>
## `0x1305` DeleteObject

### Req

- Payload: `N bytes (N = entity_id UTF-8 byte length)`
- Builder: `tcp.send_delete_object()`

Delete a target entity by identifier.

Wire layout: `[utf-8 bytes entity_id]`

| Field | Type | Description |
|------|------|-------------|
| `entity_id` | `utf-8 bytes` | UTF-8 entity identifier. No length prefix. |

Notes:
- Header payload_size is the UTF-8 byte length of entity_id.

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a delete-object request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1401"></a>
## `0x1401` ActiveSuiteStatus

### Req

- Payload: `0 bytes`
- Builder: `tcp.send_active_suite_status()`

Query the active suite and scenario list.

Wire layout: variant-specific

This message has no payload.

Notes:
- No payload.

### Resp

- Payload: `8 + 4 + N1 + 4 + N2 + 4 bytes (N1 = active_suite_name UTF-8 byte length, N2 = active_scenario_name UTF-8 byte length) + variable bytes * item_count`
- Parser: `tcp.parse_active_suite_status_payload()`

Return the active suite, active scenario, and scenario name list.

Wire layout: `[uint32 result_code] [uint32 detail_code] [uint32 active_suite_name_len][utf-8 * active_suite_name_len] [uint32 active_scenario_name_len][utf-8 * active_scenario_name_len] [uint32 scenario_list_size]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
| `active_suite_name_len` | `uint32` | active_suite_name UTF-8 byte length |
| `active_suite_name` | `utf-8 bytes` | - |
| `active_scenario_name_len` | `uint32` | active_scenario_name UTF-8 byte length |
| `active_scenario_name` | `utf-8 bytes` | - |
| `scenario_list_size` | `uint32` | - |

Repeat layout:

| Field | Type | Description |
|------|------|-------------|
| `scenario_list[].name_len` | `uint32` | scenario_list[].name UTF-8 byte length |
| `scenario_list[].name` | `utf-8 bytes` | - |

<a id="api-0x1402"></a>
## `0x1402` LoadSuite

### Req

- Payload: `4 + N bytes (N = suite_path UTF-8 byte length)`
- Builder: `tcp.send_load_suite()`

Load a MORAI suite from a path string.

Wire layout: `[uint32 suite_path_len][utf-8 * suite_path_len]`

| Field | Type | Description |
|------|------|-------------|
| `suite_path_len` | `uint32` | suite_path UTF-8 byte length |
| `suite_path` | `utf-8 bytes` | - |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a load-suite request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1504"></a>
## `0x1504` ScenarioStatus

### Req

- Payload: `0 bytes`
- Builder: `tcp.send_scenario_status()`

Query current scenario execution state.

Wire layout: variant-specific

This message has no payload.

Notes:
- No payload.

### Resp

- Payload: `12 + 4 + N bytes (N = name UTF-8 byte length)`
- Parser: `tcp.parse_scenario_status_payload()`

Return result code, current scenario execution state, and scenario name.

Wire layout: `[uint32 result_code] [uint32 detail_code] [uint32 state] [uint32 name_len][utf-8 * name_len]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
| `state` | `uint32` | 1=Play, 2=Pause, 3=Stop, 4=Completed |
| `name_len` | `uint32` | name UTF-8 byte length |
| `name` | `utf-8 bytes` | Current scenario name |

Notes:
- Parser currently accepts both the new payload (result_code/detail_code/state/name) and the legacy 12-byte payload (result_code/detail_code/state).
- When the legacy payload is received, `name` is returned as an empty string.

### Noti

- Payload: `4 + 4 + N bytes (N = name UTF-8 byte length)`
- Parser: `tcp.parse_scenario_status_notification_payload()`

Push the current scenario execution state and scenario name without a preceding request.

Wire layout: `[uint32 state] [uint32 name_len][utf-8 * name_len]`

| Field | Type | Description |
|------|------|-------------|
| `state` | `uint32` | Protobuf enum value. 1=Play, 2=Pause, 3=Stop, 4=Completed |
| `name_len` | `uint32` | name UTF-8 byte length |
| `name` | `utf-8 bytes` | Current scenario name |

Notes:
- Header uses msg_class = 0x03 (NOTI).
- Payload is assumed to be protobuf-encoded scenario status data, not the raw request/response layout.
- Current parser expects field #1 = varint state, field #2 = length-delimited utf-8 scenario name.

<a id="api-0x1505"></a>
## `0x1505` ScenarioControl

### Req

- Payload: `4 + 4 + N bytes (N = scenario_name UTF-8 byte length)`
- Builder: `tcp.send_scenario_control()`

Control scenario playback state and optional target scenario name.

Wire layout: `[uint32 command] [uint32 scenario_name_len][utf-8 * scenario_name_len]`

| Field | Type | Description |
|------|------|-------------|
| `command` | `uint32` | 1=Play, 2=Pause, 3=Stop, 4=Prev, 5=Next |
| `scenario_name_len` | `uint32` | scenario_name UTF-8 byte length |
| `scenario_name` | `utf-8 bytes` | - |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a scenario-control request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1601"></a>
## `0x1601` LoadTrafficScenario

### Req

- Payload: `4 + N bytes (N = file_path UTF-8 byte length)`
- Builder: `tcp.send_load_traffic_scenario()`

Load a traffic scenario from an .anmroutes file path.

Wire layout: `[uint32 file_path_len][utf-8 * file_path_len]`

| Field | Type | Description |
|------|------|-------------|
| `file_path_len` | `uint32` | file_path UTF-8 byte length |
| `file_path` | `utf-8 bytes` | .anmroutes file path encoded as UTF-8 |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a load-traffic-scenario request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |

<a id="api-0x1602"></a>
## `0x1602` TrafficGenerate

### Req

- Payload: `8 bytes`
- Builder: `tcp.send_traffic_generate()`

Generate traffic using the loaded traffic scenario.

Wire layout: `[int32 autonomous] [int32 lc_rate]`

| Field | Type | Description |
|------|------|-------------|
| `autonomous` | `int32` | Autonomous driving flag |
| `lc_rate` | `int32` | Lane-change rate |

### Resp

- Payload: `8 bytes`
- Parser: `tcp.parse_result_code()`

Return result code for a traffic-generate request.

Wire layout: `[uint32 result_code] [uint32 detail_code]`

| Field | Type | Description |
|------|------|-------------|
| `result_code` | `uint32` | - |
| `detail_code` | `uint32` | - |
