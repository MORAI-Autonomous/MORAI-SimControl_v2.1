# Camera Sensor Panel

이 문서는 `Camera Sensor` 패널의 현재 상태와 Depth Camera 송수신 조사 결과를 정리합니다.

## 목적

`Camera Sensor` 패널은 Lane Control과 분리된 camera stream 확인용 패널입니다.

- RGB camera 수신 확인
- Depth camera 수신/시각화 확인
- RGB + 2D/3D bounding box overlay 확인
- 최대 4개 sensor slot 독립 실행

## 주요 파일

- [panels/camera_sensor_panel.py](/C:/Dev/MORAI-SimControl_v2.1/panels/camera_sensor_panel.py:1)
- [receivers/camera_receiver.py](/C:/Dev/MORAI-SimControl_v2.1/receivers/camera_receiver.py:1)
- [receivers/camera_depth_receiver.py](/C:/Dev/MORAI-SimControl_v2.1/receivers/camera_depth_receiver.py:1)
- [receivers/camera_sensor_receiver.py](/C:/Dev/MORAI-SimControl_v2.1/receivers/camera_sensor_receiver.py:1)

## Templates

현재 Camera Sensor 패널에서 선택하는 template은 3개입니다.

- `Camera RGB.tmpl`
- `Camera Depth.tmpl`
- `Camera With 2D_3D Bounding Box.tmpl`

예전 이름으로 저장된 상태값은 패널에서 새 이름으로 정규화합니다.

- `Camera Template.tmpl` -> `Camera RGB.tmpl`
- `Camera Depth Template.tmpl` -> `Camera Depth.tmpl`
- `CameraSensorMessageTemplate.tmpl` -> `Camera With 2D_3D Bounding Box.tmpl`
- `CameraWithBboxMessageTemplate.tmpl` -> `Camera With 2D_3D Bounding Box.tmpl`

## Panel UI

각 slot은 아래 값을 가집니다.

- `Template`: RGB / Depth / BBox template 선택
- `Depth View`: `Simulator`, `Grayscale`, `Turbo`
- `Scale`: `MORAI 0-255`, `Raw 32FC1`
- `IP`, `Port`
- `Start`, `Stop`
- FPS, frame size, type, info, last RX 표시

상태 파일:

- `config/camera_sensor_state.json`

스크롤은 app의 `cam_sensor_scroll` 하나가 담당합니다. Camera Sensor 패널 내부의 전체 child window는 사용하지 않고, slot card의 내부 스크롤도 비활성화합니다.

## Threading Rule

receiver thread에서 DearPyGUI API를 직접 호출하지 않습니다.

- receiver callback에서 frame/packet 처리
- texture/UI 갱신은 `utils.ui_queue.post()`로 main thread에 전달

## Depth Payload Parsing

Depth receiver는 `Camera Depth.tmpl` 구조에 맞춰 payload를 해석합니다.

필드:

- width
- height
- encoding
- is bigendian
- image size
- step
- image data

현재 지원 encoding:

- `32FC1`

현재 receiver는 아래 조건을 검증합니다.

- width / height > 0
- encoding == `32FC1`
- little-endian only
- step == width * 4
- image_size == width * height * 4

수신된 image data는 `float32` 배열로 읽습니다.

```text
depth_raw = np.frombuffer(image_bytes, dtype="<f4").reshape((height, width))
```

## Depth Scale Modes

Depth Cam 조사 중 raw 값의 의미가 명확하지 않아 두 가지 scale mode를 유지합니다.

### MORAI 0-255

기존 해석 방식입니다.

```text
depth_m = depth_raw * (200.0 / 255.0)
```

시뮬레이터가 0~255 계열로 encoding한 값을 보낸다고 가정합니다.

### Raw 32FC1

수신한 `32FC1` 값을 meter 단위 선형 depth로 가정합니다.

```text
depth_m = depth_raw
```

ROS의 일반적인 `32FC1` depth image 관례에 가까운 해석입니다.

## Depth Camera Investigation

Depth Cam 송수신 테스트에서 클라이언트 수신 화면과 시뮬레이터 내부 화면이 다르게 보이는 문제가 있었습니다.

확인된 점:

- UDP 수신은 안정적으로 동작합니다.
- frame size는 640 x 480으로 정상 수신됩니다.
- FPS도 26~27 수준으로 안정적입니다.
- raw range는 예시 기준 약 `1.0~242.0`으로 관측됐습니다.
- `MORAI 0-255`와 `Raw 32FC1` scale을 바꿔도 화면 구조 차이는 거의 없고, 숫자 range만 달라졌습니다.

따라서 byte order, step, payload size, frame reshape 문제 가능성은 낮습니다.

현재 가장 유력한 결론:

- 클라이언트 수신/파싱 문제라기보다, 시뮬레이터가 depth를 전송하기 전에 화면 표시용 post-process가 적용된 값을 보내고 있을 가능성이 큽니다.
- `32FC1`이라는 이름과 달리, 실제 payload가 선형 meter depth가 아닐 수 있습니다.

의심되는 시뮬레이터 pipeline:

```text
linear depth
-> tone curve / post-processing / local exposure / bloom
-> gamma 2.2
-> 0~255 계열 encoding
-> UDP payload
```

이 경우 클라이언트에서 `depth_raw * 200 / 255`로 선형 복원한다고 가정해도 물리적으로 정확한 depth가 되지 않습니다. 현재 클라이언트 화면은 시뮬레이터 표시 화면을 시각적으로 비슷하게 맞춘 상태에 가깝습니다.

## Recommended Direction

권장 해결 방향은 시뮬레이터 수정입니다.

- DepthCamera 송신 경로에서 post-process 비활성화
- ToneCurve, LocalExposure, Bloom, gamma 등 화면 표시용 처리를 제거
- semantic / instance camera처럼 raw buffer 기반 값을 송신
- `32FC1`을 유지한다면 meter 단위 선형 depth로 송신

클라이언트 역보정은 차선입니다.

- gamma 역변환은 가능하지만 충분하지 않을 수 있습니다.
- ACES / tone curve 역변환은 부정확하고 engine setting에 의존합니다.
- 시뮬레이터 표시 설정이 바뀌면 클라이언트 보정도 다시 틀어질 수 있습니다.

## Current Status

현재 완료된 항목:

- Depth test panel 기능을 Camera Sensor 패널로 통합
- RGB / Depth / BBox template 선택 지원
- Depth simulator / grayscale / turbo 표시 모드 선택 지원
- Depth scale 비교 모드 추가
- raw range와 변환 후 depth range 표시
- Camera Sensor 내부 중첩 스크롤 제거
- 클라이언트 화면이 시뮬레이터 화면과 얼추 비슷하게 보이는 수준까지 조정

남은 항목:

- 시뮬레이터 DepthCamera 송신 경로 확인
- post-process 없는 선형 depth 송신 방식 확정
- 클라이언트 scale mode 기본값 재결정
- 필요 시 display range, gamma, color map 옵션 추가

## Validation

관련 파일 수정 후 최소 검증:

```bash
python -m py_compile panels/camera_sensor_panel.py receivers/camera_depth_receiver.py receivers/camera_receiver.py receivers/camera_sensor_receiver.py
```
