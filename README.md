# MORAI Interface Console

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)

MORAI Interface Console is a Python GUI application for exercising, monitoring,
and validating MORAI Simulator interfaces. It is intended for both MORAI
developers and customers who need direct access to TCP/UDP commands, sensor
streams, object controls, and autonomous-driving examples.

The repository also includes:

- **MORAI Simulation Control**, a lightweight application focused on simulator
  launch, Suite loading, simulation-time configuration, and scenario control.
- **An Automation API client** (`ProtoClient`) that calls the simulator's
  Automation API by name, without generated code, and the scripts in `tools/`
  that check each API against a running simulator.

## Applications

| Application | Purpose | Run |
|---|---|---|
| **MORAI Interface Console** | Full TCP/UDP interface testing, monitoring, control, sensors, and driving examples | `python morai_interface_console.py` |
| **MORAI Simulation Control** | Lightweight simulator and scenario control | `python simulation_control.py` |

Optional command-line entry points are kept under `cli/`.

```bash
python cli/morai_interface_console_cli.py
python cli/simulation_control_cli.py
```

## Requirements

- Windows 10/11 or Linux
- Python 3.8+
- A running MORAI Simulator for anything that talks to it (TCP port 20000 by default)

```bash
pip install -r requirements.txt
```

`protobuf` is needed by the Automation API client only; the message definitions
come from the simulator.

## Automation API

The Automation API is the simulator's TCP API for programs and LLM agents: open a
map, place and configure entities, mount sensors, run scenarios, read what the
camera sees and the road structure. Its opcodes are `0x01xxxxxx`, and every one
answers with a `Reply` carrying a result code, a reason and the response message.

`ProtoClient` ([`src/transport/proto_client.py`](src/transport/proto_client.py))
calls them by name with plain fields. It needs no `.proto` files: `load_schema()`
asks the simulator for its message definitions (`GetApiSchema`) and opcode list
(`GetApiInfo`).

```python
import sys
sys.path.insert(0, "src")
from transport.proto_client import ProtoClient, ProtoCallError

with ProtoClient("127.0.0.1", 20000) as client:
    client.load_schema()
    print(client.call("GetSimulatorSummary"))          # state, map, mode, scenario
    view = client.call("GetViewpoint")                  # what the main camera looks at
    roads = client.call("GetRoadsNearby", location=view["center"]["location"], radius_m=50)
    lane = roads["lanes"][0]
    try:
        client.call("CreateEntity", model_name="gv_car_hdioniq5_2023",
                    initial_transform={"location": lane["center_line"][0]})
    except ProtoCallError as e:
        print(e.reason_name, e.message)                 # e.g. WRONG_MODE, NAME_IN_USE
```

Responses come back as dicts with the protobuf JSON field names; enums as their
names, `bytes` fields (images) as base64.

| Group | Opcodes | APIs |
|---|---|---|
| Simulator | `0x0101xxxx` | `GetApiInfo`, `GetApiSchema`, `GetSimulatorSummary`, `OpenMap`, precision/flow regions |
| Time | `0x0102xxxx` | `GetTimeMode`, `SetTimeMode`, `StepSimulation` |
| Entities | `0x0104xxxx` | `CreateEntity`, `SetEntityTransform`, `ListEntities`, `GetEntityState`, `DeleteEntity`, `ClearEntities`, `GetEntitySettings`, `SetEntitySettings`, `ManualControl` |
| Suites and scenarios | `0x0105xxxx` | `GetScenarioStatus`, `OpenSuite`, `SelectScenario`, `SetScenarioMode`, `ControlScenario`, `SaveSuite` |
| Catalogs | `0x0107xxxx` | `GetMapCatalog`, `GetObjectCatalog` |
| Observation | `0x0108xxxx` | `GetViewpoint`, `ScreenToWorld`, `SetViewpoint`, `CaptureMainView`, `GetCameraImage` |
| Map | `0x0109xxxx` | `GetRoadsNearby`, `GetLinkConnections` |

`GetApiInfo` lists what the running simulator build supports; do not hard-code the
list above.

The specification lives in the simulator repository (interfaceplugins). These
links are for MORAI developers; customers can ask their MORAI contact for the
specification.

