# Fixed-Step Mode Control Example

TCP/UDP를 통해 MORAI 시뮬레이터와 연동하는 Python 클라이언트 예제입니다.

- **TCP**로 시뮬레이션 시간 모드, Fixed Step, 오브젝트 생성/제어, 시나리오/스위트 관리를 수행합니다.
- **UDP**로 Manual Command 송신, Vehicle Info·Collision Event 수신을 처리합니다.
- `[001] Fixed Step Mode Example` 폴더의 Suite를 MORAI 시뮬레이터에서 불러온 뒤 플레이하면 본 예제와 연동됩니다.

---

## Requirements

- Windows / Linux
- Python 3.8+
- 표준 라이브러리만 사용 (외부 의존성 없음)

---

## Configuration

`protocol_defs.py` 상단의 값을 환경에 맞게 수정합니다.

```python
TCP_SERVER_IP   = "127.0.0.1"
TCP_SERVER_PORT = 20000

UDP_IP          = "127.0.0.1"   # ManualCommand 송신 대상
UDP_PORT        = 9090

UDP_IP_TR       = "127.0.0.1"   # TransformControl 송신 대상
UDP_PORT_TR     = 9094
```

UDP 수신 포트는 각 수신 모듈 상단에서 별도로 설정합니다.

| 모듈 | 상수 | 기본값 |
|---|---|---|
| `vehicle_info_receiver.py` | `VEHICLE_INFO_PORT` | `9092` |
| `collision_event_receiver.py` | `COLLISION_EVENT_PORT` | `9094` |

---

## How To Run

```bash
python example.py
```

UDP 수신기는 독립 실행도 가능합니다.

```bash
python vehicle_info_receiver.py
python collision_event_receiver.py
```

---

## Key Bindings (`example.py`)

| Key | Action | TCP msg_type |
|---|---|---|
| `1` | GetSimulationTimeStatus | `0x1101` |
| `2` | SetSimulationTimeModeCommand (FixedStep, delta=20) | `0x1102` |
| `3` | FixedStep (step_count=1) | `0x1201` |
| `4` | SaveData | `0x1202` |
| `5` | CreateObject (프롬프트 입력) | `0x1301` |
| `6` | ManualControlById (프롬프트 입력) | `0x1302` |
| `7` | TransformControlById (프롬프트 입력) | `0x1303` |
| `8` | SetTrajectory (Car_1, 하드코딩 샘플) | `0x1304` |
| `a` | ScenarioStatus | `0x1504` |
| `b` | ScenarioControl (프롬프트 입력) | `0x1505` |
| `c` | ActiveSuiteStatus | `0x1401` |
| `d` | LoadSuite (하드코딩 경로) | `0x1402` |
| `W` | AutoCaller 토글 (FixedStep ↔ SaveData 반복) | — |
| `Q` | 종료 | — |

---

## Features

### TCP — Simulation Time

| msg_type | 설명 |
|---|---|
| `0x1101` | **GetSimulationTimeStatus** — 현재 Time Mode, step_index, 시뮬레이션 시각 조회 |
| `0x1102` | **SetSimulationTimeModeCommand** — `VARIABLE(1)` / `FIXED_DELTA(2)` / `FIXED_STEP(3)` 설정 |

### TCP — Fixed Step

| msg_type | 설명 |
|---|---|
| `0x1201` | **FixedStep** — `step_count` 만큼 시뮬레이션 tick 진행 |
| `0x1202` | **SaveData** — 데이터 저장 요청. 저장 경로(Windows 기준): `C:\Users\<User>\Documents\MORAI SIM\SimulationRes` |

### TCP — Object Control

| msg_type | 설명 |
|---|---|
| `0x1301` | **CreateObject** — entity_type, 위치/회전, driving_mode, 차량 모델 지정 후 생성 |
| `0x1302` | **ManualControlById** — entity_id 지정, throttle / brake / steer_angle 전송 |
| `0x1303` | **TransformControlById** — entity_id 지정, 위치/회전/steer_angle 직접 설정 |
| `0x1304` | **SetTrajectory** — entity_id, follow_mode, trajectory_name, waypoint 배열 전송 |

### TCP — Suite / Scenario

| msg_type | 설명 |
|---|---|
| `0x1401` | **ActiveSuiteStatus** — 현재 로드된 Suite 이름, 활성 시나리오, 전체 시나리오 목록 조회. 조회 결과는 `b` 키 ScenarioControl의 선택 목록에 자동 반영됨 |
| `0x1402` | **LoadSuite** — `.msuite` 파일 경로를 지정해 Suite 로드 |
| `0x1504` | **ScenarioStatus** — 현재 시나리오 상태(`PLAY` / `PAUSE` / `STOP`) 조회 |
| `0x1505` | **ScenarioControl** — `PLAY(1)` / `PAUSE(2)` / `STOP(3)` / `PREV(4)` / `NEXT(5)` 제어. PLAY 시 시나리오 이름 지정 가능 |

