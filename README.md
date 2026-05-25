# MORAI Sim Control Example Code

MORAI 시뮬레이터를 TCP/UDP로 제어하기 위한 Python 예제 코드입니다.

- `app.py`: DearPyGUI 기반 GUI 예제
- `app_cli.py`: CLI 예제
- `autonomous_driving/`: Path Follow 예제 로직
- `lane_control/`: camera 기반 lane follow와 제어 로직
- `panels/`: DearPyGUI 패널
- `receivers/`: UDP sensor/control receiver
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
- `lane_control/`: lane detection, BEV/preprocess, PD/PI control
- `autonomous_driving/`: Path Follow, trajectory, multi-vehicle 제어
- `config/`: 런타임 상태 저장 파일
- `docs/`: 구조, 워크플로, TCP 인터페이스 문서
- `tools/udp_debug/`: standalone UDP 분석/우회 스크립트 모음

주요 문서:

- [docs/architecture.md](/C:/Dev/MORAI-SimControl_v2.1/docs/architecture.md:1): 구조와 패턴
- [docs/camera-sensor.md](/C:/Dev/MORAI-SimControl_v2.1/docs/camera-sensor.md:1): Camera Sensor / Depth Cam 조사 정리
- [docs/tcp-api.md](/C:/Dev/MORAI-SimControl_v2.1/docs/tcp-api.md:1): TCP API reference
- [docs/workflow.md](/C:/Dev/MORAI-SimControl_v2.1/docs/workflow.md:1): 개발 워크플로

## GUI Tabs

- `UDP Monitor`: `.tmpl` 기반 UDP 데이터 모니터링
- `UDP Control`: `isControl == true` 템플릿 기반 UDP control payload 전송
- `Path Follow`: 경로 기반 자율주행 예제
- `Lane Control`: camera 기반 lane follow 제어
- `Camera Sensor`: RGB / Depth / BBox camera stream 확인
- `File Playback`: CSV 기반 Manual Control 재생
- `Transform Playback`: CSV 기반 Transform Control 재생

## Main Features

### Camera Sensor

Camera stream을 최대 4개 슬롯에서 독립적으로 수신하고 표시합니다.

- template 선택: `Camera RGB.tmpl`, `Camera Depth.tmpl`, `Camera With 2D_3D Bounding Box.tmpl`
- Depth 표시/scale 비교 옵션 제공
- RGB+BBox 모드는 2D/3D bounding box overlay 표시
- 상태 저장: `config/camera_sensor_state.json`
- 상세 내용은 [docs/camera-sensor.md](/C:/Dev/MORAI-SimControl_v2.1/docs/camera-sensor.md:1)를 참고

### Lane Control

Camera frame 기반 차선 인식으로 차량을 제어합니다.

- BEV 변환, 이진화, sliding window 기반 차선 검출
- steering PD 제어와 speed PI 제어
- GUI parameter tuning과 debug frame 확인

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

## API Overview

### TCP API

TCP API 명세는 [transport/message_schema.py](/C:/Dev/MORAI-SimControl_v2.1/transport/message_schema.py:1)를 기준으로 관리합니다.
상세 packet header, payload layout, request/response/notification 목록은 자동 생성 문서인 [docs/tcp-api.md](/C:/Dev/MORAI-SimControl_v2.1/docs/tcp-api.md:1)를 참고합니다.

주요 구현 파일:

- [transport/protocol_defs.py](/C:/Dev/MORAI-SimControl_v2.1/transport/protocol_defs.py:1)
- [transport/tcp_transport.py](/C:/Dev/MORAI-SimControl_v2.1/transport/tcp_transport.py:1)
- [transport/tcp_thread.py](/C:/Dev/MORAI-SimControl_v2.1/transport/tcp_thread.py:1)

### UDP Template API

UDP payload는 `templates/*.tmpl` JSON template을 기준으로 파싱하거나 생성합니다.

- `isControl == false`: `UDP Monitor`와 camera/sensor 수신 계열에서 사용
- `isControl == true`: `UDP Control`에서 입력 폼 생성과 payload 전송에 사용
- template 목록과 control/receive 분리는 [panels/monitor_utils.py](/C:/Dev/MORAI-SimControl_v2.1/panels/monitor_utils.py:1)에서 처리

## API Change Workflow

TCP 인터페이스를 추가하거나 수정할 때는 [docs/tcp-interface-checklist.md](/C:/Dev/MORAI-SimControl_v2.1/docs/tcp-interface-checklist.md:1)를 따릅니다.

기본 검증:

```bash
python tools/gen_tcp_docs.py --check
python -m unittest tests.test_tcp_payloads
```

## Notes

- DearPyGUI UI 변경은 메인 스레드에서만 처리합니다. 백그라운드 스레드에서는 `utils.ui_queue.post()`를 사용합니다.
- viewport resize callback에서는 직접 레이아웃을 바꾸지 않고, 메인 루프에서 dirty flag 기반으로 반영합니다.
- `config/` 아래 상태 파일은 실행 중 자동 생성될 수 있습니다.
- UDP `.tmpl`은 수신용과 control용이 섞여 있을 수 있습니다. `isControl == false`는 `UDP Monitor`, `isControl == true`는 `UDP Control`에서 사용합니다.
