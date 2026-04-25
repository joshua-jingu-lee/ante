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
principal, token prefix, scope vocabulary, human bypass, agent scope 제한 규칙의
SSOT는 [member/02-design-decisions.md](../member/02-design-decisions.md#authorization-ssot)다.
CLI는 해당 규칙을 command 실행 전에 적용하는 표면이다.

| 함수/데코레이터 | 설명 |
|----------------|------|
| `authenticate_member(ctx)` | 루트 그룹에서 호출. `ANTE_MEMBER_TOKEN` 환경변수로 `MemberService.authenticate()` 실행, 성공 시 `ctx.obj["member"]`에 저장 |
| `@require_auth` | 커맨드 데코레이터. `ctx.obj["member"]`가 None이면 에러 출력 후 SystemExit(1) |
| `@require_scope(*scopes)` | 커맨드 데코레이터. Human 멤버(`MemberType.HUMAN`)는 스코프 무제한 통과. Agent 멤버는 등록된 scope에 필요 scope가 모두 포함되어야 함 |
| `get_member_id(ctx)` | 인증된 멤버 ID 반환. 미인증 시 `"unknown"` |

**인증 면제 커맨드 경로**: `ante init`, `ante member reset-password`, `ante member regenerate-recovery-key` (토큰 없이 실행 가능)

매칭은 leaf 이름이 아니라 **전체 커맨드 경로** 기준이다. `ante feed init`처럼 leaf 이름이 우연히 `init`인 다른 서브커맨드는 면제 대상이 아니다 (`@require_auth` + `@require_scope`로 인증 필요). 구현은 `LeafAwareGroup`(src/ante/cli/main.py)이 루트 그룹 진입 직후 전체 경로 tuple을 `ctx.obj["_leaf_command_path"]`에 저장하고, `authenticate_member`가 이 tuple과 `_AUTH_EXEMPT_COMMAND_PATHS`(src/ante/cli/middleware.py)를 비교한다.

### 인스턴스 경로 일관성 (`config_dir` 기반)

**배경**: `ante init`은 `<config_dir>/system.toml`과 `<config_dir>/db/ante.db`를 생성한다. 후속 CLI들이 과거처럼 `Database("db/ante.db")`나 `data/`를 CWD 기준으로 하드코딩하면 서버와 CLI가 서로 다른 인스턴스를 참조하게 된다.

**규칙**:
- 모든 CLI는 Config 스펙의 Ante instance/path contract를 따른다.
- `--config-dir` 또는 `ANTE_CONFIG_DIR`이 확정한 `config_dir`이 인스턴스 루트이다.
- 모든 정적 상대 경로(`db.path`, `data.path`, `runtime.socket_path` 등)는 `config_dir` 기준으로 해석한다.
- 모든 CLI는 `ante.cli.main.get_db_path(ctx)` 헬퍼로 DB 경로를 해석한다. 이 헬퍼는 `system.toml`의 `db.path`를 우선 읽고, 미설정 시 `<config_dir>/db/ante.db` 기본값으로 폴백한다.
- data 계열 CLI는 `get_data_path(ctx)` 계열 헬퍼로 `data.path`를 해석한다. 명시적 `--data-path`가 없으면 `<config_dir>/data`가 기본값이다.
- 우선순위:
  1. `ctx.obj["config_dir"]` (루트 그룹이 `--config-dir` 또는 `ANTE_CONFIG_DIR` 환경변수로부터 확정한 Path)
  2. `system.toml` 안의 path-like 설정
  3. Config 기본값 (`db/ante.db`, `data`, `run/ante.sock` 등)
- `--db-path` 옵션을 가진 커맨드(`ante approval`, `ante backtest`, `ante instrument`, `ante report`, `ante data`)는 사용자 override를 위해 기본값을 `None`으로 두고, 값이 없을 때 `get_db_path(ctx)`로 폴백한다. 이로써 기존 사용자의 `--db-path` 지정은 그대로 동작한다.
- 서버(`ante system start`)와 런타임 CLI는 같은 resolver로 `db.path`와 `runtime.socket_path`를 해석한다. 따라서 같은 `config_dir`을 쓰면 같은 DB와 IPC socket을 본다.

### `--db-path` 옵션의 인증 DB / 작업 DB 분리

일부 CLI 커맨드(`ante approval`, `ante backtest`, `ante data`, `ante instrument`, `ante report`)는 대용량 조회·백테스트·스냅샷 조회 등을 위해 보조 DB를 지정할 수 있는 `--db-path <경로>` 옵션을 제공한다. 이 옵션은 **작업 대상 DB만 바꾸며 인증 DB를 바꾸지 않는다**. 아래 분리는 의도된 설계다.

- **인증 단계(루트 그룹)**: `authenticate_member(ctx)`는 항상 `get_db_path(ctx)` — 즉 `config_dir`과 `system.toml`의 `db.path`에서 정규화한 **canonical instance DB** — 에서 `ANTE_MEMBER_TOKEN`을 검증한다. 서브커맨드의 `--db-path` 값은 루트 콜백 실행 시점에 파싱되기 전이므로 인증 대상 DB에 영향을 줄 수 없다.
- **작업 단계(서브커맨드)**: 인증이 성공하면 서브커맨드가 `--db-path`로 지정된 DB(또는 미지정 시 `get_db_path(ctx)` 폴백)를 열어 실제 조회/기록을 수행한다.

예: `ante approval list --db-path /tmp/backup.db`는

1. canonical instance DB(`<config_dir>/db/ante.db`, 또는 `system.toml`의 `db.path` 정규화 결과)에서 `ANTE_MEMBER_TOKEN`을 검증한 뒤 (루트 콜백),
2. `/tmp/backup.db`에서 approval 목록을 조회한다 (서브커맨드 콜백).

**이 분리를 유지하는 이유**:

- **보안**: 토큰 검증은 신뢰할 수 있는 기본 DB에서만 수행한다. 호출자가 임의의 경로를 넘겨 인증을 우회하거나, 준비된 가짜 DB로 멤버 레코드를 위조하는 공격 벡터를 차단한다.
- **운영 시나리오**: 사용자·Agent가 백테스트 DB, 스냅샷, 아카이브를 조회할 때마다 해당 DB에 별도 멤버·토큰을 심어둘 필요가 없다. 한 번 발급받은 토큰으로 여러 데이터셋을 오가며 조회할 수 있다.

**부수 효과**:

- `--db-path`로 지정한 DB 자체의 유효성(존재 여부, 스키마 호환 등)은 서브커맨드 실행 시점에 검증되며, 인증이 실패하면 그 지점에 도달하지 않으므로 경로 유효성 오류는 노출되지 않을 수 있다. 이는 의도된 순서(인증 먼저)다.
- 반대로 `--config-dir`(또는 `ANTE_CONFIG_DIR`)은 루트 콜백 시점에 해석되므로 **인증 DB, 기본 작업 DB, data root, IPC socket을 함께** 바꾼다. 인스턴스를 스위치하려면 `--db-path`가 아니라 `--config-dir`을 사용한다.

`--db-path`가 인증 DB까지 바꾸도록 재구성하는 것은 구조적 리팩터링(루트 콜백에서 서브커맨드 파라미터 선해석)이 필요하며, 현재 범위에 포함하지 않는다. 필요 시 별도 설계 결정으로 다룬다.

### 시스템 통신

CLI 커맨드는 **오프라인**, **런타임**, **cold-path structural** 세 가지 방식으로 시스템과 통신한다.

구분 기준: **서버 프로세스가 보유한 EventBus 구독자, 인메모리 작업, 외부 연결,
인증·세션 상태가 관여하는가?**

| 분류 | 실행 방식 | 설명 |
|------|----------|------|
| **오프라인** | 직접 모듈 임포트 | 백테스트, 데이터 파일 조회, 정적 검증처럼 서버 런타임에 영향이 없고 서버의 live 상태를 읽을 필요도 없는 커맨드. 서비스를 직접 생성하여 호출한다. |
| **런타임** | IPC (Unix domain socket) | 봇 실행 제어, 예산 할당, 설정 변경, live broker 조회, 멤버 인증 상태 변경처럼 서버의 EventBus·인메모리 상태·외부 연결·세션 상태가 관여하는 커맨드. 서버 프로세스의 서비스 계층에 위임한다. |
| **cold-path structural** | 서버 정지 guard + 직접 DB | 계좌 생성/삭제/credentials 변경처럼 서버 topology를 바꾸는 커맨드. 같은 `config_dir`의 서버가 실행 중이면 DB 수정 전 거부한다. |

CLI 명령 시그니처와 실행 분류의 SSOT는 [03-commands.md](03-commands.md)다.
런타임 커맨드의 IPC 프로토콜과 서버 라우팅은 [ipc.md](../ipc/ipc.md)를 참조한다.

**런타임 커맨드 실행 흐름**:
1. CLI에서 `ANTE_MEMBER_TOKEN` 인증 + Member SSOT 기반 `@require_scope` 권한 확인
2. Config resolver가 정규화한 `runtime.socket_path`로 `IPCClient` 연결
3. 서버의 `IPCServer`가 수신 → `ServiceRegistry`의 서비스 실행 → EventBus 이벤트 전파
4. 결과를 CLI에 반환하여 출력

`ante member reset-password`와 `ante member regenerate-recovery-key`처럼 인증 면제
recovery 커맨드가 서버 실행 중 런타임 경로를 사용할 때는 토큰 대신 recovery key 또는
현재 패스워드를 서버 서비스가 검증한다.
