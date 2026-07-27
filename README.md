# MORAI Interface Console

[![TCP API Check](https://github.com/MORAI-Autonomous/MORAI-SimControl_v2.1/actions/workflows/tcp-api-check.yml/badge.svg)](https://github.com/MORAI-Autonomous/MORAI-SimControl_v2.1/actions/workflows/tcp-api-check.yml)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey)

MORAI Interface Console is a Python GUI application for exercising, monitoring,
and validating MORAI Simulator interfaces. It is intended for both MORAI
developers and customers who need direct access to TCP/UDP commands, sensor
streams, object controls, and autonomous-driving examples.

The repository also includes MORAI Simulation Control, a lightweight application
focused on simulator launch, Suite loading, simulation-time configuration, and
scenario control.

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

```bash
pip install -r requirements.txt
```

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

## API References

TCP packet definitions are maintained in
[`src/transport/message_schema.py`](src/transport/message_schema.py).
The generated reference is [`docs/tcp-api.md`](docs/tcp-api.md).

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
src/receivers/                   UDP receivers
src/panels/                      DearPyGUI panels
src/runners/                     Long-running control features
config/                          Local runtime state
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md): Application structure and integration patterns
- [`docs/camera-sensor.md`](docs/camera-sensor.md): Camera and depth rendering notes
- [`docs/tcp-interface-checklist.md`](docs/tcp-interface-checklist.md): TCP API change checklist
- [`docs/workflow.md`](docs/workflow.md): Development workflow and recurring rules

## Validation

```bash
python tools/gen_tcp_docs.py --check
python -m unittest tests.test_tcp_payloads tests.test_scenario_control
python -m compileall -q morai_interface_console.py simulation_control.py cli sitecustomize.py src tools tests
```

Runtime state under `config/`, debug captures, editor settings, and local
AI/MCP tool files are intentionally ignored by Git.
