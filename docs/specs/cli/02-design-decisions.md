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

### 비대화형 입력 계약 (CLI Non-Interactive Input Contract)

> 본 절은 Ante CLI 입력 계약의 SSOT다. 모든 도메인 스펙(`account/09-cli.md`,
> `bot/06-cli-usage.md`, `member/06-cli.md`)은 이 계약을 따른다.

**원칙**:

```text
Ante CLI는 stdin 대화형 입력을 제공하지 않는다.
필수 입력이 없으면 prompt하지 않고 구조화된 에러로 실패한다.
모든 입력은 인자, 옵션, 환경변수 참조, 파일 경로 중 하나로 전달한다.
비밀값은 직접 값 옵션보다 --*-env 또는 --*-file 경로를 우선한다.
위험 명령은 confirm prompt 대신 --yes 또는 --force를 명시적으로 요구한다.
```

**stdin prompt 금지**:

CLI 코드에서 다음 API 사용을 금지한다.

- `click.prompt(...)`
- `click.confirm(...)`
- `@click.confirmation_option(...)`

`click` 자체는 명령/옵션 파싱과 `--help` 생성을 위해 유지하며, prompt 계열 API만 금지한다.

**입력 채널**:

모든 사용자 입력은 다음 4개 채널 중 하나로 전달한다.

| 채널 | 형식 | 용도 |
|------|------|------|
| argument | `<value>` 위치 인자 | account_id, bot_id 등 식별자 |
| option | `--key value` | 명시적 옵션 값 |
| env reference | `--*-env <ENV_NAME>` | 비밀값을 환경변수로 전달 |
| file reference | `--*-file <PATH>` | 비밀값을 파일에서 읽음 |

**비밀값 입력 우선순위**:

비밀값(credential, password 등)은 `--*-env`/`--*-file` 사용을 권장한다. 직접 값 옵션
(예: `--credential key=value`)은 shell history 노출 우려가 있어 명시적 비권장 경로다.
직접 값 옵션은 테스트와 로컬 편의용으로만 허용하며, 자동화/Agent 워크플로우에서는
`--*-env`/`--*-file`을 사용한다.

**위험 명령 확인 방식**:

다음 명령은 prompt 대신 `--yes` 또는 `--force` 옵션을 명시적으로 요구한다.

| 명령 | 옵션 | 누락 시 에러 |
|------|------|--------------|
| `ante account delete <account_id>` | `--yes` | `CLI_CONFIRMATION_REQUIRED` |
| `ante bot remove <bot_id>` | `--yes` | `CLI_CONFIRMATION_REQUIRED` |
| `ante member revoke <member_id>` | `--yes` | `CLI_CONFIRMATION_REQUIRED` |
| `ante update [실제 실행]` | `--yes` | `CLI_CONFIRMATION_REQUIRED` |
| `ante update` (서버 실행 중 자동 중지) | `--force` | `UPDATE_SERVER_RUNNING` |

`ante update --check`는 PyPI 버전 조회만 수행하는 dry-run이므로 `--yes`가 필요하지 않다.

**누락 입력 처리**:

필수 옵션·인자가 누락되면 prompt하지 않고 구조화된 에러로 즉시 종료한다(exit code 1).
JSON 모드(`--format json`)에서는 `{status: "error", code: "...", message: "..."}` 형식으로 출력한다.

**에러 코드 명명 규칙 (SSOT)**:

도메인 prefix를 사용하며 `SCREAMING_SNAKE_CASE`로 작성한다. 입력 계약 위반은 도메인이
명확하면 도메인 prefix를 사용하고(`ACCOUNT_*`, `MEMBER_*`, `BOT_*`, `UPDATE_*`),
도메인이 없으면 `CLI_*` prefix를 사용한다.

표준 에러 코드 (이번 이슈에서 SSOT로 확정):

