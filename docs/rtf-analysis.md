# Fixed Step RTF 분석 메모

이 문서는 Fixed Step 모드에서 RTF(Real-Time Factor)가 낮게 나올 때, 어느 구간이 병목인지 구분하기 위한 메모입니다.

## 기본 개념

- `RTF = simulated_time / wall_clock_time`
- `1.0`이면 실시간과 동일
- `1.0`보다 작으면 시뮬레이션이 실제 시간보다 느림

## 관찰 포인트

Fixed Step 계열에서는 다음 구간을 나눠서 봐야 합니다.

1. 시뮬레이터가 step을 실제로 처리하는 시간
2. 응답 패킷이 클라이언트로 오는 시간
3. 클라이언트가 응답을 해석하고 다음 command를 보내는 시간

## 클라이언트 쪽에서 먼저 볼 것

- 과도한 송수신 로그
- 매 tick `log.append()` 호출
- O(n) 경로 탐색
- callback chain 과다
- 불필요한 파일 I/O

## 개선 방향 예시

### 로그 줄이기

- 정상 응답은 전부 출력하지 않기
- Manual/Transform 계열의 매 tick 로그 줄이기
- 상태 갱신은 `set_value()` 중심으로 전환

### 탐색 캐시

- waypoint cache
- lookahead index cache

### batching / pipeline

- 가능하면 `step_count` 배치 증가 검토
- 응답 대기와 다음 command 준비 구간 분리 검토

## 결론

RTF 이슈는 항상 서버 문제 또는 클라이언트 문제 하나로 단정하지 말고,  
`server step time`과 `client turnaround time`을 분리해서 봐야 합니다.
