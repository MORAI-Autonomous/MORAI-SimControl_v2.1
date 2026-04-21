# MORAI Sim Control

TCP/UDP를 통해 MORAI 시뮬레이터와 연동하는 Python 클라이언트입니다.

- **`app.py`** — DearPyGUI 기반 GUI 컨트롤 패널
- **`app_cli.py`** — 키보드 인터랙티브 CLI (터미널 전용)
- **`lane_control/`** — 카메라 영상 기반 차선 인식 및 자율주행 컨트롤러
- **`autonomous_driving/`** — MGeo 경로 기반 자율주행 (Pure Pursuit + ACC)

---

## Requirements

- Windows 10/11 또는 Linux (WSL2 포함)
- Python **3.8+**

| 용도 | 패키지 |
|------|--------|
| GUI (`app.py`) | `dearpygui` |
| 차선 제어 (`lane_control/`) | `opencv-python`, `numpy` |
| 아이콘 변환 (선택) | `Pillow` |

```bash
pip install -r requirements.txt
```

---

## Project Structure

```
├── app.py                          # GUI 진입점
├── app_cli.py                      # CLI 진입점
├── ad_runner.py                    # 자율주행 실행기 (Fixed 모드, 차량 1대)
├── step_ad_runner.py               # 자율주행 실행기 (Fixed Step 모드, 다중 차량)
├── lane_runner.py                  # 차선 자율주행 실행기 (GUI 연동)
│
├── templates/                      # MORAI .tmpl 파일 모음
│   ├── Vehicle Info.tmpl
│   ├── Vehicle Info with wheel.tmpl
│   ├── IMU Template.tmpl
│   ├── GNSS Template.tmpl
│   ├── Collision Event Data.tmpl
│   ├── Detected Object.tmpl
│   ├── Camera Template.tmpl
│   └── ...
│
├── config/                         # 런타임 상태 저장 (자동 생성)
│   ├── monitor_state.json          # 마지막으로 열었던 UDP Monitor 탭 목록
│   └── fp_state.json               # 마지막 File Playback CSV 경로 / Entity ID
│
├── transport/                      # TCP/UDP 통신 레이어
│   ├── protocol_defs.py            # 상수, 포맷 문자열, 크기 정의
│   ├── tcp_transport.py            # 패킷 빌드 / 송수신 / 파싱
│   ├── tcp_thread.py               # TCP 수신 스레드
│   └── commands.py                 # UDP 송신 (ManualCommand)
│
├── receivers/                      # UDP 수신기
│   ├── template_parser.py          # .tmpl 기반 범용 바이너리 파서
│   ├── camera_receiver.py          # 카메라 영상 UDP 수신
│   ├── vehicle_info_receiver.py    # VehicleInfo UDP 수신
│   └── collision_event_receiver.py
│
├── automation/
│   └── automation.py               # FixedStep ↔ SaveData 자동 반복 스레드
│
├── panels/                         # GUI 패널 (app.py 전용)
│   ├── commands.py                 # 커맨드 패널 (Suite / Sim / Scenario / Object / FixedStep)
│   ├── monitor.py                  # UDP Monitor 탭 (.tmpl 기반 동적 표시)
│   ├── lane_control_panel.py       # Lane Control 탭 (디버그 뷰 + 튜닝 슬라이더)
│   ├── autonomous_panel.py         # Autonomous 탭 (Fixed / Fixed Step 통합, 동적 차량 설정)
│   ├── file_playback_panel.py      # File Playback 탭 (CSV 재생 + 진행 바)
│   └── log.py                      # 로그 패널
│
├── lane_control/                   # 카메라 기반 차선 인식 + 자율주행
│   ├── lane_preprocessor.py        # BEV 변환, 이진화, 노이즈 필터
│   ├── lane_detector.py            # Sliding Window 차선 검출
│   └── lane_controller.py          # PD 조향 + 속도 PI 제어, 실시간 파라미터 튜닝
│
├── autonomous_driving/             # MGeo 경로 기반 자율주행
│   ├── autonomous_driving.py
│   ├── vehicle_state.py
│   ├── control/                    # Pure Pursuit (윈도우 탐색 캐시 적용)
│   ├── localization/               # Path Manager (윈도우 탐색 캐시 적용)
│   ├── planning/                   # ACC
│   └── mgeo/                       # MGeo 맵 파싱 / 경로 탐색
│
└── utils/
    ├── ui_queue.py                 # 백그라운드 → DPG 안전 업데이트 큐
    ├── key_input.py                # 플랫폼별 raw 키 입력
    └── input_helper.py             # CLI 프롬프트 헬퍼
```

---

## Configuration

`transport/protocol_defs.py` 상단 값을 환경에 맞게 수정합니다.

