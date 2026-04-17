# CLI 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# 설계 결정

### CLI 프레임워크

**근거**:
- `click` 라이브러리 채택 — 그룹/서브커맨드, 타입 검증, 자동 `--help` 생성
- `--format json` 글로벌 옵션 — Agent가 모든 커맨드 출력을 파싱 가능 (D-010)
- `--config-dir` 글로벌 옵션 — 설정 디렉토리 경로 (환경변수 `ANTE_CONFIG_DIR`로도 설정 가능)
- `--version` — 버전 정보 출력 (`ante --version`)
- `click.Context`로 공유 상태(format, formatter, config_dir, member) 전달
- 루트 그룹에서 `authenticate_member(ctx)` 호출하여 인증 수행

**유틸 함수**: `get_formatter(ctx) -> OutputFormatter` — 컨텍스트에서 포맷터 인스턴스 획득

소스: `src/ante/cli/main.py`

### OutputFormatter

text/json 모드를 지원하는 CLI 출력 포맷터.

| 프로퍼티/메서드 | 파라미터 | 반환값 | 설명 |
|----------------|----------|--------|------|
| `is_json` (property) | — | bool | JSON 모드 여부 |
| `output` | data: dict \| list, text_template: str = "" | None | 데이터 출력 (json 모드: JSON dump, text 모드: 템플릿 포맷) |
| `table` | rows: list[dict], columns: list[str] | None | 테이블 형태 출력 |
| `error` | message: str, code: str = "" | None | 에러 출력 |
| `success` | message: str, data: dict \| None = None | None | 성공 메시지 출력 (json 모드: `{status: "ok", message, data}`) |

소스: `src/ante/cli/formatter.py`

### 인증 미들웨어

> 소스: `src/ante/cli/middleware.py`

CLI 커맨드에 멤버 인증과 스코프 기반 접근 제어를 적용하는 미들웨어.

| 함수/데코레이터 | 설명 |
|----------------|------|
| `authenticate_member(ctx)` | 루트 그룹에서 호출. `ANTE_MEMBER_TOKEN` 환경변수로 `MemberService.authenticate()` 실행, 성공 시 `ctx.obj["member"]`에 저장 |
| `@require_auth` | 커맨드 데코레이터. `ctx.obj["member"]`가 None이면 에러 출력 후 SystemExit(1) |
| `@require_scope(*scopes)` | 커맨드 데코레이터. Human 멤버(`MemberType.HUMAN`)는 스코프 무제한 통과. Agent 멤버는 등록된 scope에 필요 scope가 모두 포함되어야 함 |
| `get_member_id(ctx)` | 인증된 멤버 ID 반환. 미인증 시 `"unknown"` |

**인증 면제 커맨드**: `bootstrap`, `reset-password`, `regenerate-recovery-key` (토큰 없이 실행 가능)

### 시스템 통신

CLI 커맨드는 **오프라인**과 **런타임** 두 가지 방식으로 시스템과 통신한다.

구분 기준: **서버의 EventBus 구독자가 반응해야 하는 부수효과(이벤트 발행 또는 인메모리 상태 변경)가 있는가?**

| 분류 | 실행 방식 | 설명 |
|------|----------|------|
| **오프라인** | 직접 모듈 임포트 | 조회, 백테스트, 데이터 관리 등 서버 런타임에 영향이 없는 커맨드. 서비스를 직접 생성하여 호출한다. |
| **런타임** | IPC (Unix domain socket) | 봇 중지, 예산 할당, 설정 변경 등 서버의 EventBus 구독자가 반응해야 하는 커맨드. 서버 프로세스의 서비스 계층에 위임한다. |

런타임 커맨드의 상세 목록과 IPC 프로토콜은 [ipc.md](../ipc/ipc.md)를 참조한다.

**런타임 커맨드 실행 흐름**:
1. CLI에서 `ANTE_MEMBER_TOKEN` 인증 + `@require_scope` 권한 확인 (기존과 동일)
2. `IPCClient`로 서버의 Unix socket에 커맨드 전달
3. 서버의 `IPCServer`가 수신 → `ServiceRegistry`의 서비스 실행 → EventBus 이벤트 전파
4. 결과를 CLI에 반환하여 출력
