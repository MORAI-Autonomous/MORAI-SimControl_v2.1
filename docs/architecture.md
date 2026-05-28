# Architecture Patterns

This document captures the project rules that matter during feature work.

## Runtime Shape

```text
app.py
  panels/*                 DearPyGUI UI surfaces
  runners/*                Long-running feature wrappers
  transport/*              TCP protocol and receiver thread
  receivers/*              UDP receivers and template parsing
  utils/ui_queue.py        Main-thread UI dispatch

app_cli.py
  transport/*
  utils/input_helper.py
```

Panels should stay thin. They own DearPyGUI widgets and user interaction, but long-running work belongs in runners or receivers.

## Main-Thread UI Updates

DearPyGUI calls must run on the main thread. Receiver threads and runner threads should post UI work through `utils.ui_queue.post()`.

```python
import utils.ui_queue as ui_queue

ui_queue.post(lambda: dpg.set_value("status_tag", "Running"))
```

`ui_queue.drain()` is called from the main loop in `app.py`.

## Panel Init Pattern

Panel modules must not import `app.py`. Shared app behavior is passed through `init(...)` callbacks.

```python
# panels/some_panel.py
_start_fn = None

def init(start_fn):
    global _start_fn
    _start_fn = start_fn
```

```python
# app.py
some_panel.init(start_fn=state.start_something)
```

This keeps panel code reusable and avoids circular imports.

## Runner Ownership

Runners wrap long-running behavior and are owned by `AppState`.

| Runner | Owner field | Mode | Responsibility |
|---|---|---|---|
| `runners.LaneRunner` | `self.lc_runner` | Fixed | Single lane-follow session |
| `runners.AdRunner` | `self.ad_runners` | Fixed | One runner per path-follow vehicle |
| `runners.StepAdRunner` | `self.step_ad_runners` | Fixed Step | Multi-vehicle fixed-step orchestration |

Runners should expose `start()` and `stop()` and should avoid direct DearPyGUI calls.

## Status Callback Pattern

High-frequency runtime state should update compact UI values through callbacks instead of writing log lines every tick.

```python
runner = AdRunner(
    ...,
    status_cb=autonomous_panel.update_status,
)
```

The callback implementation should post UI updates through `ui_queue` when it can be called from a background thread.

## Dynamic DearPyGUI Widgets

Dynamic UI containers should be created once and rebuilt with `delete_item(..., children_only=True)`.

```python
dpg.add_group(tag="au_vehicles_area")

def rebuild_vehicles(count: int) -> None:
    dpg.delete_item("au_vehicles_area", children_only=True)
    for index in range(count):
        with dpg.group(parent="au_vehicles_area"):
            dpg.add_input_text(tag=f"au_entity_id_{index + 1}")
```

When updating dynamic tags later, guard with `dpg.does_item_exist(tag)`.

## Runtime Config

Runtime state is stored under `config/*.json`.

- Missing files should not block startup.
- State save failures should be logged, not treated as fatal application errors.
- Create `config/` with `os.makedirs(..., exist_ok=True)` before saving.

Known state files:

- `config/app_state.json`
- `config/fp_state.json`
- `config/tfp_state.json`
- `config/monitor_state.json`
- `config/udp_control_state.json`

## Template Resolution

UDP templates are grouped by domain under `templates/`.

```text
templates/camera/
templates/control/
templates/event/
templates/sensor/
templates/vehicle/
```

Code should resolve templates by file name through `utils.template_paths.resolve_template_path()` instead of hard-coding subfolders.

## Camera Sensor

`Camera Sensor` is a standalone panel for checking camera streams.

- UI: [panels/camera_sensor_panel.py](../panels/camera_sensor_panel.py)
- RGB receiver: [receivers/camera_receiver.py](../receivers/camera_receiver.py)
- Depth receiver: [receivers/camera_depth_receiver.py](../receivers/camera_depth_receiver.py)
- Semantic/Instance receiver: [receivers/camera_semantic_receiver.py](../receivers/camera_semantic_receiver.py)
- BBox receiver: [receivers/camera_sensor_receiver.py](../receivers/camera_sensor_receiver.py)

Depth rendering details live in [camera-sensor.md](camera-sensor.md).

## Lane Control

```text
lane_preprocessor.py   BEV transform, thresholding, filters
lane_detector.py       Sliding-window lane detection
controllers.py         EMA, PD, Speed PI
vehicle_info.py        Vehicle Info UDP receiver wrapper
tune_panel.py          OpenCV tuning window
lane_controller.py     Main control loop
```

Runtime parameters are updated through `LaneController.update_params(**kwargs)`.

## Path Follow

`autonomous_driving/` owns MGeo/path-follow behavior. The GUI starts it through `runners/ad_runner.py` or `runners/step_ad_runner.py`.

Fixed Step mode coordinates this sequence:

1. Wait for FixedStep ACK.
2. Optionally request SaveData.
3. Wait for Vehicle Info updates.
4. Send ManualControl commands.
5. Send the next FixedStep request.

## Transform Playback

`Transform Playback` reads CSV rows and sends `TransformControlById` commands over time.

Expected columns include:

- `time_sec`
- `pos_x`, `pos_y`, `pos_z`
- `rot_x`, `rot_y`, `rot_z`
- `steer_angle`
- `speed`

State is stored in `config/tfp_state.json`.

## Resize Rule

Viewport resize callbacks should only mark layout state as dirty. Actual `dpg.configure_item()` work should happen from the main loop.
