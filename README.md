# MORAI Sim Control Example Code

MORAI 시뮬레이터를 TCP/UDP로 제어하고, 주요 센서 데이터를 확인하기 위한 Python 예제 클라이언트입니다.

## Requirements

- Windows 10/11 또는 Linux
- Python 3.8+

```bash
pip install -r requirements.txt
```

## Run

GUI:

```bash
python app.py
```

CLI:

```bash
python app_cli.py
```

## Project Structure

```text
app.py                 GUI entrypoint
app_cli.py             CLI entrypoint
transport/             TCP protocol, schema, sender/receiver thread
receivers/             UDP receivers and template-based parsers
panels/                DearPyGUI panels
runners/               GUI runner wrappers for lane/path follow
lane_control/          Camera-based lane follow logic
autonomous_driving/    MGeo/path-follow autonomous driving logic
templates/             UDP template files grouped by domain
samples/               Sample playback inputs and suite examples
docs/                  Architecture, API, and workflow notes
tools/                 Utility scripts
tests/                 Unit tests
config/                Runtime state files, generated locally
```

Template files are grouped under `templates/camera`, `templates/control`, `templates/event`, `templates/sensor`, and `templates/vehicle`.

## GUI Tabs

- `UDP Monitor`: Receive and inspect UDP payloads from `.tmpl` files.
- `UDP Control`: Build and send UDP control payloads.
- `Camera Sensor`: Receive and visualize RGB, Depth, Semantic, Instance, and BBox camera streams.
- `Lane Control`: Run camera-based lane following.
- `Path Follow`: Run path-follow autonomous driving.
- `File Playback`: Replay manual control CSV data.
- `Transform Playback`: Replay transform control CSV data.

## API Notes

TCP packet definitions are maintained in [transport/message_schema.py](transport/message_schema.py).
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
python -m compileall -q app.py app_cli.py runners panels receivers transport utils lane_control tools tests
python tools/gen_tcp_docs.py --check
python -m unittest tests.test_tcp_payloads
```

Runtime state files under `config/`, debug captures under `debug/`, editor settings, and local AI/MCP tool files are intentionally ignored by git.
