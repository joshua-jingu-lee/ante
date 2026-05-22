# D-018: Core Interface CLI/IPC 중심화 (2026-05-22)

> Ante 설계 결정 기록.
> 인덱스: [README.md](README.md)

**결정**: Ante 1.0의 활성 운영 인터페이스는 CLI와 Unix domain socket IPC로 둔다. 브라우저 UI, HTTP REST 서버, 세션 쿠키 기반 로그인은 코어 런타임에서 제거한다.

**구성**:
- 사용자/Agent 입력: `ante` CLI
- 서버 실행 중 mutation/read: IPC command registry
- 내부 통신: 서비스 직접 호출 + EventBus
- 외부 브로커 통신: APIGateway / BrokerAdapter의 증권사 REST·WebSocket

**근거**:
- 홈서버 개인 운용 환경에서 Python 단일 런타임만 요구하도록 배포 표면을 줄인다.
- 사용자와 Agent가 같은 구조화 출력(JSON)과 같은 권한 체계를 쓰도록 인터페이스를 단순화한다.
- HTTP 서버, 프론트엔드 빌드, 세션 쿠키, OpenAPI 생성물의 유지 비용을 제거한다.
- 거래 실행과 안전 규칙을 담당하는 얇은 인프라라는 Ante 설계 철학과 맞춘다.

**영향**:
- D-008의 브라우저 UI 프레임워크 결정은 역사 기록으로 남기고 본 결정이 대체한다.
- D-009의 프로젝트 구조에서 기존 UI와 HTTP 런타임 디렉토리는 제거된다.
- D-011의 동적 설정 변경 경로는 CLI/IPC를 기준으로 한다.
- APIGateway와 BrokerAdapter의 외부 증권사 REST/WebSocket 통신은 그대로 유지한다.
