# MORAI Sim Control Example Code

Python GUI client for controlling MORAI Simulator through TCP/UDP APIs and
checking key simulator, object, scenario, traffic, and sensor data.

## Requirements

- Windows 10/11 or Linux
- Python 3.8+

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

## GUI Tabs

- `UDP Monitor`: Receive and inspect UDP payloads from `.tmpl` files.
- `UDP Control`: Build and send UDP control payloads.
- `Commands`: Control simulator mode/map, simulation time, suite/scenario, traffic scenario, and fixed-step commands.
- `Object Control`: Create, delete, manually control, transform, and assign trajectories to simulator objects.
- `Camera Sensor`: Receive and visualize RGB, Depth, Semantic, Instance, and BBox camera streams.
- `Lane Control`: Run camera-based lane following.
- `Path Follow`: Run path-follow autonomous driving.
- `File Playback`: Replay manual control CSV data.
- `Transform Playback`: Replay transform control CSV data.

## API Notes

TCP packet definitions are maintained in [src/transport/message_schema.py](src/transport/message_schema.py).
The generated TCP API reference is [docs/tcp-api.md](docs/tcp-api.md).

UDP payload parsing and generation are based on `templates/**/*.tmpl`.
The template discovery logic resolves templates by file name, so panels do not need to know the exact subfolder.

## Main Docs

- [docs/architecture.md](docs/architecture.md): Application structure and integration patterns
- [docs/camera-sensor.md](docs/camera-sensor.md): Camera Sensor and depth rendering notes
- [docs/tcp-interface-checklist.md](docs/tcp-interface-checklist.md): TCP API change checklist
- [docs/workflow.md](docs/workflow.md): Development workflow and recurring rules

## Validation

```bash
python tools/gen_tcp_docs.py --check
python -m unittest tests.test_tcp_payloads tests.test_scenario_control
python -m compileall -q app.py app_cli.py sitecustomize.py src tools tests
```

Runtime state files under `config/`, debug captures under `debug/`, editor settings, and local AI/MCP tool files are intentionally ignored by git.