```python
TCP_SERVER_IP   = "127.0.0.1"
TCP_SERVER_PORT = 20000

AUTO_TIMEOUT_SEC            = 2.0
AUTO_DELAY_BETWEEN_CMDS_SEC = 0.0
MAX_CALL_NUM                = 2000
```

> **WSL2**: mirrored networking이 활성화된 환경(Windows 11 22H2+)에서는 `127.0.0.1` 그대로 사용 가능합니다.

---

## How To Run

### GUI

```bash
python app.py
```

### CLI

```bash
python app_cli.py
```

### 차선 자율주행 컨트롤러 (CLI 단독)

```bash
# 기본 실행 (target 15km/h, 카메라 포트 9090)
python lane_control/lane_controller.py

# 속도 / 게인 조정
python lane_control/lane_controller.py --target-speed 30 --kp-spd 0.05

# 고정 스로틀 모드
python lane_control/lane_controller.py --no-speed-ctrl --throttle 0.3
```

GUI에서 실행할 경우 우측 탭바의 **Lane Control 탭**을 사용합니다.

---

## GUI 우측 탭 패널

우측 패널은 버튼+show/hide 방식의 커스텀 탭으로 구성됩니다.

| 탭 | 태그 키 | 설명 |
|----|---------|------|
| UDP Monitor | `udp` | 템플릿 기반 UDP 수신 모니터 |
| Lane Control | `lc` | 차선 자율주행 제어 및 실시간 튜닝 |
| Autonomous | `au` | MGeo 경로 기반 자율주행 (Fixed / Fixed Step) |
| File Playback | `fp` | CSV 제어값 파일 재생 |

---

## GUI 주요 기능

### Autonomous 탭

MGeo 경로 파일을 기반으로 Pure Pursuit 조향 + ACC 속도 제어를 수행합니다.

**레이아웃:**

| 섹션 | 내용 |
|------|------|
| CONTROL | Fixed Step 체크박스, Save Data 체크박스, ▶ Start / ■ Stop, 상태 표시 |
| VEHICLES | 차량 수 입력 (기본 2, 최소 1, 최대 6) + 차량별 설정 |

**차량별 설정 항목 (동적):**

| 항목 | 설명 |
|------|------|
| Path | 경로 CSV 파일 경로 (기본값 `path_link.csv` — 상암맵 기준) |
| ID | Entity ID (예: `Car_1`) |
| Port | VehicleInfo UDP 수신 포트 |
| Status | Pos / Vel / Accel / Brake / Steer 실시간 표시 |

**실행 모드:**

| 모드 | 설명 |
|------|------|
| Fixed (기본) | 시뮬레이터가 자체 타이밍으로 연속 실행. 차량별 `AdRunner` 스레드 1개씩 기동 |
| Fixed Step | 클라이언트가 매 tick 제어 → FixedStep ACK → 다음 tick. `StepAdRunner` 1개로 전체 차량 관리 |

Fixed Step 모드 선택 시 **Save Data** 체크박스가 자동 활성화됩니다.

---

### Lane Control 탭

카메라 영상을 수신하여 차선을 인식하고 자율주행을 수행하는 전용 탭입니다.

**레이아웃:**

| 섹션 | 내용 |
|------|------|
| CONTROL | ▶ Start / ■ Stop |
| TARGET VEHICLE | Entity ID, 속도 제어 On/Off, 목표 속도, Invert Steer |
| INTERFACE | Vehicle Info 수신 포트, 카메라 수신 포트 |
| TUNING | 실시간 PD 게인 / 노이즈 필터 슬라이더 + Reset 버튼 |
| LIVE VIEW | 디버그 합성 영상 (640×240) + Vehicle Info 수치 |

**TUNING 슬라이더:**

| 슬라이더 | 범위 | 기본값 | 설명 |
|----------|------|--------|------|
| Kp | 0.0 – 3.0 | 0.50 | 조향 PD 비례 게인 |
| Kd | 0.0 – 1.0 | 0.10 | 조향 PD 미분 게인 |
| EMA α | 0.01 – 1.0 | 0.30 | 조향값 EMA 스무딩 계수 |
| Steer Rate | 0.01 – 0.5 | 0.15 | 최대 조향 변화율 (rad/step) |
| Offset Clip | 0.1 – 3.0 | 1.50 | 차선 오프셋 클리핑 범위 |
| Target Spd | 1.0 – 100.0 | 15.0 | 목표 속도 (km/h) |
| BEV Top Crop | 0 – 240 | 80 | BEV 바이너리 상단 N행 마스킹 |
| Min Blob | 0 – 500 | 50 | N픽셀 미만 연결 성분 제거 |
| Search Ratio | 0.1 – 1.0 | 0.50 | 히스토그램 탐색 하단 비율 |
| Min Pixels | 1 – 200 | 30 | 슬라이딩 윈도우 최소 유효 픽셀 수 |

---

### UDP Monitor 탭

