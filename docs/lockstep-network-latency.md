# Lockstep Network Latency

## FixedStep 타임스탬프 확장

Fixed + UserControl(락스텝) 모드의 지연을 클라이언트 처리 시간과 네트워크 전송 시간으로 분리하기 위해 FixedStep 명령(`0x1201`)에 클라이언트 타임스탬프 두 개를 추가한다.

### Payload

```text
[uint32 step_count][uint8 save_mode][uint64 client_recv_ns][uint64 client_send_ns]
```

- 전체 크기: 21 bytes
- byte order: little-endian
- Python struct format: `<IBQQ`

| 필드 | 타입 | 캡처 시점 |
|---|---|---|
| `step_count` | `uint32` | 실행할 simulation step 수 |
| `save_mode` | `uint8` | 스텝 저장 방식 |
| `client_recv_ns` | `uint64` | 직전 FixedStep 응답 payload를 모두 수신한 직후 |
| `client_send_ns` | `uint64` | 이번 FixedStep 요청을 전송하기 직전 |

`save_mode` 값은 다음과 같다.

| 값 | 이름 | 동작 |
|---:|---|---|
| `0` | `SAVE_MODE_SKIP` | 해당 스텝을 저장하지 않음. 하위 호환 기본값 |
| `1` | `SAVE_MODE_DEFAULT` | 인터페이스 저장 옵션을 따름. 기존 SaveDataCommand와 동일 |
| `2` | `SAVE_MODE_FORCE` | 인터페이스 저장 옵션과 관계없이 모두 저장 |

필드 배치는 방식 A를 사용한다.

- offset 0: `step_count` (4 bytes)
- offset 4: `save_mode` (1 byte)
- offset 5: `client_recv_ns` (8 bytes)
- offset 13: `client_send_ns` (8 bytes)

파서는 4바이트 payload에서 `step_count`, 5바이트 이상에서 `save_mode`, 21바이트 이상에서 두 echo 타임스탬프를 읽을 수 있다.

두 타임스탬프는 동일한 클라이언트 monotonic clock을 사용한다. 현재 Python 구현은 `time.perf_counter_ns()`를 사용한다. 시뮬레이터는 두 값의 차이만 사용하므로 시뮬레이터와 클라이언트 사이의 시계 동기화는 필요하지 않다.

첫 FixedStep 요청은 직전 응답이 없으므로 `client_recv_ns`와 `client_send_ns`를 같은 값으로 전송한다. 이때 클라이언트 처리 시간은 0으로 해석할 수 있다.

기존 4바이트 payload도 시뮬레이터에서 계속 허용하므로 하위 호환된다.

## 현재 클라이언트 전송 순서

StepAD에서 UDP VehicleInfo와 Save Mode를 사용하는 경우의 순서는 다음과 같다.

```text
FixedStep 전송
→ FixedStep ACK 대기
→ VehicleInfo 수신 대기
→ 제어 명령 전송
→ 다음 FixedStep 전송
```

StepAD는 별도의 SaveDataCommand를 보내지 않는다. UI에서 선택한 Save Mode가 각 FixedStep 명령에 포함된다. Save Mode는 저장 정책만 결정하며 VehicleInfo 수신 여부에는 영향을 주지 않는다. `SKIP`, `DEFAULT`, `FORCE` 모두 FixedStep을 보내기 전에 VehicleInfo 수신 이벤트를 초기화하고, ACK 후 해당 Step의 VehicleInfo와 제어 처리를 마친 뒤 다음 FixedStep을 보낸다.

Commands 패널의 단발 FixedStep과 AutoCaller도 같은 Save Mode 콤보를 사용한다. 두 경로 모두 별도 SaveDataCommand를 보내지 않으며, AutoCaller는 매 반복에서 Save Mode가 포함된 FixedStep ACK 하나만 기다린다.

## TCP socket 옵션

메인 GUI, CLI, Lightweight GUI 및 독립 Autonomous Driving Runner의 TCP 소켓은 연결 전에 다음 옵션을 적용한다.

```python
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
```

따라서 주요 FixedStep 경로에서는 Nagle 알고리즘이 비활성화되어 있다. 다만 `TCP_NODELAY`는 연속된 `sendall()` 호출이 반드시 별도의 TCP segment로 전달되는 것을 보장하지 않는다.
