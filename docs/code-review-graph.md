# Code Review Graph

This graph is a review-oriented view of the project. It focuses on ownership boundaries,
runtime data flow, and modules that are risky to change together.

## Top-Level Runtime Graph

```mermaid
flowchart TD
    app["app.py<br/>DearPyGUI entrypoint"]
    cli["app_cli.py<br/>CLI entrypoint"]

    panels["panels/*<br/>GUI panels"]
    runners["lane_runner.py / ad_runner.py / step_ad_runner.py<br/>GUI runner wrappers"]
    transport["transport/*<br/>TCP schema, commands, transport, thread"]
    receivers["receivers/*<br/>UDP receivers and template parsing"]
    lane["lane_control/*<br/>camera lane follow"]
    ad["autonomous_driving/*<br/>path follow and MGeo logic"]
    utils["utils/*<br/>UI queue and input helpers"]
    templates["templates/*.tmpl<br/>UDP message layouts"]
    config["config/*.json<br/>runtime state"]
    samples["samples/*<br/>playback inputs"]

    app --> panels
    app --> runners
    app --> transport
    app --> utils
    cli --> transport
    cli --> utils

    panels --> transport
    panels --> receivers
    panels --> templates
    panels --> utils
    panels --> config
    panels --> samples

    runners --> lane
    runners --> ad
    runners --> transport
    runners --> receivers

    lane --> receivers
    lane --> transport
    ad --> transport
    ad --> receivers

    receivers --> templates
    transport --> config
```

## Camera Sensor Review Graph

```mermaid
flowchart TD
    camera_panel["panels/camera_sensor_panel.py<br/>slot UI, receiver selection, visualization"]

    rgb_receiver["receivers/camera_receiver.py<br/>RGB image stream"]
    depth_receiver["receivers/camera_depth_receiver.py<br/>32FC1 depth stream"]
    seg_receiver["receivers/camera_semantic_receiver.py<br/>semantic / instance stream"]
    bbox_receiver["receivers/camera_sensor_receiver.py<br/>RGB + bbox stream"]

    templates["templates/<br/>Camera RGB / Depth / Semantic / Instance / BBox"]
    ui_queue["utils/ui_queue.py<br/>main-thread UI updates"]
    dpg["DearPyGUI texture<br/>RGBA float texture upload"]
    opencv["OpenCV / NumPy<br/>decode, colorize, resize"]
    debug_png["debug/camera_depth/*<br/>visualize_depth debug PNG"]

    camera_panel --> rgb_receiver
    camera_panel --> depth_receiver
    camera_panel --> seg_receiver
    camera_panel --> bbox_receiver
    camera_panel --> ui_queue
    camera_panel --> opencv
    camera_panel --> dpg
    camera_panel --> debug_png

    rgb_receiver --> templates
    depth_receiver --> templates
    seg_receiver --> templates
    bbox_receiver --> templates
```

## TCP/API Review Graph

```mermaid
flowchart TD
    schema["transport/message_schema.py<br/>API command schema"]
    defs["transport/protocol_defs.py<br/>packet ids and payload helpers"]
    tcp["transport/tcp_transport.py<br/>socket send/receive"]
    thread["transport/tcp_thread.py<br/>background TCP thread"]
    commands["transport/commands.py<br/>high-level command calls"]

    app["app.py"]
    command_panel["panels/commands.py"]
    udp_control["panels/udp_control_panel.py"]
    runners["ad_runner.py / lane_runner.py / step_ad_runner.py"]
    docs["docs/tcp-api.md<br/>generated API reference"]
    tests["tests/test_tcp_payloads.py"]
    generator["tools/gen_tcp_docs.py"]

    schema --> defs
    schema --> tcp
    defs --> tcp
    defs --> commands
    tcp --> thread
    thread --> app
    commands --> app
    commands --> command_panel
    defs --> udp_control
    tcp --> runners

    schema --> generator
    generator --> docs
    schema --> tests
```

## Lane Follow Review Graph

```mermaid
flowchart TD
    runner["lane_runner.py<br/>GUI wrapper"]
    panel["panels/lane_control_panel.py<br/>GUI state and preview"]
    controller["lane_control/lane_controller.py<br/>runtime loop"]
    detector["lane_control/lane_detector.py"]
    preprocessor["lane_control/lane_preprocessor.py"]
    controllers["lane_control/controllers.py<br/>PD/PI control"]
    tune["lane_control/tune_panel.py"]
    vehicle["lane_control/vehicle_info.py"]
    camera["receivers/camera_receiver.py"]
    wheel["receivers/vehicle_info_with_wheel_receiver.py"]
    tcp["transport/tcp_transport.py"]
    defs["transport/protocol_defs.py"]

    panel --> runner
    runner --> controller
    controller --> detector
    controller --> preprocessor
    controller --> controllers
    controller --> tune
    controller --> vehicle
    controller --> camera
    controller --> tcp
    controller --> defs
    vehicle --> wheel
```

## Path Follow Review Graph

```mermaid
flowchart TD
    ad_runner["ad_runner.py / step_ad_runner.py<br/>GUI runner wrappers"]
    ad_panel["panels/autonomous_panel.py / panels/step_ad_panel.py"]
    ad_core["autonomous_driving/autonomous_driving.py<br/>path-follow orchestration"]
    config["autonomous_driving/config/config.py"]
    path_manager["autonomous_driving/localization/path_manager.py"]
    control["autonomous_driving/control/*<br/>PID / pure pursuit / control input"]
    planning["autonomous_driving/planning/adaptive_cruise_control.py"]
    mgeo["autonomous_driving/mgeo/*<br/>MGeo path generation"]
    vehicle_state["autonomous_driving/vehicle_state.py"]
    vehicle_receiver["receivers/vehicle_info_receiver.py"]
    tcp["transport/tcp_transport.py"]

    ad_panel --> ad_runner
    ad_runner --> ad_core
    ad_runner --> vehicle_receiver
    ad_runner --> tcp
    ad_core --> config
    ad_core --> path_manager
    ad_core --> control
    ad_core --> planning
    ad_core --> mgeo
    control --> vehicle_state
```

## Review Order

1. `transport/message_schema.py`, `transport/protocol_defs.py`, `transport/tcp_transport.py`
2. `receivers/template_parser.py`, then the specific receiver being changed
3. `panels/*` UI integration, checking `utils.ui_queue.post()` for background-thread UI writes
4. Runner wrappers: `lane_runner.py`, `ad_runner.py`, `step_ad_runner.py`
5. Domain logic: `lane_control/*` or `autonomous_driving/*`
6. Docs and tests: `docs/*`, `tools/gen_tcp_docs.py`, `tests/test_tcp_payloads.py`

## High-Risk Review Boundaries

- `panels/*` must not import `app.py`; callbacks should be injected from the entrypoint.
- Background receiver threads must not update DearPyGUI directly; use `utils.ui_queue.post()`.
- UDP camera/template changes should be reviewed with the matching `templates/*.tmpl` file.
- TCP API changes should update `transport/message_schema.py`, regenerate `docs/tcp-api.md`, and run payload tests.
- Depth camera changes should compare three outputs separately: raw receiver stats, `_visualize_depth()` debug PNG, and GUI texture preview.

## Useful Verification Commands

```bash
python -m py_compile app.py panels/camera_sensor_panel.py receivers/camera_depth_receiver.py
python tools/gen_tcp_docs.py --check
python -m unittest tests.test_tcp_payloads
```
