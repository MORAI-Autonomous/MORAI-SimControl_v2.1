# 개발 워크플로

## 기본 순서

1. 요청 파악
   관련 파일과 함수 위치를 먼저 찾습니다.

2. 변경 범위 축소
   최소 수정으로 끝낼 수 있는지 먼저 봅니다.

3. 구현
   기존 파일은 먼저 읽고, 그 다음 수정합니다.

4. 규칙 확인
   - `from __future__ import annotations`
   - background thread UI 변경 시 `ui_queue.post()`
   - DearPyGUI ASCII 라벨 규칙
   - panel의 `init(callback)` 패턴

5. 검증
   문법 확인, 관련 테스트, 필요한 문서 갱신

---

## 반복 실수 목록

| 상황 | 잘못된 접근 | 올바른 접근 |
|---|---|---|
| background thread에서 UI 변경 | `dpg.set_value()` 직접 호출 | `ui_queue.post()` |
| Python 3.8 타입힌트 | 최신 문법 가정 | `from __future__ import annotations` |
| DearPyGUI 탭 | `add_tab_bar` 남용 | 버튼 + show/hide |
| 버튼 라벨 | 유니코드 아이콘 사용 | ASCII 텍스트 사용 |
| panel 의존성 | `app.py` import | `init(callback)` |
| 동적 UI 태그 접근 | 존재 가정 | `does_item_exist()` 체크 |
| 대용량 파일 읽기 | 처음부터 끝까지 전부 읽기 | 위치 검색 후 필요한 부분만 읽기 |
| 매 tick 로그 출력 | `log.append()` 남발 | `status_cb` + `set_value()` |

---

## TCP API 작업 순서

TCP 인터페이스 변경 시 권장 순서:

1. `src/transport/message_schema.py` 수정
2. `python tools/gen_tcp_docs.py`
3. `python tools/gen_tcp_docs.py --check`
4. `python -m unittest tests.test_tcp_payloads`

`docs/tcp-api.md`는 generated file이므로 직접 고치지 않습니다.

---

## RTF 분석 메모

Fixed Step 성능 이슈는 클라이언트와 시뮬레이터 사이 구간을 분리해서 봐야 합니다.

클라이언트 쪽에서 먼저 볼 항목:

- 과도한 TCP 송수신 로그
- 매 tick `log.append()` 사용
- O(n) 경로 탐색
- 불필요한 callback 체인

서버 쪽 병목은 별도 분석 문서에서 봅니다.
