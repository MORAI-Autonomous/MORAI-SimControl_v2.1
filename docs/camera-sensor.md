# Camera Sensor Panel

이 문서는 `Camera Sensor` 패널의 현재 상태와 Depth Camera 송수신 조사 결과를 정리합니다.

## 목적

`Camera Sensor` 패널은 Lane Control과 분리된 camera stream 확인용 패널입니다.

- RGB camera 수신 확인
- Depth camera 수신/시각화 확인
- Semantic camera 수신/시각화 확인
- Instance camera 수신/시각화 확인
- RGB + 2D/3D bounding box overlay 확인
- 최대 4개 sensor slot 독립 실행

## 주요 파일

- [panels/camera_sensor_panel.py](../panels/camera_sensor_panel.py)
- [receivers/camera_receiver.py](../receivers/camera_receiver.py)
- [receivers/camera_depth_receiver.py](../receivers/camera_depth_receiver.py)
- [receivers/camera_semantic_receiver.py](../receivers/camera_semantic_receiver.py)
- [receivers/camera_sensor_receiver.py](../receivers/camera_sensor_receiver.py)

## Templates

현재 Camera Sensor 패널에서 선택하는 template은 5개입니다.

- 위치: `templates/camera/`
- `Camera RGB.tmpl`
- `Camera Depth.tmpl`
- `Camera Semantic.tmpl`
- `Instance Cam.tmpl`
- `Camera With 2D_3D Bounding Box.tmpl`

예전 이름으로 저장된 상태값은 패널에서 새 이름으로 정규화합니다.

- `Camera Template.tmpl` -> `Camera RGB.tmpl`
- `Camera Depth Template.tmpl` -> `Camera Depth.tmpl`
- `CameraSensorMessageTemplate.tmpl` -> `Camera With 2D_3D Bounding Box.tmpl`
- `CameraWithBboxMessageTemplate.tmpl` -> `Camera With 2D_3D Bounding Box.tmpl`

## Panel UI

각 slot은 아래 값을 가집니다.

- `Template`: RGB / Depth / Semantic / Instance / BBox template 선택
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

Depth Cam 송수신 테스트에서 클라이언트 수신 화면, 클라이언트 `_visualize_depth()` 저장 PNG, 시뮬레이터 `SaveDepthAsPng()` 저장 PNG, 시뮬레이터 viewport 화면이 서로 다르게 보이는 문제가 있었습니다.

확인된 점:

- UDP 수신은 안정적으로 동작합니다.
- frame size는 640 x 480으로 정상 수신됩니다.
- FPS도 26~27 수준으로 안정적입니다.
- `Depth View=Turbo`, `Scale=Raw 32FC1` 조건에서도 클라이언트 저장 PNG와 시뮬레이터 저장 PNG의 색감 차이가 남았습니다.
- 클라이언트 GUI resize/display 경로가 아니라, 저장 PNG끼리 비교해도 차이가 확인됐습니다.

따라서 byte order, step, payload size, frame reshape 문제 가능성은 낮습니다.

현재 가장 유력한 결론:

- 클라이언트 수신/파싱과 `_visualize_depth()` 수식 문제 가능성은 낮습니다.
- 시뮬레이터 `SaveDepthAsPng()`의 C++ `TurboLUT` 고인덱스 구간이 현재 Python OpenCV `cv2.COLORMAP_TURBO`와 다릅니다.
- 고인덱스 `240~255` 구간에서 시뮬레이터 LUT가 더 어두운 값을 사용해 가까운 영역이 검게 뭉치고 horizontal band가 도드라지는 현상을 설명합니다.
- 시뮬레이터 viewport는 별도 depth visualization / post-process 경로일 수 있으므로 저장 PNG와 직접 동일해야 하는 기준으로 보지 않습니다.

클라이언트 환경에서 확인한 OpenCV Turbo RGB 예시:

```text
240 = (169, 22, 1)
243 = (161, 18, 1)
247 = (149, 13, 1)
252 = (133, 7, 2)
255 = (122, 4, 3)
```

## Recommended Direction

권장 해결 방향은 시뮬레이터 저장 코드의 LUT 교체입니다.

- Python OpenCV `cv2.COLORMAP_TURBO`에서 256개 RGB 값을 추출
- 시뮬레이터 `SaveDepthAsPng()`의 `TurboLUT[256][3]` 전체 교체
- 같은 scene/frame 조건에서 클라이언트 `_visualize_depth()` debug PNG와 시뮬레이터 저장 PNG 재비교

추가 확인 후보:

- sky/far pixel이 `0`인지, `200+` 또는 far clip 값인지 확인
- 시뮬레이터 viewport와 저장 PNG가 서로 다른 visualization 경로인지 확인

클라이언트에는 `_save_depth_visual_debug()` helper가 남아 있지만 기본 실행은 비활성화되어 있습니다. 필요할 때 `_on_depth_packet()`의 주석 처리된 호출을 되살려 저장 PNG 비교에 사용합니다.

## Semantic / Instance

Semantic과 Instance camera는 공통 segmentation receiver를 사용합니다.

- encoded image payload는 `cv2.imdecode()`로 처리
- raw `BGRA8`, `RGB8`, `LABEL8` 계열 payload를 fallback으로 처리
- `LABEL8`은 OpenCV Turbo color map으로 시각화
- step / image_size 필드 순서를 template 기준으로 검증

현재 상태:

- `Camera Semantic.tmpl` 수신/렌더링 확인 완료
- `Instance Cam.tmpl` 수신/렌더링 확인 완료

## Current Status

현재 완료된 항목:

- Depth test panel 기능을 Camera Sensor 패널로 통합
- RGB / Depth / Semantic / Instance / BBox template 선택 지원
- RGB / Depth / Semantic / Instance 타입별 송수신 및 데이터 표시 검증
- Depth simulator / grayscale / turbo 표시 모드 선택 지원
- Depth scale 비교 모드 추가
- raw range와 변환 후 depth range 표시
- Camera Sensor 내부 중첩 스크롤 제거
- 클라이언트 Depth render 원본 PNG 저장 helper 추가, 기본 비활성화
- 시뮬레이터 저장 PNG와 클라이언트 저장 PNG 색감 차이의 주요 원인을 C++ TurboLUT 불일치로 정리

남은 항목:

- 시뮬레이터 `SaveDepthAsPng()` TurboLUT를 Python OpenCV 기준 값으로 교체
- LUT 교체 후 클라이언트 debug PNG와 simulator PNG 재비교
- sky/far pixel 처리 기준 확정
- 필요 시 Depth display 기본값 재결정

## Validation

관련 파일 수정 후 최소 검증:

```bash
python -m py_compile panels/camera_sensor_panel.py receivers/camera_depth_receiver.py receivers/camera_receiver.py receivers/camera_semantic_receiver.py receivers/camera_sensor_receiver.py
```
