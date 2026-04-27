# MORAI Sim Control Example Code

MORAI 시뮬레이터를 TCP/UDP로 제어하기 위한 Python 예제 코드입니다.

- `app.py`: DearPyGUI 기반 GUI 예제
- `app_cli.py`: CLI 예제
- `autonomous_driving/`: Path Follow 예제 로직
- `transport/`: TCP 요청/응답, 프로토콜 정의, 수신 스레드

## Requirements

- Windows 10/11 또는 Linux
- Python `3.8+`

주요 패키지:

- `dearpygui`
- `numpy`
- `opencv-python`
- `Pillow` 선택

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
app.py
app_cli.py
ad_runner.py
step_ad_runner.py
lane_runner.py

autonomous_driving/
config/
docs/
panels/
receivers/
templates/
tests/
tools/
transport/
utils/
```

주요 디렉터리:

- `transport/`: TCP packet builder/parser, request/response schema, receiver thread
- `receivers/`: UDP receiver와 `.tmpl` 기반 parser
- `panels/`: DearPyGUI 패널
- `autonomous_driving/`: Path Follow, trajectory, multi-vehicle 제어
- `config/`: 런타임 상태 저장 파일
- `docs/`: 구조, 워크플로, TCP 인터페이스 문서

## GUI Tabs

- `UDP Monitor`: `.tmpl` 기반 UDP 데이터 모니터링
- `Path Follow`: 경로 기반 자율주행 예제
- `File Playback`: CSV 기반 Manual Control 재생
- `Transform Playback`: CSV 기반 Transform Control 재생

## Main Features

### Path Follow

MGeo 또는 CSV 경로를 기준으로 차량을 추종합니다.

- Fixed / Fixed Step 모드 지원
- 다중 차량 지원
- 차량별 path, entity id, vehicle info port 설정 가능
- collision scenario용 target/chaser 설정 지원

### File Playback

CSV에서 throttle, brake, steer 값을 읽어 순차적으로 재생합니다.

주요 컬럼:

- `Time [sec]`
- `Acc [0~1]`
- `Brk [0~1]`
- `SWA [deg]`

### Transform Playback

CSV에서 transform과 steer, speed를 읽어 `TransformControlById`를 순차 전송합니다.

- multi-vehicle 지원, 기본 2대
- 상태 저장: `config/tfp_state.json`
- `FixedStep` 없이 timestamp 간격 기준 재생

필수 컬럼:

- `location.x/y/z`
- `rotation.x/y/z`
- `steer angle`
- `local_velocity.x/y`

속도 계산:

```text
speed = sqrt(local_velocity.x^2 + local_velocity.y^2)
```

현재 `Vehicle Info` CSV의 velocity 단위는 `m/s` 기준으로 사용합니다.

## TCP API Workflow

TCP 인터페이스 작업은 [transport/message_schema.py](/C:/Dev/MORAI-SimControl_v2.1/transport/message_schema.py:1)부터 시작합니다.

- request/response 필드 변경은 먼저 `message_schema.py`에서 수정
- `python tools/gen_tcp_docs.py`로 [docs/tcp-api.md](/C:/Dev/MORAI-SimControl_v2.1/docs/tcp-api.md:1) 재생성
- `python tools/gen_tcp_docs.py --check`로 schema, docs, protocol 검증
- `python -m unittest tests.test_tcp_payloads`로 대표 payload/parser 회귀 확인

상세 체크리스트는 [docs/tcp-interface-checklist.md](/C:/Dev/MORAI-SimControl_v2.1/docs/tcp-interface-checklist.md:1)를 참고하면 됩니다.

## TCP Commands

Simulation Time:

- `0x1101` `GetSimulationTimeStatus`
- `0x1102` `SetSimulationTimeModeCommand`

Fixed Step:

- `0x1201` `FixedStep`
- `0x1202` `SaveData`

Object Control:

- `0x1301` `CreateObject`
- `0x1302` `ManualControlById`
- `0x1303` `TransformControlById`
- `0x1304` `SetTrajectory`

Suite / Scenario:

- `0x1401` `ActiveSuiteStatus`
- `0x1402` `LoadSuite`
- `0x1504` `ScenarioStatus`
- `0x1505` `ScenarioControl`

상세 필드 정의는 [docs/tcp-api.md](/C:/Dev/MORAI-SimControl_v2.1/docs/tcp-api.md:1)에서 자동 생성됩니다.

## Notes

- DearPyGUI UI 변경은 메인 스레드에서만 처리합니다. 백그라운드 스레드에서는 `utils.ui_queue.post()`를 사용합니다.
- viewport resize callback에서는 직접 레이아웃을 바꾸지 않고, 메인 루프에서 dirty flag 기반으로 반영합니다.
- `config/` 아래 상태 파일은 실행 중 자동 생성될 수 있습니다.
