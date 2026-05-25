# Architecture Patterns

## ui_queue

DearPyGUI API 호출은 메인 스레드에서만 안전합니다.  
백그라운드 스레드에서 UI를 변경해야 하면 반드시 `utils.ui_queue.post()`를 사용합니다.

```python
# 잘못된 예시
dpg.set_value("tag", value)

# 올바른 예시
import utils.ui_queue as ui_queue
ui_queue.post(lambda: dpg.set_value("tag", value))
```

`ui_queue.drain()`은 `app.py`의 메인 루프에서만 호출합니다.

---

## Panel Init Pattern

패널 모듈은 `app.py`를 직접 import하지 않습니다.  
대신 `init()`으로 필요한 callback을 주입받습니다.

```python
# panels/some_panel.py
_start_fn = None
_stop_fn = None

def init(start_fn, stop_fn):
    global _start_fn, _stop_fn
    _start_fn = start_fn
    _stop_fn = stop_fn
```

```python
# app.py
some_panel.init(
    start_fn=state.start_something,
    stop_fn=state.stop_something,
)
```

---

## Runner Ownership

장시간 동작하는 기능은 보통 runner가 담당하고, `AppState`가 그 생명주기를 소유합니다.

| Runner | 보관 필드 | 모드 | 비고 |
|---|---|---|---|
| `LaneRunner` | `self.lc_runner` | Fixed | 단일 인스턴스 |
| `AdRunner` | `self.ad_runners` | Fixed | 차량별 개별 인스턴스 |
| `StepAdRunner` | `self.step_ad_runners` | Fixed Step | 전체 차량을 한 runner가 관리 |

```python
for v in vehicles:
    runner = AdRunner(...)
    runner.start()
    self.ad_runners.append(runner)
```

```python
runner = StepAdRunner(...)
runner.start()
self.step_ad_runners.append(runner)
```

---

## status_cb Pattern

주기적으로 변하는 상태는 매 tick마다 로그를 쌓지 말고, status callback으로 UI 값만 교체합니다.

```python
runner = AdRunner(
    ...,
    status_cb=au_panel.update_status,
)
```

```python
def update_status(entity_id, x, y, vel_kmh, accel, brake, steer):
    def _apply():
        dpg.set_value("some_tag", f"{vel_kmh:.1f} km/h")
    ui_queue.post(_apply)
```

이 방식이 `log.append()`보다 UI 부하가 훨씬 적습니다.

---

## Dynamic Vehicle UI

차량 수에 따라 입력 UI를 다시 만들 때는, 컨테이너 그룹을 미리 만들고 `children_only=True`로 비운 뒤 다시 생성합니다.

```python
dpg.add_group(tag="au_vehicles_area")
```

```python
def _build_vehicles(count: int) -> None:
    dpg.delete_item("au_vehicles_area", children_only=True)
    for i in range(1, count + 1):
        with dpg.group(parent="au_vehicles_area"):
            dpg.add_input_text(tag=f"au_entity_id_{i}")
```

주의:

- `delete_item(children_only=True)` 후에는 부모를 다시 명시해야 합니다.
- 동적 태그를 참조하는 update 함수는 항상 `does_item_exist()`로 방어합니다.

---

## config State Files

런타임 상태는 `config/*.json`에 저장합니다.

- 파일이 없어도 정상 시작해야 함
- 저장 실패는 치명 오류로 취급하지 않음
- `os.makedirs(..., exist_ok=True)`로 디렉터리를 자동 생성

예:

- `config/fp_state.json`
- `config/tfp_state.json`
- `config/monitor_state.json`
- `config/udp_control_state.json`

---

## lane_control Structure

`lane_control/`은 대략 다음 역할로 나뉩니다.

```text
lane_preprocessor.py   BEV 변환, 이진화, 필터
lane_detector.py       Sliding Window 기반 차선 검출
controllers.py         EMA, PD, Speed PI
vehicle_info.py        Vehicle Info UDP 수신
tune_panel.py          OpenCV 기반 튜닝 창
lane_controller.py     메인 제어 루프
```

`LaneController.update_params(**kwargs)`로 실행 중 파라미터를 갱신할 수 있습니다.

대표 파라미터:

- `kp`, `kd`
- `ema_alpha`
- `steer_rate`
- `offset_clip`
- `invert_steer`
- `target_kmh`
- `bev_top_crop`
- `min_blob_area`
- `search_ratio`
- `min_pixels`