### UDP — 송신 (fire-and-forget)

| 대상 포트 | 설명 | Payload |
|---|---|---|
| `9090` | **ManualCommand** — throttle, brake, steer | `<ddd` (24 bytes) |
| `9094` | **TransformControl** — pos(XYZ), rot(XYZ), steer_angle | `<fffffff` (28 bytes) |

### UDP — 수신

#### VehicleInfo (`9092`) — `vehicle_info_receiver.py`

헤더 없음, Little Endian, 기본 108 bytes + 선택적 wheel 데이터.

| Field | Type | Size |
|---|---|---|
| seconds | int64 | 8 |
| nanos | int32 | 4 |
| id | char[24] | 24 |
| location (XYZ) | float32 × 3 | 12 |
| rotation (RPY) | float32 × 3 | 12 |
| local_velocity (XYZ) | float32 × 3 | 12 |
| local_acceleration (XYZ) | float32 × 3 | 12 |
| angular_velocity (XYZ) | float32 × 3 | 12 |
| control (throttle, brake, steer_angle) | float32 × 3 | 12 |
| *(optional)* wheel_count | int32 | 4 |
| *(optional)* wheel world_loc (XYZ) × wheel_count | float32 × 3 | 12 × N |

wheel 데이터가 없는 패킷도 정상 처리됩니다 (`vehicle_info_with_wheel_receiver.py` 참고).

#### CollisionEvent (`9094`) — `collision_event_receiver.py`

헤더 없음, Little Endian.

**Base** (28 bytes)

| Field | Type | Size |
|---|---|---|
| entity_id | char[24] | 24 |
| collision_object_count | uint32 | 4 |

**Repeat** (112 bytes × count)

| Field | Type | Size |
|---|---|---|
| collision_object_id | char[24] | 24 |
| object_type | uint32 | 4 |
| seconds | int64 | 8 |
| nanos | int32 | 4 |
| location (XYZ) | float32 × 3 | 12 |
| rotation (XYZ) | float32 × 3 | 12 |
| dimensions (L, W, H) | float32 × 3 | 12 |
| velocity (XYZ) | float32 × 3 | 12 |
| acceleration (XYZ) | float32 × 3 | 12 |
| vehicle_spec (overhang_front, overhang_rear, wheel_base) | float32 × 3 | 12 |

---

## Protocol

### TCP Header (`<BBIIIH`, 16 bytes)

| Field | Type | Size |
|---|---|---|
| magic_number (`0x4D`) | uint8 | 1 |
| msg_class (`0x01`=REQ / `0x02`=RESP) | uint8 | 1 |
| msg_type | uint32 | 4 |
| payload_size | uint32 | 4 |
| request_id | uint32 | 4 |
| flag | uint16 | 2 |

수신 측은 `0x4D` MAGIC 바이트 기반으로 스트림 동기화(resync)를 수행합니다.

### ResultCode (`<II`, 8 bytes)

| result_code | 의미 |
|---|---|
| 0 | OK |
| 101 | Invalid State |
| 102 | Invalid Param |
| 200 | Failed |
| 201 | Timeout |
| 202 | Not Supported |

### 가변 길이 문자열 인코딩

TCP payload 내 문자열은 모두 `uint32 length + UTF-8 bytes` 형식입니다.

---

## Architecture

```
example.py
├── RequestIdCounter        — thread-safe request_id 발급
├── tcp_thread.Receiver     — TCP 수신 스레드, pending dict event set
├── automation.AutoCaller   — FixedStep + SaveData 자동 반복 스레드
├── tcp_transport           — 패킷 빌드/파싱/송수신 저수준 함수
├── protocol_defs           — 상수, 포맷 문자열, 크기 정의
├── commands                — UDP 송신 (ManualCommand, TransformControl)
├── input_helper            — 키 프롬프트, 시나리오 목록 캐시
└── key_input               — 플랫폼별 raw 키 입력 (Windows msvcrt / Unix termios)

vehicle_info_receiver.py            — VehicleInfo UDP 독립 수신기
vehicle_info_with_wheel_receiver.py — VehicleInfo + Wheel 확장 수신기
collision_event_receiver.py         — CollisionEvent UDP 독립 수신기
```

### AutoCaller (`W` 토글)

`automation.AutoCaller`는 `FixedStep → SaveData`를 `MAX_CALL_NUM`(기본 2000)회 반복합니다. 각 요청은 `pending` dict의 `threading.Event`로 동기화되며, `AUTO_TIMEOUT_SEC`(기본 2.0초) 초과 시 중단됩니다. `protocol_defs.py`에서 아래 값을 조정합니다.

```python
MAX_CALL_NUM                = 2000
AUTO_TIMEOUT_SEC            = 2.0
AUTO_DELAY_BETWEEN_CMDS_SEC = 0.0
```