# ML Driving Pipeline Roadmap

Lane Control self-improvement is the first step toward a camera-driven
autonomous driving research pipeline. This document records the intended
direction and the order of work so the current rule-based controller can grow
into a data/model/evaluation loop without rewriting the app.

## Goal

Build a repeatable loop:

```text
MORAI Simulator
  -> camera and vehicle telemetry
  -> run recorder
  -> dataset builder
  -> training
  -> offline evaluation
  -> simulator evaluation
  -> model registry
  -> runtime inference with safety guard
```

The first production path remains the current rule-based Lane Control. ML
components should be introduced as optional candidates and compared through the
same scenario/record/analyze cycle.

## Recommended Stack

| Layer | Early choice | Later choice |
|---|---|---|
| App and sim control | Python TCP/UDP client | Python or ROS 2 bridge |
| Data recording | Current run folders | Run folders plus indexed datasets |
| Training | PyTorch | PyTorch with experiment tracking |
| Model exchange | ONNX | ONNX with versioned registry |
| Inference | Python runner | ONNX Runtime or TensorRT |
| Evaluation | Current analyzer | Offline plus closed-loop sim evaluation |

## Target Source Layout

```text
src/ml_driving/
  data/
    schema.py            Shared sample/run/dataset records
    dataset_builder.py   Build dataset indexes from recorded runs
  evaluation/
    metrics.py           KPI calculation independent of UI
  models/
    interfaces.py        Model input/output contracts
  runtime/
    inference_runner.py  Runtime wrapper around a model backend
    safety_guard.py      Output limits before MORAI control
  sim_interface/
    contracts.py         Simulator IO contracts for adapters
```

This structure is intentionally separate from `src/lane_control/`. Existing
Lane Control behavior should not import ML modules until a concrete integration
step is planned.

## Work Priority

| Priority | Work | Purpose | Status |
|---|---|---|---|
| 1 | Add ML pipeline document and package skeleton | Fix the long-term shape before feature code grows | Started |
| 2 | Add lane violation KPI | Penalize long but unstable lane-invading runs | Done |
| 3 | Add Binary noise KPI | Check whether lane input data is reliable | Done |
| 4 | Add shadow boundary KPI | Detect sun/shadow transition noise | Done |
| 5 | Add wide bright boundary filter | Remove broad bright regions while keeping thin lane structures | Done |
| 6 | Add frame image export option | Make recorded runs usable for supervised learning | Next |
| 7 | Add dataset index builder | Convert run folders into a train/eval manifest | Planned |
| 8 | Train first perception model | Predict lane offset or lane mask from camera frames | Planned |
| 9 | Add offline evaluator | Compare model predictions against recorded labels | Planned |
| 10 | Add optional inference runner | Run a model candidate without replacing rule-based control | Planned |
| 11 | Add closed-loop candidate comparison | Compare rule-based and ML candidates in Auto Cycle | Planned |

## KPI Direction

Do not judge a run only by duration. A run that survives for a long time while
crossing lane boundaries should score worse than a shorter but centered run.

Minimum KPI groups:

| Group | Metrics |
|---|---|
| Safety | collision, stuck, lane violation ratio, out-of-lane duration |
| Lane quality | mean offset, p95 offset, lane detection ratio, bad width ratio |
| Input quality | binary white ratio, upper white share, shadow boundary score, noisy frame ratio |
| Progress | valid drive time, valid distance, average speed, target speed ratio |
| Comfort | steering oscillation, throttle jerk, brake jerk |

`lane_violation_ratio` should be calculated from offset thresholds such as
`abs(offset_m) > 0.8` and `abs(offset_m) > 1.0`. Speed increase should be blocked
when violation metrics are high.

## Integration Rules

- Keep the existing Lane Control path working while ML pieces are added.
- Treat the rule-based controller as the first teacher for data collection.
- Save raw inputs and labels with timestamps; do not rely on video-only data.
- Run offline evaluation before closed-loop simulator evaluation.
- Put a safety guard between every model output and MORAI control.
- Promote a model only when it beats the current baseline in the same scenarios.

## First Pipeline Run

The first ML pipeline entrypoint does not train a model yet. It reads recorded
Lane Control runs and writes a compact KPI report that can be used to compare
future model candidates.

```bash
cd src
python -m ml_driving.pipeline_runner --limit 20
```

Default output:

```text
runs/ml_driving_report.json
```

The report recalculates lane quality from `telemetry.csv`, so it can also be
used on older runs that do not yet have `lane_violation_ratio_*` fields in
`summary.json`.
