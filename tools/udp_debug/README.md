# UDP Debug Scripts

예제 앱 본체와 분리한 UDP 분석/디버그 스크립트 보관 폴더입니다.

## Files

- `defaults.py`
  - UDP debug 스크립트 공통 기본값
  - 기본 listen IP, RSA/PVD 기본 포트, 기본 buffer size, RSA watch vehicle id, RSA 출력 모드 관리
- `molit8_parser_rsa.py`
  - RSA 관련 기존 스크립트 4개를 하나로 통합한 standalone 도구
  - subcommand:
    - `parse`
    - `record`
    - `bypass`
- `molit8_parser_pvd.py`
  - PVD UDP 도구
  - subcommand:
    - `parse`
    - `bypass`

## Run

```bash
python tools/udp_debug/molit8_parser_rsa.py parse
python tools/udp_debug/molit8_parser_rsa.py record --log-dir logs
python tools/udp_debug/molit8_parser_rsa.py bypass --target 127.0.0.1:50002

python tools/udp_debug/molit8_parser_pvd.py parse
python tools/udp_debug/molit8_parser_pvd.py bypass --target 127.0.0.1:50001
```

## Notes

- 현재 GUI/CLI 예제 프로그램과 직접 연결되지 않습니다.
- receiver/panel 구조로 통합하지 않고 standalone 분석용 스크립트로만 보관합니다.
- RSA 쪽은 원래 아래 4개 파일의 기능을 통합했습니다.
  - `molit8_parser_rsa.py`
  - `molit8_parser_rsa_record.py`
  - `bypass_rsa.py`

## RSA Watch Mode

`molit8_parser_rsa.py`의 watch 동작은 CLI 인자가 아니라 `defaults.py`에서 설정합니다.

주요 상수:

- `RSA_WATCH_VEHICLE_IDS`
  - 감시할 `vehicle_id` 목록
- `RSA_OUTPUT_MODE`
  - `"all"`: 모든 payload 전체 출력
  - `"watch_only"`: 감시 대상 차량 정보만 출력

예시:

```python
RSA_WATCH_VEHICLE_IDS = [1001, 1002]
RSA_OUTPUT_MODE = "watch_only"
```

`parse` / `record` 모드 종료 시에는 아래 요약도 같이 출력합니다.

- 수집 시간 (`Collection time`)
- 중복 ID를 1대로 본 총 고유 차량 수 (`Unique vehicles observed`)
