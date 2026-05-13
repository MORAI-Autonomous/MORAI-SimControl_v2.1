# TCP Interface Checklist

이 문서는 TCP 인터페이스를 새로 추가하거나 기존 구조를 수정할 때의 작업 순서를 정리합니다.

## Source Of Truth

- 시작점은 항상 [transport/message_schema.py](/C:/Dev/MORAI-SimControl_v2.1/transport/message_schema.py:1) 입니다.
- request/response 필드, 반복 필드, 설명을 먼저 여기서 수정합니다.
- 문서와 일부 helper 검증은 이 파일을 기준으로 생성됩니다.

## 신규 인터페이스 추가

1. [transport/message_schema.py](/C:/Dev/MORAI-SimControl_v2.1/transport/message_schema.py:1)에 request `MessageSpec` 추가
2. response가 있으면 `RESPONSE_MESSAGES`에도 추가
3. [transport/protocol_defs.py](/C:/Dev/MORAI-SimControl_v2.1/transport/protocol_defs.py:1)에 `MSG_TYPE_*`와 필요한 format/size 상수 추가
4. [transport/tcp_transport.py](/C:/Dev/MORAI-SimControl_v2.1/transport/tcp_transport.py:1)에 send 함수와 payload builder 추가
5. response parser가 필요하면 같은 파일에 parser 추가
6. 앱 로직에서 response를 직접 처리해야 하면 [transport/tcp_thread.py](/C:/Dev/MORAI-SimControl_v2.1/transport/tcp_thread.py:1)에 분기 추가
7. panel, runner, CLI 같은 실제 호출부 연결

## 기존 인터페이스 수정

1. [transport/message_schema.py](/C:/Dev/MORAI-SimControl_v2.1/transport/message_schema.py:1) 수정
2. [transport/protocol_defs.py](/C:/Dev/MORAI-SimControl_v2.1/transport/protocol_defs.py:1) 반영 확인
3. [transport/tcp_transport.py](/C:/Dev/MORAI-SimControl_v2.1/transport/tcp_transport.py:1) send/parser 수정
4. [transport/tcp_thread.py](/C:/Dev/MORAI-SimControl_v2.1/transport/tcp_thread.py:1) 처리/로그 갱신
5. 실제 호출부가 새 필드를 모두 전달하는지 확인

## Validation

- `python tools/gen_tcp_docs.py`
- `python tools/gen_tcp_docs.py --check`
- `python -m unittest tests.test_tcp_payloads`

## Rule Of Thumb

- 명세 변경은 항상 `message_schema.py`부터 시작합니다.
- request payload가 바뀌면 builder와 golden payload test를 같이 봅니다.
- response payload가 바뀌면 parser와 `tcp_thread.py` 처리도 같이 봅니다.
- `docs/tcp-api.md`는 생성물로 유지합니다.