| 에러 코드 | 의미 | 발생 명령 |
|-----------|------|----------|
| `CLI_MISSING_REQUIRED_INPUT` | 필수 옵션·인자 누락 (도메인 명확 시 도메인 prefix specialize) | 모든 명령 |
| `CLI_CONFIRMATION_REQUIRED` | 위험 명령에 `--yes`/`--force` 누락 | `account delete`, `bot remove`, `member revoke`, `update` |
| `ACCOUNT_MISSING_REQUIRED_CREDENTIAL` | `BrokerPreset.required_credentials`에 정의된 credential key 누락 | `account create`, `account set-credentials` |
| `ACCOUNT_UNKNOWN_CREDENTIAL_KEY` | broker preset의 `required_credentials`에 정의되지 않은 credential key 제공 | `account create`, `account set-credentials` |
| `ACCOUNT_DUPLICATE_CREDENTIAL_KEY` | 같은 credential key를 `--credential`/`--credential-env`/`--credential-file` 중 둘 이상 채널로 중복 제공 | `account create`, `account set-credentials` |
| `ACCOUNT_CREDENTIAL_FILE_NOT_FOUND` | `--credential-file`이 가리키는 파일이 존재하지 않음 | `account create`, `account set-credentials` |
| `ACCOUNT_CREDENTIAL_ENV_NOT_SET` | `--credential-env`이 참조한 환경변수가 설정되지 않음 | `account create`, `account set-credentials` |
| `MEMBER_PASSWORD_FILE_NOT_FOUND` | `--password-file`/`--new-password-file`이 가리키는 파일이 존재하지 않음 | `member reset-password`, `member regenerate-recovery-key` |
| `MEMBER_PASSWORD_ENV_NOT_SET` | `--password-env`/`--new-password-env`이 참조한 환경변수가 설정되지 않음 | `member reset-password`, `member regenerate-recovery-key` |
| `BOT_MISSING_REQUIRED_ACCOUNT` | `--account` 생략 시 active 계좌가 0개 또는 2개 이상 | `bot create` |
| `UPDATE_SERVER_RUNNING` | `ante update --force` 없이 서버가 실행 중 | `update` |

`--broker-config`는 1.0 범위에서 free-form pass-through(아래 silent ignore trade-off
참조)이므로 본 이슈에서는 `UNKNOWN_BROKER_CONFIG_KEY`를 정의하지 않는다.

**인간-AI 공용 표면**:

입력 계약(인자/옵션/env/file)은 출력 계약(`--format json`)과 함께 "Agent와 사람이
공용으로 사용 가능한 CLI 표면"의 일부다. Agent는 stdin prompt에 응답할 수 없으므로,
prompt 기반 입력은 Agent 사용성을 일방적으로 희생시킨다. 비대화형 입력 계약은
Agent와 사람이 같은 명령 시그니처로 동일한 결과를 얻도록 보장한다.

**비대상 표면**:

다음은 CLI stdin prompt와 별개의 표면이며 본 원칙의 적용 대상이 아니다.

- Telegram `/confirm` 2단계 확인 — `docs/specs/notification/*` (사용자 단말의 별도 채널)
- Dashboard 확인 모달 — `docs/specs/dashboard/*` (브라우저 UI의 별도 채널)
- 서버 측 IPC/Web API 요청 본문 — CLI 입력 계약의 적용 범위 밖

**1.0 trade-off — `--broker-config` silent ignore 위험**:

1.0에서 `BrokerPreset`은 `required_credentials`만 강제 검증하고, broker별 optional
broker_config key는 free-form pass-through로 받는다(`Account.broker_config: dict[str, Any]`).
broker adapter가 unknown key를 거부하지 않고 silent ignore할 수 있다(예: KIS adapter는
`config.get("is_paper", ...)` 형태로 known key만 읽음). 이는 1.0 의도된 trade-off이며,
후속 이슈에서 `BrokerPreset.optional_broker_config` 모델과 `UNKNOWN_BROKER_CONFIG_KEY`
검증을 도입한다.

**명시적 예외 — `ante feed config set`**:

`ante feed config set <KEY> <VALUE>`는 `<config_dir>/data/.feed/.env` 파일에 직접
secret을 기록하기 위한 입력 경로로 1.0 시점에 남아 있다. CLI 입력 계약의 비밀값
우선순위와 충돌하지만 본 이슈에서는 정리하지 않는다. 후속 이슈에서 `feed config set`에
`--value-env`/`--value-file` 도입을 별도로 다룬다.

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

매칭은 leaf 이름이 아니라 **전체 커맨드 경로** 기준이다. `ante feed init`처럼 leaf 이름이 우연히 `init`인 다른 서브커맨드는 면제 대상이 아니다 (`@require_auth` + `@require_scope`로 인증 필요). 구현은 `LeafAwareGroup`(src/ante/cli/main.py)이 루트 그룹 진입 직후 전체 경로 tuple을 `ctx.obj["_leaf_command_path"]`에 저장하고, `authenticate_member`가 이 tuple과 `_AUTH_EXEMPT_COMMAND_PATHS`(src/ante/cli/middleware.py:29-33)를 비교한다.

### default-deny CLI 인증 게이트

