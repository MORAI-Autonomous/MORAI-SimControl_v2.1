# MCP 설정 가이드

이 프로젝트는 기본적으로 로컬 파일, TCP/UDP 소켓, DearPyGUI 중심으로 동작합니다.  
따라서 불필요한 MCP를 많이 켜 둘 필요는 없습니다.

## 권장 방향

- 기본 로컬 도구만으로 충분하면 MCP를 최소화합니다.
- 프로젝트와 직접 관계없는 브라우저, 메신저, 노트북 계열 MCP는 비활성화해도 됩니다.

## 비활성화 후보

- Slack
- Browser / Chrome
- Jupyter / Notebook
- 프로젝트와 무관한 외부 서비스 연동

## 설정 위치 예시

### 전역 설정

Windows:

```text
%APPDATA%\Claude\claude_desktop_config.json
```

macOS:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

예시:

```json
{
  "mcpServers": {
    "slack": { "disabled": true }
  }
}
```

### 프로젝트별 설정

```json
{
  "enabledMcpServers": []
}
```

## 효과

MCP를 최소화하면:

- 불필요한 tool 탐색이 줄고
- 입력 컨텍스트가 가벼워지고
- 응답 속도가 조금 더 안정적일 수 있습니다.