---

## autonomous_driving Optimization

### PathManager Waypoint Cache

매 tick 전체 경로를 처음부터 훑지 않고, 이전 waypoint 근처만 탐색합니다.

```python
BACK, FRONT = 5, 100
for offset in range(-BACK, FRONT + 1):
    i = (self._last_wp + offset) % n
```

### PurePursuit Lookahead Cache

`_last_lfd_idx`부터 먼저 탐색하고, 실패하면 0부터 fallback 탐색합니다.

```python
for attempt in range(2):
    start = self._last_lfd_idx if attempt == 0 else 0
```

---

## Transform Playback

`Transform Playback`은 CSV를 읽어 `TransformControlById`를 순차 전송하는 패널입니다.

기본 규칙:

- 기본 차량 수: `2`
- 상태 파일: `config/tfp_state.json`
- 차량별 설정: `path`, `entity_id`

CSV에서 읽는 주요 값:

- `time_sec`
- `pos_x`, `pos_y`, `pos_z`
- `rot_x`, `rot_y`, `rot_z`
- `steer_angle`
- `speed`

속도 계산:

```text
speed = sqrt(local_velocity.x^2 + local_velocity.y^2)
```

현재 `Vehicle Info` 계열 CSV의 velocity 단위는 `m/s` 기준으로 사용합니다.

재생 흐름은 `FixedStep` 없이 timestamp 차이 기반으로 순차 전송하는 방식입니다.

---

## UDP Template Split

`templates/*.tmpl`에는 수신용 템플릿과 control용 템플릿이 섞여 있을 수 있습니다.

- `isControl == false`
  - `UDP Monitor`에서 수신/파싱용으로 사용
- `isControl == true`
  - `UDP Control`에서 입력 폼 생성과 UDP 전송용으로 사용

분리 기준은 [C:\Dev\MORAI-SimControl_v2.1\panels\monitor_utils.py](C:/Dev/MORAI-SimControl_v2.1/panels/monitor_utils.py:1)에 있습니다.

관련 상태 파일:

- `config/monitor_state.json`
- `config/udp_control_state.json`

---

## Camera Sensor Panel

`Camera Sensor` 패널은 `Lane Control`과 별개로 camera stream을 확인하는 독립 패널입니다.

- RGB / Depth / BBox template 선택 지원
- 수신기: [C:\Dev\MORAI-SimControl_v2.1\receivers\camera_receiver.py](C:/Dev/MORAI-SimControl_v2.1/receivers/camera_receiver.py:1), [C:\Dev\MORAI-SimControl_v2.1\receivers\camera_depth_receiver.py](C:/Dev/MORAI-SimControl_v2.1/receivers/camera_depth_receiver.py:1), [C:\Dev\MORAI-SimControl_v2.1\receivers\camera_sensor_receiver.py](C:/Dev/MORAI-SimControl_v2.1/receivers/camera_sensor_receiver.py:1)
- 패널: [C:\Dev\MORAI-SimControl_v2.1\panels\camera_sensor_panel.py](C:/Dev/MORAI-SimControl_v2.1/panels/camera_sensor_panel.py:1)
- 상세: [C:\Dev\MORAI-SimControl_v2.1\docs\camera-sensor.md](C:/Dev/MORAI-SimControl_v2.1/docs/camera-sensor.md:1)

원칙:

- camera stream 확인과 표시용 렌더링만 담당
- `LaneController`의 debug composite 생성 책임과 분리
- background receiver thread에서 받은 frame은 `ui_queue.post()`로 texture에 반영

---

## Viewport Resize Rule

viewport resize callback 안에서 직접 레이아웃을 바꾸지 않습니다.  
callback에서는 dirty flag만 세우고, 실제 `dpg.configure_item()` 호출은 메인 루프에서 처리합니다.

```python
_layout_dirty = True

def _mark_layout_dirty():
    global _layout_dirty
    _layout_dirty = True

dpg.set_viewport_resize_callback(_mark_layout_dirty)
```

```python
while dpg.is_dearpygui_running():
    if _layout_dirty:
        _apply_layout()
    dpg.render_dearpygui_frame()
```

이 규칙은 창 이동/리사이즈 시 hit-test, scroll, layout 꼬임을 줄이기 위한 것입니다.