- [`Docs/AutomationApi.md`](https://gitlab.morai.ai/sim-v2/interfaceplugins/-/blob/main/Docs/AutomationApi.md):
  transport, states and modes, units and coordinate frames, entities, settings,
  task sequences, errors ([Korean](https://gitlab.morai.ai/sim-v2/interfaceplugins/-/blob/main/Docs/AutomationApi.ko.md))
- [`Docs/AutomationApiReference.md`](https://gitlab.morai.ai/sim-v2/interfaceplugins/-/blob/main/Docs/AutomationApiReference.md):
  every request and response message, field by field

## Tools

Scripts under `tools/` run against a running simulator. The checks print one `OK`
or `FAIL` line per step and end with `all OK` or the number of failures; the top
of each script says what it needs (logged in, a map open, the editing mode, ...).
`--ip` / `--port` default to `127.0.0.1:20000`.

### API checks

| Script | Checks | Example |
|---|---|---|
| `state_check.py` | States and modes: what each API needs, and the refusals | `python tools/state_check.py` |
| `openmap_check.py` | `OpenMap` | `python tools/openmap_check.py --map <map>` |
| `catalog_check.py` | `GetObjectCatalog` | `python tools/catalog_check.py` |
| `scenario_check.py` | Suite and scenario operation | `python tools/scenario_check.py` |
| `entity_check.py` | Creating, moving, listing and deleting entities | `python tools/entity_check.py --vehicle <model> --x <x> --y <y>` |
| `vehicle_settings_check.py` | Vehicle role, driving mode, control source, `settings_json` | `python tools/vehicle_settings_check.py --vehicle <model> --x <x> --y <y>` |
| `sensor_check.py` | Mounting sensors and their settings | `python tools/sensor_check.py --vehicle <model> --camera <model> --x <x> --y <y>` |
| `manual_control_check.py` | `ManualControl` and the control source gate | `python tools/manual_control_check.py --vehicle <model> --x <x> --y <y>` |
| `time_mode_check.py` | Time mode and `StepSimulation` | `python tools/time_mode_check.py` |
| `fidelity_check.py` | Precision/flow regions | `python tools/fidelity_check.py` |
| `observation_check.py` | Viewpoint, `ScreenToWorld`, captures, camera images | `python tools/observation_check.py --vehicle Car_1 --camera Camera_1` |
| `road_info_check.py` | Lanes and junctions around a point, lane connections | `python tools/road_info_check.py` |
| `legacy_regression.py` | The 21 legacy TCP opcodes | `python tools/legacy_regression.py` |

`entity_pose_check.py` (`--vehicle <model> --x <x> --y <y>`) does not judge: it
prints how the simulator applies a given pose (`SEEN` lines), for the specification.

`<model>` is a name from `GetObjectCatalog`; `<x> <y>` a free spot on the map, in
the map frame (metres).

### Examples

| Script | Does |
|---|---|
| `place_on_lane.py` | Places a vehicle on the lane nearest to what the camera looks at, facing along it; `--lane N` for a road's Nth lane, `--ahead` to move along the lane |

### Debugging and mocks

| Path | Purpose |
|---|---|
| `udp_debug/` | UDP payload parsing and debugging scripts ([README](tools/udp_debug/README.md)) |
| `rdop_mock/` | Mock RDOP REST server and target for traffic integration tests ([README](tools/rdop_mock/README.md)) |
| `verify_bbox_ids.py` | Checks bbox class/instance ids against the semantic/instance image colors |
| `export_sensor_defaults.py` | Writes every sensor model's default settings for the simulator repository |
| `gen_tcp_docs.py` | Generates [`docs/tcp-api.md`](docs/tcp-api.md) for the legacy TCP API |

## Interface Console Features

- `UDP Monitor`: Receive and inspect UDP payloads from `.tmpl` files.
- `UDP Control`: Build and send UDP control payloads.
- `Commands`: Exercise simulator, map, time, Suite, scenario, and fixed-step APIs.
- `Object Control`: Create, delete, control, transform, and assign trajectories to objects.
- `Traffic Scenario`: Load `.anmroutes` files and trigger traffic generation.
- `Camera Sensor`: Visualize RGB, Depth, Semantic, Instance, and BBox streams.
- `Lane Control`: Run camera-based lane following.
- `Path Follow`: Run path-follow autonomous driving.
- `File Playback`: Replay manual-control CSV data.
- `Transform Playback`: Replay transform-control CSV data.

## Simulation Control Features

- Account login and remembered authentication
- Rendering and Headless simulator launch
- TCP connection and simulator status
- Suite loading
- Variable/Fixed simulation-time configuration
- Scenario control and status monitoring

## Legacy TCP API

The legacy opcodes (`0x1001` ... `0x1602`) are frozen and kept for existing
clients; new work uses the Automation API. Their packets are hand-packed bytes
defined in [`src/transport/message_schema.py`](src/transport/message_schema.py);
the generated reference is [`docs/tcp-api.md`](docs/tcp-api.md).
`tools/legacy_regression.py` checks them against a running simulator.

UDP payload parsing and generation use `templates/**/*.tmpl`. Templates are
resolved by file name so panels do not need to know their exact subfolder.

## Project Structure

```text
morai_interface_console.py       Full GUI entry point
simulation_control.py            Lightweight GUI entry point
cli/                             Optional command-line entry points
src/morai_interface_console_main.py
src/simulation_control_gui_main.py
src/transport/                   TCP protocol and transport
src/transport/proto_client.py    Automation API client (schema from the simulator)
src/receivers/                   UDP receivers
src/panels/                      DearPyGUI panels
src/runners/                     Long-running control features
tools/                           API checks, examples, debugging scripts
config/                          Local runtime state
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md): Application structure and integration patterns
- [`docs/camera-sensor.md`](docs/camera-sensor.md): Camera and depth rendering notes
- [`docs/lockstep-network-latency.md`](docs/lockstep-network-latency.md): FixedStep timing and save-mode protocol notes
- [`docs/tcp-interface-checklist.md`](docs/tcp-interface-checklist.md): TCP API change checklist
- [`docs/workflow.md`](docs/workflow.md): Development workflow and recurring rules

## Validation

Offline, no simulator needed:

```bash
python tools/gen_tcp_docs.py --check
python -m unittest tests.test_tcp_payloads tests.test_scenario_control
python -m compileall -q morai_interface_console.py simulation_control.py cli sitecustomize.py src tools tests
```

Against a running simulator: the [API checks](#api-checks) for the APIs a change
touches; each ends with `all OK`.

Runtime state under `config/`, debug captures, editor settings, and local
AI/MCP tool files are intentionally ignored by Git.