> 정책 SSOT: [D-015 default-deny 인증 게이트](../../decisions/D-015-default-deny-auth-gate.md)

CLI는 default-deny + allowlist (opt-out) 정책을 적용한다. 새 명령 추가 시 별도 조치
없이 인증이 자동으로 부착되고, 인증 없이 실행할 수 있는 명령은 명시적으로 allowlist에
등록한다.

**책임 분리**:

| 단계 | 책임 | 위치 |
|------|------|------|
| 1차 차단 (authentication) | `ANTE_MEMBER_TOKEN`이 없거나 검증 실패면 exit 1. allowlist 명령은 면제. | `authenticated_group` factory(#1404 구현 예정). 현재는 루트 그룹의 `authenticate_member(ctx)` + 명령 단의 `@require_auth`로 부분 적용. |
| 2차 차단 (authorization) | `@require_scope(...)` 데코레이터. agent에 대해서만 required scope를 검사하고 human은 bypass. | `src/ante/cli/middleware.py`의 `@require_scope`. |

**현재 상태와 후속 전환**:

- 1.0 현재 CLI는 opt-in 모델(`@require_auth` + `@require_scope` 명령별 부착)을 유지하고
  있다. default-deny factory(`authenticated_group`) 도입은 #1404에서 구현한다.
- 본 spec은 정책과 allowlist 결정만 확정한다. factory 시그니처, decorator shim,
  마이그레이션 순서는 #1404가 SSOT다.
- 공개 명령 allowlist의 SSOT는 [03-commands.md — 공개 명령 allowlist](03-commands.md#공개-명령-allowlist--인증-면제)다.

**게이트-면제 메타 경로 (allowlist와 분리)**:

다음 경로는 "공개 명령 allowlist"(4개 명령)와는 별개로 인증 게이트 자체가 적용되지
않는다. 어떤 명령에 대해서도 평등하게 적용되는 메타 입력이기 때문이다.

| 게이트-면제 경로 | 사유 | 코드 cite |
|-----------------|------|----------|
| `ante --help` (root) | `click`은 root 그룹의 콜백 실행 **전에** root 레벨 `--help` 플래그를 처리해 도움말을 출력하고 종료한다. 인증 단계까지 진입하지 않는다. | `src/ante/cli/main.py:105`의 root `cli()` 콜백 안 `authenticate_member(ctx)`는 click이 root `--help`를 처리한 뒤에는 호출되지 않는다. |
| `ante <cmd> --help`, `ante <cmd> <sub> --help` 등 nested `--help` | **주의**: click은 nested `--help`에서 **부모 그룹 콜백을 먼저 실행한 뒤** 서브커맨드 단의 도움말을 출력한다. 즉 `ante member --help`나 `ante member list --help`에서도 root `cli()` 콜백(과 #1404 도입 후 `authenticated_group` factory)이 실행된다. 토큰 없이 인증을 강제하면 보호 서브커맨드의 도움말 자체를 못 받게 되어 학습 경로가 막힌다. | nested help 처리 시 부모 group 콜백이 실행되는 시점의 `ctx.resilient_parsing` 값은 **click 내부 동작에 의존**하며 항상 `True`라고 보장되지 않는다. 따라서 본 spec은 invariant만 정의하고 구체 검사 시그니처는 #1404 plan-preflight에서 확정한다. invariant는 아래 "nested help 면제 invariant" 절을 따른다. raw `sys.argv` 검사(`"--help" in sys.argv[1:]`)는 어떤 경우에도 사용하지 않는다. `ante strategy submit -- --help`처럼 `--` 이후 위치 인자로 들어간 `--help`는 인증을 면제하지 않으며 default-deny 게이트가 정상 발화해야 한다. 도움말은 명령 사용법 그 자체이며 토큰 없이 받을 수 있어야 Agent와 사람이 명령을 학습할 수 있으므로 본 면제는 default-deny의 의도와 충돌하지 않는다(Codex review v4 Finding 2 — raw sys.argv 검사로 인한 우회 차단). |
| `ante --version` | `@click.version_option`(`src/ante/cli/main.py:94`)이 root 콜백 진입 전 처리. 메타데이터 출력. | 동일. |
| Click resilient parsing 경로 | `click`이 자동완성(shell completion) 등을 위해 명시적으로 `ctx.resilient_parsing=True`로 옵션 파싱을 시도할 때. 이 모드에서는 부작용을 일으키지 않아야 한다. **nested `--help`는 click 버전에 따라 부모 콜백 invoke 시점에 `resilient_parsing`이 `True`가 아닐 수 있으므로 위 nested help 행과 별도로 다룬다.** | `authenticate_member(ctx)`는 `ctx.resilient_parsing`이 True면 즉시 return하여 인증을 건너뛴다(`src/ante/cli/middleware.py:64-65`). #1404의 `authenticated_group` factory도 동일 가드를 갖는다. |

이 면제 경로는 4개 명령 allowlist와 다른 결로 운영된다.

- **공개 명령 allowlist**: 명령 자체가 인증 없이 실행되어야 하는 부트스트랩/복구 경로.
  명령 추가 시 도메인 invariant(재진입 가드, 현재 패스워드 요구 등) 검증이 필요하다.
- **게이트-면제 메타 경로**: `--help` / `--version` / resilient parsing처럼 명령 실행
  자체가 일어나지 않는 입력. 명령 단위가 아니라 click 프레임워크 레벨에서 결정되며,
  새 명령이 추가되어도 자동으로 동일하게 적용된다. 별도 allowlist 등록이 필요 없다.

따라서 신규 명령을 추가할 때 "이 명령은 인증이 필요한가?" 질문은 게이트-면제 메타
경로와 무관하게 명령 자체의 의미에만 답하면 된다. `--help` 통과는 default-deny
정책과 충돌하지 않는다.

**nested help 면제 invariant (Codex review v5 Finding 3)**:

`ante <group> --help`나 `ante <group> <sub> --help` 같은 nested help는 click이
부모 group의 콜백을 먼저 invoke한 뒤 자식의 도움말을 렌더링하는 경로다. 이때
부모 콜백이 호출되는 시점의 `ctx.resilient_parsing` 값은 click 내부 동작에
의존하며 spec이 "항상 `True`"로 단언할 수 없다. 따라서 본 spec은 **invariant
세 개만** 정의하고, 정확한 검사 시그니처(`ctx` 필드 조합)는 #1404 plan-preflight
단계에서 click의 실제 동작을 확인한 뒤 확정한다.

| invariant | 내용 |
|-----------|------|
| (H1) 통과해야 한다 | `ante`, `ante <group>`, `ante <group> <sub>`, 더 깊은 임의 경로에 대해 `--help` / `-h`가 명령 인자로 들어온 경우, 토큰이 없어도 도움말이 정상 출력되고 exit 0으로 종료한다. 인증 단계는 부수효과(토큰 검증 실패 로깅, exit 1 등)를 일으키지 않는다. |
| (H2) 차단해야 한다 | `--help`가 `--` 이후의 위치 인자로 들어온 경우(예: `ante strategy submit -- --help`)는 도움말이 아니라 일반 명령 인자이므로, default-deny 게이트가 정상 발화해 토큰 없으면 exit 1로 차단한다. |
| (H3) 검사 방식 | nested help 판정은 **Click context가 노출하는 상태만** 본다(예: `ctx.resilient_parsing`, `ctx.protected_args`, `ctx.invoked_subcommand`, `ctx.params`의 click 결과). raw `sys.argv` 검사(`"--help" in sys.argv`)는 어떤 경우에도 사용하지 않는다. (H2)를 만족시키기 위해 click이 이미 `--` 분리를 처리한 뒤의 context를 기준으로 한다. |

대안 패턴(예: `group.no_args_is_help = True` 설정 후 root 콜백 진입 전에 click이
help를 가로채도록 위임)도 본 invariant를 만족하면 허용된다. #1404 plan-preflight는
click 버전(`click>=8.0` 등 본 프로젝트 pin)에서 실제 nested help 호출 시 어떤
context 필드가 어떤 값으로 채워지는지 확인하고 (H1)(H2)(H3)을 동시에 만족하는
검사 식을 확정한다.

**caveat**: 본 spec은 nested help 면제 검사의 정확한 함수 시그니처를 못박지
않는다. click 내부 동작 의존 표면이라 spec과 코드를 같은 라운드에 정정하지
않으면 회귀가 발생하기 쉽기 때문이다. 따라서 (H1)(H2)(H3) invariant 위반은
#1404 PR에서 단위 테스트로 보증하고, spec은 invariant 정의에 한정한다.

**`ante login` 후보 제거**: 본 이슈 검토 과정에서 거론되었으나 CLI는 `ANTE_MEMBER_TOKEN`
환경변수 모델이며 별도 `login` 명령은 spec(`docs/specs/cli/03-commands.md`)과 코드
(`src/ante/cli/commands/`) 모두에 존재하지 않는다. allowlist 후보에서 제거.

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
