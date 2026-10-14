# RDOP Mock Scripts

RDOP 서버 없이 시뮬레이터의 RDOP REST 연동(관제 / 이력 재생 / 미시 시뮬레이션 / 결과 통보)을 점검하는 스크립트입니다.
명세: RDOP-MORAI 시뮬레이션 API 인터페이스 정의서 (개정 1.1). Python 3.7+, 표준 라이브러리만 사용.

## Files

- `rdop_mock_server.py`
  - 명세 01~04 를 흉내내는 서버 + 콘솔로 큐 적재
  - pop 은 FIFO 1건(200) 후 큐에서 제거, 비면 204
  - 경로 스타일
    - `nas` (기본): 실제와 같은 `/nas/...` 경로를 보냄
    - `nas` + `--stage-root <폴더>`: 경로는 `/nas/...` 그대로, 파일 준비(출력 폴더 생성, `--macro-file` 복사)와 결과 파일 확인은 `<폴더>` 를 `/nas` 로 보고 수행
    - `local`: `--nas-root` 아래의 이 PC 경로를 그대로 보냄
- `rdop_target.py`
  - 시뮬레이터 인터페이스 JSON(`Content/NetworkInterface/{Monitoring,Traffic}`)의 `destinationAddr` 를 `local` / `dev` / `prod` / `<ip>:<port>` 로 전환
  - 인자 없이 실행하면 현재 값 표시
  - 시뮬레이터 저장소 위치: `--sim-root <경로>` 또는 환경 변수 `MORAI_SIM_ROOT`
  - `CameraLocationPost` 는 RDOP 가 아니라 건드리지 않음

## Run

```bash
# 1. 시뮬레이터 인터페이스를 모의 서버로 (끝나면 반드시 dev 로 되돌릴 것 - git 추적 파일)
python tools/rdop_mock/rdop_target.py local --sim-root D:/Dev/clone_morai_world_ue5.8

# 2. 모의 서버 (NAS 경로 매핑까지 확인)
python tools/rdop_mock/rdop_mock_server.py --stage-root //10.100.100.5/log_storage/rdop_test --macro-file <anmroutes 파일>

# 3. 되돌리기
python tools/rdop_mock/rdop_target.py dev --sim-root D:/Dev/clone_morai_world_ue5.8
```

시뮬레이터 쪽 설정 (에디터 콘솔 또는 `Engine.ini` 의 `[SystemSettings]`):

```
Rdop.NasRoot \\10.100.100.5\log_storage\rdop_test
```

`--stage-root` 와 `Rdop.NasRoot` 를 같은 폴더로 맞추면 `/nas/...` 경로 변환 → NAS 에서 거시 파일 읽기 → 결과 CSV 복사 → 결과 POST 까지 한 번에 확인됩니다.
인터페이스 JSON 은 모드 진입 시 읽으므로 `rdop_target.py` 실행 후 모드를 다시 들어가야 합니다.

## Console

| 명령 | 내용 |
|------|------|
| `cam [lon lat]` | 관제 카메라 위치 적재 (기본 126.83 37.2) |
| `sim [area hour]` | 미시 시뮬레이션 작업 적재 (기본 1 12) |
| `simset key=value ...` | 필드를 지정해 작업 적재. keys: `id area hour macro out` |
| `rec <id> [lon lat]` | 결과가 접수된 실행의 이력 재생 적재 |
| `recpath <path> [id]` | 임의 경로로 이력 재생 적재 (이력 확인 생략) |
| `fail <cam\|rec\|sim\|result> <status>` | 해당 API 다음 응답을 지정 상태로 (예: 500, 409) |
| `status` | 큐, 결과 대기 작업, 접수된 결과 표시 |

## 시뮬레이터 로그

로그 창에서 `[RdopRest]` 로 필터. 미시 시뮬레이션 정상 순서:

`job received (readable=1, exists=1)` → `imported` → `Generated` → `starting scenario` → `run started` → (종료) `copying result` → `SimulationResultPost Req` → `Result accepted`