`templates/` 폴더의 `.tmpl` 파일을 읽어 UDP 데이터를 동적으로 표시합니다.

- 템플릿 목록에서 항목 선택 후 `▶ Open` → 새 탭으로 열림
- 탭마다 IP / Port / Start / Stop 개별 설정
- xyz / xyzw 연속 필드는 자동으로 한 줄에 묶어 표시
- 열었던 탭 목록과 IP/Port 설정은 재시작 후에도 유지 (`config/monitor_state.json`)

---

### File Playback 탭

CSV 파일의 제어 값을 읽어 시뮬레이터에 FixedStep 단위로 재생합니다.

**CSV 형식:**

| 컬럼 | 설명 |
|------|------|
| `Time [sec]` | 시간 (참고용) |
| `Acc [0~1]` | Throttle 값 |
| `Brk [0~1]` | Brake 값 |
| `SWA [deg]` | Steer Wheel Angle |

**동작 순서 (행마다 반복):**

```
ManualControlById 전송 (fire-and-forget)
    → FixedStep 전송 + ACK 대기
    → SaveData 전송 + ACK 대기
    → 다음 행
```

진행 상황은 프로그레스 바와 카운터(`현재/전체`)로 표시됩니다.
마지막으로 사용한 CSV 경로 / Entity ID는 재시작 후에도 복원됩니다 (`config/fp_state.json`).

---

### AutoCaller (커맨드 패널)

`FixedStep → SaveData` 를 지정 횟수만큼 자동 반복합니다.

```python
# transport/protocol_defs.py
MAX_CALL_NUM                = 2000
AUTO_TIMEOUT_SEC            = 2.0
AUTO_DELAY_BETWEEN_CMDS_SEC = 0.0
```

---

## TCP Commands

### Simulation Time

| msg_type | 커맨드 | 설명 |
|----------|--------|------|
| `0x1101` | GetSimulationTimeStatus | Time Mode, step_index, 시뮬레이션 시각 조회 |
| `0x1102` | SetSimulationTimeModeCommand | `VARIABLE(1)` / `FIXED_DELTA(2)` / `FIXED_STEP(3)` 설정 |

### Fixed Step

| msg_type | 커맨드 | 설명 |
|----------|--------|------|
| `0x1201` | FixedStep | `step_count`만큼 시뮬레이션 tick 진행 |
| `0x1202` | SaveData | 데이터 저장 (`Documents/MORAI SIM/SimulationRes`) |

### Object Control

| msg_type | 커맨드 | 설명 |
|----------|--------|------|
| `0x1301` | CreateObject | entity_type, 위치/회전, 차량 모델 지정 후 생성 |
| `0x1302` | ManualControlById | entity_id 지정, throttle / brake / steer_angle 전송 |
| `0x1303` | TransformControlById | entity_id 지정, 위치/회전/steer_angle 직접 설정 |
| `0x1304` | SetTrajectory | entity_id, follow_mode, waypoint 배열 전송 |

### Suite / Scenario

| msg_type | 커맨드 | 설명 |
|----------|--------|------|
| `0x1401` | ActiveSuiteStatus | Suite 이름, 활성 시나리오, 전체 시나리오 목록 조회 |
| `0x1402` | LoadSuite | `.msuite` 파일 경로 지정 후 Suite 로드 |
| `0x1504` | ScenarioStatus | 현재 시나리오 상태 조회 |
| `0x1505` | ScenarioControl | `PLAY(1)` / `PAUSE(2)` / `STOP(3)` / `PREV(4)` / `NEXT(5)` 제어 |

---

## UDP

### 수신 — Template Parser

`receivers/template_parser.py` 가 `.tmpl` JSON을 읽어 바이너리 패킷을 파싱합니다.

지원 타입: `FLOAT`, `DOUBLE`, `INT32`, `INT64`, `UINT32`, `ENUM`, `STRING`

### 송신

| 포트 | 설명 | Payload |
|------|------|---------|
| `9090` | ManualCommand — throttle, brake, steer | `<ddd` (24 bytes) |

---

## Protocol

### TCP Header (`<BBIIIH`, 16 bytes)

| Field | Type | Size |
|-------|------|------|
| magic_number (`0x4D`) | uint8 | 1 |
| msg_class (`0x01`=REQ / `0x02`=RESP) | uint8 | 1 |
| msg_type | uint32 | 4 |
| payload_size | uint32 | 4 |
| request_id | uint32 | 4 |
| flag | uint16 | 2 |

수신 측은 `0x4D` MAGIC 바이트 기반으로 스트림 동기화(resync)를 수행합니다.

### ResultCode

| result_code | 의미 |
|-------------|------|
| 0 | OK |
| 101 | Invalid State |
| 102 | Invalid Param |
| 200 | Failed |
| 201 | Timeout |
| 202 | Not Supported |
