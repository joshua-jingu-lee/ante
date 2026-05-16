# CLI 모듈 세부 설계 - 커맨드 상세

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# 커맨드 상세

## SSOT 원칙

이 문서는 Ante CLI의 **명령 시그니처, 실행 분류, 서버 실행 중 동작**에 대한 단일 출처(SSOT)다.
모듈별 문서는 도메인 동작과 예시를 설명할 수 있지만, CLI 옵션·인자·runtime/offline
분류가 이 문서와 충돌하면 이 문서를 우선한다.

전략 파일 경로와 등록된 전략 ID는 분리한다. 전략 파일은 `ante strategy submit <path>`와
`ante backtest run <strategy_path>`에서만 직접 받는다. 봇 생성은 등록된 전략 ID를
사용한다.

## 공개 명령 allowlist (인증 면제)

> 정책 SSOT: [D-015 default-deny 인증 게이트](../../decisions/D-015-default-deny-auth-gate.md)
> 게이트 책임 분리: [02-design-decisions.md — default-deny CLI 인증 게이트](02-design-decisions.md#default-deny-cli-인증-게이트)

CLI는 default-deny + allowlist 정책을 적용한다. 다음 명령만 `ANTE_MEMBER_TOKEN`
없이 실행할 수 있다. 그 외 모든 명령은 토큰이 없으면 자동으로 exit 1로 거부된다.

코드 인용: `_AUTH_EXEMPT_COMMAND_PATHS` 정의는 `src/ante/cli/middleware.py:29-33`.
매칭은 leaf 이름이 아니라 전체 커맨드 경로 tuple 기준이다(`ante feed init`처럼
leaf 이름이 우연히 같은 명령은 면제 대상이 아니다).

| 명령 | 경로 tuple | 근거 |
|------|-----------|------|
| `ante --version` | — (옵션, 명령 아님) | `@click.version_option`(`src/ante/cli/main.py:94`)이 본 root 그룹에서 인증 단계 진입 전에 처리한다. 메타데이터 출력. |
| `ante init` | `("init",)` | 부트스트랩: 시스템 파일 골격, master 계정, test account를 1회 생성한다. 토큰 자체가 아직 발급되지 않은 상태. 재진입 가드(`src/ante/cli/commands/init.py:349-356` 부근의 5-state 검증, 테스트 `tests/unit/test_cli_init.py:246` "state1_all_exist_rejects")가 이미 init된 시스템에서 명령을 거부한다. |
| `ante member reset-password --recovery-key ...` | `("member", "reset-password")` | 패스워드 분실 복구. recovery key 자체가 인증 수단이다. 서버 측에서 recovery key 해시를 검증한 뒤 새 패스워드를 적용한다. |
| `ante member regenerate-recovery-key (--password-env\|--password-file)` | `("member", "regenerate-recovery-key")` | recovery key 재발급. 현재 패스워드 입력이 인증 수단이다(코드 invariant). |

**후보에서 제거**: `ante login` — CLI는 `ANTE_MEMBER_TOKEN` 환경변수 모델이며 별도
`login` 명령은 spec과 코드 모두에 존재하지 않는다(`grep -rn 'name="login"|@.*group.command.*login' src/ante/cli/` 결과 empty).
allowlist 후보에서 제거한다.

### 게이트-면제 메타 경로 (allowlist와 분리)

다음 경로는 공개 명령 allowlist와 별개로 인증 게이트가 적용되지 않는다. 명령 단위가
아니라 click 프레임워크 레벨에서 결정되므로 본 allowlist 표에 행을 추가할 필요가 없다.
정책 SSOT는 [02-design-decisions.md — 게이트-면제 메타 경로](02-design-decisions.md#default-deny-cli-인증-게이트)다.

| 메타 경로 | 적용 범위 | 사유 |
|----------|----------|------|
| `--help` | `ante --help`, `ante <cmd> --help`, `ante <cmd> <sub> --help` 등 모든 명령 단계 | root `--help`만 root 콜백 진입 전 처리되고, **nested `--help`는 부모 그룹 콜백이 먼저 실행된 뒤** 서브커맨드 단의 도움말이 출력된다(click 동작). 이 때문에 `authenticate_member(ctx)` 및 #1404 `authenticated_group` factory는 invocation에 `--help` 플래그가 있거나 `ctx.resilient_parsing == True`인 경우 인증 검사를 skip한다. 도움말은 명령 사용법 그 자체이며 인증 없이도 받을 수 있어야 Agent와 사람이 명령을 학습할 수 있다. 상세 정정 근거는 [02-design-decisions.md — `--help` 처리 시점](02-design-decisions.md#default-deny-cli-인증-게이트) 참조. |
| `--version` | `ante --version` | `@click.version_option`이 root 콜백 진입 전 처리. 메타데이터 출력. |
| resilient parsing | 자동완성 등 click이 `ctx.resilient_parsing=True`로 옵션을 시도 파싱하는 경로 | 부작용 없는 파싱이므로 인증 단계로 진입하지 않는다. `authenticate_member(ctx)`가 `ctx.resilient_parsing`을 확인해 즉시 return(`src/ante/cli/middleware.py:64-65`). |

`--help` / `--version` / resilient parsing은 신규 명령이 추가되어도 자동으로 동일하게
적용된다. 따라서 새 명령의 인증 여부 판단은 본 메타 경로와 무관하게 명령 자체의
의미("인증 없이 실행되어야 하는 부트스트랩/복구인가?")로만 답한다.

새 공개 명령 추가 시 다음 순서를 따른다:

1. 본 allowlist 표에 행 추가 (명령, 경로 tuple, 근거)
2. 코드의 `_AUTH_EXEMPT_COMMAND_PATHS`에 동일 tuple 등록
3. 인증 없이 호출되어도 안전한지 도메인별 invariant(예: `ante init`의 재진입 가드,
   `regenerate-recovery-key`의 현재 패스워드 요구) 검증

## 실행 분류 전수 표

| 분류 | 의미 |
|------|------|
| `offline` | 서버 프로세스와 무관하게 CLI가 직접 서비스/저장소를 생성해 실행한다. 서버 실행 중에도 live 상태를 바꾸지 않는다. |
| `runtime IPC` | 서버 프로세스의 서비스 인스턴스, EventBus, 인메모리 상태, 외부 연결, 세션 상태가 필요하므로 IPC로 위임한다. |
| `runtime IPC + snapshot fallback` | 서버 실행 중에는 IPC로 live 상태를 조회하고, 서버 정지 중에는 DB에 저장된 persisted snapshot만 조회한다. |
| `runtime IPC + cold-path fallback` | 서버 실행 중에는 IPC로 live 상태를 변경하고, 서버 정지 중에는 정해진 persisted cleanup만 직접 수행한다. |
| `cold-path` | 서버 topology 또는 broker 초기화 입력을 바꾸므로 active Ante runtime이 없는 상태에서만 직접 DB를 수정한다. |
| `external process` | 별도 프로세스 실행, OS signal, 장기 실행 파이프/스케줄러처럼 CLI 프로세스 경계를 넘는 작업이다. |
| `bootstrap/maintenance` | 초기화·복구 목적의 인증 면제 또는 서버 정지 fallback 경로다. |

| 커맨드 | 분류 | 실행 경계 |
|--------|------|-----------|
| `ante system start [--config-dir <path>]` | `external process` | `python -m ante.main` 실행 |
| `ante system stop` | `external process` | PID 기반 SIGTERM |
| `ante system status` | `offline` | canonical DB/PID 상태 조회 |
| `ante system halt` | `runtime IPC` | 서버 AccountService 전역 kill switch (모든 ACTIVE 계좌를 SUSPENDED로 전환) |
| `ante system clear-halt` | `runtime IPC` | 서버 AccountService 전역 kill switch 해제 (모든 SUSPENDED 계좌를 ACTIVE로 복구; 봇 자동 재시작 아님) |
| `ante account list [--status <status>]` | `offline` | runtime-safe 조회 |
| `ante account info <account_id>` | `offline` | runtime-safe 조회 |
| `ante account credentials <account_id>` | `offline` | 마스킹 조회 |
| `ante account create --broker-type <type> --account-id <id> --name <name> --trading-mode virtual\|live ...` | `cold-path` | 서버 실행 중 차단 |
| `ante account set-credentials <account_id> ...` | `cold-path` | 서버 실행 중 차단 |
| `ante account delete <account_id> --yes` | `cold-path` | 서버 실행 중 차단 |
| `ante account repair-timezone <account_id> <new_timezone>` | `cold-path` | 서버 실행 중 차단 |
| `ante account suspend <account_id> --reason <reason>` | `runtime IPC` | 서버 AccountService + EventBus |
| `ante account activate <account_id>` | `runtime IPC` | 서버 AccountService + EventBus |
| `ante bot list [--account <account_id>]` | `runtime IPC + snapshot fallback` | 서버 BotManager live 조회 우선 |
| `ante bot info <bot_id>` | `runtime IPC + snapshot fallback` | 서버 BotManager live 조회 우선 |
| `ante bot status <bot_id>` | `runtime IPC + snapshot fallback` | 서버 BotManager live 조회 우선 |
| `ante bot positions <bot_id>` | `runtime IPC + snapshot fallback` | live 포지션 조회 우선 |
| `ante bot signal-key <bot_id>` | `runtime IPC + snapshot fallback` | live signal key 상태 조회 우선 |
| `ante bot create --name <name> --strategy <strategy_id> ...` | `runtime IPC` | 서버 BotManager 생성 |
| `ante bot start <bot_id>` | `runtime IPC` | 서버 BotManager 실행 task 생성 |
| `ante bot stop <bot_id>` | `runtime IPC` | 서버 BotManager 실행 task 중지 |
| `ante bot remove <bot_id> --yes` | `runtime IPC + cold-path fallback` | 실행 중이면 서버 BotManager 정리, 정지 중이면 persisted bot cleanup |
| `ante bot signal-key <bot_id> --rotate` | `runtime IPC` | 기존 signal channel 무효화 |
| `ante trade list [--bot <bot_id>] [--from <date>] [--to <date>] [--limit N]` | `offline` | canonical DB 조회 |
| `ante trade info <trade_id>` | `offline` | canonical DB 조회 |
| `ante strategy validate <path>` | `offline` | AST 정적 검증 |
| `ante strategy submit <path>` | `offline` | 검증 + 로드 테스트 + StrategyRegistry 등록 |
| `ante strategy list` | `offline` | StrategyRegistry 조회 |
| `ante strategy info <name>` | `offline` | StrategyRegistry 조회 |
| `ante strategy performance <name> [--account-id <account_id>]` | `offline` | 성과 DB 집계 |
| `ante treasury status [--account <account_id>]` | `offline` | persisted treasury 상태 조회 |
| `ante treasury allocate <bot_id> <amount> --account <account_id>` | `runtime IPC` | 서버 TreasuryManager 캐시 갱신 |
| `ante treasury deallocate <bot_id> <amount> --account <account_id>` | `runtime IPC` | 서버 TreasuryManager 캐시 갱신 |
| `ante treasury snapshot ...` | `offline` | 일별 snapshot 조회 |
| `ante rule list [--scope global|strategy]` | `offline` | rule 설정 조회 |
| `ante rule info <rule_id>` | `offline` | rule 설정 조회 |
| `ante broker status/health [--account <account_id>]` | `runtime IPC` | 서버 BrokerAdapter live 상태 |
| `ante broker balance [--account <account_id>]` | `runtime IPC` | 서버 BrokerAdapter live 조회 |
| `ante broker positions [--account <account_id>]` | `runtime IPC` | 서버 BrokerAdapter live 조회 |
| `ante broker price <symbol> [--account <account_id>]` | `runtime IPC` | live broker quote |
| `ante broker reconcile [--account <account_id>] [--fix]` | `runtime IPC` | 서버 PositionReconciler |
| `ante data list/schema/storage/validate ...` | `offline` | canonical data root 또는 명시 data path 대상 |
| `ante backtest run <strategy_path> ...` | `offline` | 서버와 분리된 백테스트 실행 |
| `ante backtest history <strategy_name> [--limit N]` | `offline` | BacktestRunStore 조회 |
| `ante report schema/submit/list/view/performance ...` | `offline` | ReportStore/PerformanceFeedback 직접 호출 |
| `ante feed init/status/config/inject/run ...` | `offline` | canonical data root의 feed 작업 |
| `ante feed start [--data-path <path>]` | `external process` | 장기 실행 feed scheduler |
| `ante config get [key]` | `offline` | static/dynamic config 조회 |
| `ante config set <key> <value>` | `runtime IPC` | 서버 DynamicConfigService + EventBus |
| `ante config history <key>` | `offline` | dynamic config history 조회 |
| `ante approval request/approve/reject/cancel/reopen ...` | `runtime IPC` | 서버 ApprovalService + Notification/EventBus |
| `ante approval list/info/review ...` | `offline` | approval 저장소 조회 |
| `ante approval audit-types [--status ...]` | `offline` | scope `approval:read`. legacy invalid-type row 식별 (#1472) |
| `ante approval cancel-invalid <id>` | `runtime IPC` | scope `approval:admin`. legacy invalid-type row administrative cleanup (#1472) |
| `ante init ...` | `bootstrap/maintenance` | 인스턴스 파일 + master/test account 생성 |
| `ante member list/info ...` | `offline` | member 조회 |
| `ante member list-invalid-roles` | `offline` | DB 직접 조회 (runtime IPC 우회; `service.initialize` 수반) |
| `ante member register --id <member_id> --type human|agent ...` | `runtime IPC` | 서버 실행 중 member/session/security 상태 변경 |
| `ante member set-emoji/suspend/reactivate/rotate-token ...` | `runtime IPC` | 서버 실행 중 member/session/security 상태 변경 |
| `ante member revoke <member_id> --yes` | `runtime IPC` | 서버 실행 중 member/session/security 상태 변경 |
| `ante member reset-password --recovery-key <key> (--new-password-env <ENV>\|--new-password-file <PATH>)` | `runtime IPC` | 서버 실행 중 member/session/security 상태 변경 |
| `ante member regenerate-recovery-key (--password-env <ENV>\|--password-file <PATH>)` | `runtime IPC` | 서버 실행 중 member/session/security 상태 변경 |
| 동일 member mutation, 서버 정지 상태 | `bootstrap/maintenance` | recovery/비상 운영 fallback |
| `ante instrument list/search/sync/import ...` | `offline` | InstrumentService 및 외부 master data 작업 |
| `ante audit list ...` | `offline` | 감사 로그 조회 |
| `ante signal connect --key <sk_...>` | `external process` | signal key 기반 장기 실행 JSON Lines 채널 |
| `ante update [--check] [--version <version>] [--yes] [--force]` | `external process` | pip update + post-update migration |
| `ante notification` | — | public leaf command 없음 |

### `ante system` — 시스템 제어

```bash
ante system start                  # 시스템 시작
ante system stop                   # 시스템 정상 종료
ante system status                 # 시스템 상태 조회
ante system halt                   # 전역 거래 긴급 중지 (모든 ACTIVE 계좌를 SUSPENDED로 전환). 단일 계좌는 `account suspend <account_id>` 사용
ante system clear-halt             # 전역 정지 해제 (모든 SUSPENDED 계좌를 ACTIVE로 복구; 봇 자동 재시작 아님). 단일 계좌는 `account activate <account_id>` 사용
```

### `ante account` — 계좌 관리

```bash
ante account list [--status active|suspended|deleted]  # 계좌 목록
ante account info <account_id>                # 계좌 상세 정보
ante account create \
  --broker-type <broker_type> \
  --account-id <account_id> \
  --name <name> \
  --trading-mode virtual|live \
  [--credential key=value ...] \
  [--credential-env key=ENV_NAME ...] \
  [--credential-file key=PATH ...] \
  [--broker-config key=value ...] \
  [--format json]                             # 계좌 등록 (cold-path 전용, 서버 정지 필요)
ante account credentials <account_id>         # 인증 정보 조회 (마스킹)
ante account set-credentials <account_id> \
  [--credential key=value ...] \
  [--credential-env key=ENV_NAME ...] \
  [--credential-file key=PATH ...] \
  [--format json]                             # 인증 정보 재설정 (cold-path 전용)
ante account suspend <account_id> --reason <사유>  # 계좌 거래 정지
ante account activate <account_id>            # 계좌 거래 재개
ante account delete <account_id> --yes        # 계좌 삭제 (cold-path 전용, 연결된 봇이 없을 때만)
ante account repair-timezone <account_id> <new_timezone>  # legacy invalid IANA timezone 행 복구 (cold-path 전용)
```

`account create/delete/set-credentials`는 계좌 topology 또는 브로커 초기화 입력을 바꾸므로
서버 실행 중에는 차단된다. 실행 전 active Ante runtime guard를 확인하고,
runtime이 살아 있으면 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER`로 종료한다.
1.0 정책상 동일 OS user/home server 기준으로 active runtime은 항상 단일이며,
`account.delete`는 IPC 런타임 커맨드가 아니므로 cold-path CLI에서 직접
`AccountService.delete()`를 호출한다.

#### Broker 책임 경계 — `BROKER_REGISTRY` vs `BrokerPreset`

`account create`의 broker 관련 입력 검증 책임은 두 SSOT로 분리된다.

| 책임 | SSOT | 위치 |
|------|------|------|
| `broker_type` 문자열 → `BrokerAdapter` 클래스 매핑 | `BROKER_REGISTRY` | `src/ante/broker/registry.py` |
| broker별 default 값 + `required_credentials` 목록 | `BrokerPreset` (dataclass) | `src/ante/account/models.py` |

- `--broker-type`의 enum 검증(미등록 broker_type 거부)은 `BROKER_REGISTRY`를 참조한다.
- credential key 검증(`--credential`/`--credential-env`/`--credential-file`로 전달된 key가
  `required_credentials`에 정의되어 있는지)은 `BrokerPreset.required_credentials`를 참조한다.
- 필수 credential 누락은 `ACCOUNT_MISSING_REQUIRED_CREDENTIAL`, 정의되지 않은 key는
  `ACCOUNT_UNKNOWN_CREDENTIAL_KEY`로 실패한다.

`BROKER_REGISTRY`는 broker preset 정보를 보유하지 않으며, broker preset 변경에 영향을 받지 않는다.

#### `--broker-config` 정책 (1.0 범위)

`BrokerPreset`에 `optional_broker_config` 필드를 신설하지 않는다. `--broker-config key=value`는
free-form pass-through로 받아 `Account.broker_config: dict[str, Any]`에 저장한다.
broker별 known optional key 검증은 broker adapter 초기화 시점으로 위임한다.

예: `kis-domestic`의 `is_paper`는 `--broker-config is_paper=true`로 전달한다.

**1.0 silent ignore trade-off**: 1.0에서 broker adapter가 unknown `broker_config` key를
거부하지 않고 silent ignore할 수 있다(예: KIS adapter는 `config.get("is_paper", ...)` 형태로
known key만 읽음). 사용자가 오타나 잘못된 key를 `--broker-config`로 넘겨도 검증되지 않는다.
이는 1.0 의도된 trade-off이며, [02-design-decisions.md — 비대화형 입력 계약](02-design-decisions.md#비대화형-입력-계약-cli-non-interactive-input-contract)에 위험으로 명시한다.
후속 이슈에서 `BrokerPreset.optional_broker_config` 모델과 `UNKNOWN_BROKER_CONFIG_KEY`
검증을 도입한다.

#### `account create` 입력 계약

| 옵션 | 필수/선택 | 설명 |
|------|----------|------|
| `--broker-type <broker_type>` | 필수 | `BROKER_REGISTRY` 등록 값 |
| `--account-id <account_id>` | 필수 | 신규 계좌 식별자 |
| `--name <name>` | 필수 | 표시 이름 |
| `--trading-mode virtual\|live` | 필수 | 거래 모드 |
| `--credential key=value` | 선택 (반복) | credential 직접 값 (테스트/로컬 편의용, 비권장) |
| `--credential-env key=ENV_NAME` | 선택 (반복) | credential 환경변수 참조 (권장) |
| `--credential-file key=PATH` | 선택 (반복) | credential 파일 참조 (권장) |
| `--broker-config key=value` | 선택 (반복) | broker-specific 설정 (free-form pass-through) |
| `--format json` | 선택 | 출력 포맷 |

**계약**:

- `BrokerPreset.required_credentials`를 모두 충족해야 한다. 누락 시
  `ACCOUNT_MISSING_REQUIRED_CREDENTIAL`로 실패한다.
- 정의되지 않은 credential key는 `ACCOUNT_UNKNOWN_CREDENTIAL_KEY`로 실패한다.
- 같은 credential key를 `--credential`/`--credential-env`/`--credential-file` 중 둘 이상
  채널로 중복 제공하면 `ACCOUNT_DUPLICATE_CREDENTIAL_KEY`로 실패한다.
- `--credential-env`이 참조한 환경변수가 설정되지 않으면 `ACCOUNT_CREDENTIAL_ENV_NOT_SET`,
  `--credential-file`이 가리키는 파일이 존재하지 않으면 `ACCOUNT_CREDENTIAL_FILE_NOT_FOUND`로
  실패한다.
- prompt fallback은 없다. 누락 입력은 즉시 구조화된 에러로 종료한다.

#### `account set-credentials` 입력 계약

```bash
ante account set-credentials <account_id> \
  [--credential key=value ...] \
  [--credential-env key=ENV_NAME ...] \
  [--credential-file key=PATH ...] \
  [--format json]
```

**계약**:

- credential 옵션이 하나도 없으면 prompt하지 않고 `ACCOUNT_MISSING_REQUIRED_CREDENTIAL`로 실패한다.
- "재설정" 의미에 맞춰 대상 account의 `BrokerPreset.required_credentials`를 **모두**
  충족해야 한다(부분 갱신 허용 안 함).
- 그 외 검증 규칙(중복 key, env/file 해석 실패, unknown key)은 `account create`와 동일하다.

#### 위험 명령 — `--yes`/`--force` 필수

다음 명령은 prompt confirm을 제거하고 `--yes` 또는 `--force` 없이는 실패한다.

```bash
ante account delete <account_id> --yes
ante bot remove <bot_id> --yes
ante member revoke <member_id> --yes
```

`--yes` 누락 시 `CLI_CONFIRMATION_REQUIRED`로 실패한다.

`ante update`의 `--check`/`--yes`/`--force` 의미 분리는 [`ante update`](#ante-update--업데이트) 절을 참조한다.

#### `ante bot create`의 `--account` 생략 정책

```bash
ante bot create --name <name> --strategy <strategy_id> [--account <account_id>] ...
```

- active 계좌가 정확히 1개일 때만 `--account` 생략을 허용하고, 그 단일 active 계좌가 자동 선택된다.
- active 계좌가 0개 또는 2개 이상이면 prompt 없이 `BOT_MISSING_REQUIRED_ACCOUNT`로 실패한다.
- prompt 기반 계좌 선택 경로는 제거되었다.

#### `ante member reset-password` 입력 계약

```bash
ante member reset-password \
  --recovery-key <key> \
  (--new-password-env ENV_NAME | --new-password-file PATH) \
  [--format json]
```

- `--new-password-env` 또는 `--new-password-file` 중 정확히 하나를 사용한다.
- 직접 `--new-password` 값 옵션은 shell history 노출 우려로 본 이슈에서 권장 채널에서 제외한다
  (env/file만 권장 채널로 확정).
- 두 옵션 모두 누락이면 `MEMBER_PASSWORD_ENV_NOT_SET` 또는 `MEMBER_PASSWORD_FILE_NOT_FOUND`
  가 아닌 `CLI_MISSING_REQUIRED_INPUT`(또는 도메인 specialize 코드)으로 실패한다.

#### `ante member regenerate-recovery-key` 입력 계약

```bash
ante member regenerate-recovery-key \
  (--password-env ENV_NAME | --password-file PATH) \
  [--format json]
```

- `--password-env` 또는 `--password-file` 중 정확히 하나를 사용한다.
- prompt 기반 현재 패스워드 입력은 제거되었다.

### `ante bot` — 봇 관리

```bash
ante bot list [--account <account_id>]  # 봇 목록 (계좌별 필터링)
ante bot create --name <name> --strategy <strategy_id> [--account <account_id>] [--id <bot_id>] [--interval <초>] [--param key=value ...]
ante bot start <bot_id>            # 봇 시작
ante bot stop <bot_id>             # 봇 중지
ante bot remove <bot_id> --yes     # 봇 삭제 (--yes 누락 시 CLI_CONFIRMATION_REQUIRED)
ante bot info <bot_id>             # 봇 상세 정보
ante bot status <bot_id>           # 봇 실행 상태
ante bot positions <bot_id>        # 봇 현재 포지션
ante bot signal-key <bot_id> [--rotate]  # 외부 시그널 키 조회·갱신
```

`bot create`의 `--account` 생략 시 동작은 [위 절](#ante-bot-create의---account-생략-정책)을 따른다.

`bot create/start/stop`과 `bot signal-key --rotate`는 서버 BotManager의 인메모리
`_bots`, 실행 task, EventBus 구독, signal key 연결 상태를 바꾸므로 런타임 IPC 커맨드다.
`bot remove`는 서버 실행 중에는 IPC로 BotManager에 위임하고, 서버 정지 중에는
cold-path fallback으로 signal key, 전략 스냅샷, Treasury budget, `bots.status`만
정리한다. 서버 실행 중 `bot list/info/status/positions/signal-key` 조회는 IPC로
서버의 live 상태를 우선 조회한다. 서버가 정지된 상태에서는 DB의 persisted snapshot만
읽을 수 있으며, `bot remove` 외 직접 DB 수정으로 봇 상태를 바꾸는 경로는 허용하지 않는다.

`--strategy`는 등록된 `strategy_id`다. 전략 파일 경로를 직접 넘기려면 먼저
`ante strategy submit <path>`로 등록해야 한다.

### `ante trade` — 거래 이력

```bash
ante trade list [--bot <bot_id>] [--from <날짜>] [--to <날짜>] [--limit N]
ante trade info <trade_id>         # 거래 상세
```

`trade list`의 `--from`/`--to`가 모두 지정되고 시작일(`--from`)이 종료일(`--to`)
이후이면(inverted date range) DB 접근 이전에 `INVALID_DATE_RANGE` 에러 코드와
exit code 1로 거부한다(빈 결과 반환 금지). 한쪽만 지정·둘 다 미지정·동일
날짜는 정상 처리한다.

### `ante strategy` — 전략 관리

```bash
ante strategy validate <path>      # 전략 파일 정적 검증 (AST)
ante strategy submit <path>        # 검증 + 로드 테스트 + 전략 등록
ante strategy list                 # 등록된 전략 목록
ante strategy info <name>          # 전략 상세 (메타데이터, 파라미터)
ante strategy performance <name> [--account-id <account_id>]  # 전략 전체 성과 (모든 봇 집계, Agent 피드백용)
```

`strategy submit`은 전략 파일을 `StrategyRegistry`에 등록하고 `strategy_id`를 생성한다.
이후 봇 생성은 이 `strategy_id`를 참조한다.

### `ante treasury` — 자금 관리

```bash
ante treasury status [--account <account_id>]    # 자금 현황 (계좌별 필터링)
ante treasury allocate <bot_id> <금액> --account <account_id>    # 봇에 자금 할당
ante treasury deallocate <bot_id> <금액> --account <account_id>  # 봇 자금 회수

# 일별 자산 스냅샷 조회
ante treasury snapshot [--account <account_id>]                        # 최근 스냅샷 (대시보드 D-1)
ante treasury snapshot --from <날짜> --to <날짜> [--account <account_id>]  # 기간별 스냅샷 (대시보드 D-2 차트)
ante treasury snapshot --date <날짜> [--account <account_id>]          # 특정일 스냅샷
```

`treasury snapshot`의 `--from`/`--to`가 모두 지정되고 시작일(`--from`)이
종료일(`--to`) 이후이면(inverted date range), `--date`/`--from`/`--to` 배타
검증(`CLI_OPTION_CONFLICT`) 직후·서비스 호출 이전에 `INVALID_DATE_RANGE` 에러
코드와 exit code 1로 거부한다(빈 결과 반환 금지). 한쪽만 지정·둘 다
미지정·동일 날짜는 정상 처리한다.

> 스냅샷 스펙: [treasury.md — 일별 자산 스냅샷](../treasury/treasury.md#일별-자산-스냅샷-daily-asset-snapshot)

### `ante rule` — 거래 룰 관리

```bash
ante rule list [--scope global|strategy]  # 전역 + 전략별 룰 목록
ante rule info <rule_id>           # 룰 상세
```

### `ante broker` — 증권사 연동

```bash
ante broker status [--account <account_id>]      # 증권사 연결 상태
ante broker health [--account <account_id>]      # status alias
ante broker balance [--account <account_id>]     # 실제 증권사 잔고 조회
ante broker positions [--account <account_id>]   # 실제 증권사 포지션 조회
ante broker price <symbol> [--account <account_id>]  # live 현재가 조회
ante broker reconcile [--account <account_id>] [--fix]  # 시스템↔증권사 포지션 대사
```

모든 `broker` live 커맨드는 서버가 시작 시 생성한 BrokerAdapter를 통해 실행하는
런타임 IPC 커맨드다. CLI가 별도 adapter를 직접 생성하면 credentials 복호화, 연결
상태, rate limit, circuit breaker, audit 경로가 서버와 분리되므로 허용하지 않는다.
`broker price`는 live broker quote만 의미한다. 과거·공개 market data 조회는
`data`/`feed` 계열 커맨드로 다룬다. `broker order`와 `broker stream prices`는
일반 운영 CLI 범위가 아니며, 별도 maintenance/test 스펙 없이는 제공하지 않는다.

### `ante data` — 데이터 관리

모든 data 커맨드는 `@require_auth`와 `@require_scope("data:read")` 데코레이터 적용.
`--data-path`를 생략하면 Config resolver가 정규화한 `data.path`를 사용한다.
명시적 `--data-path`는 해당 커맨드의 작업 대상만 바꾸며 인스턴스 경계를 바꾸지 않는다.

```bash
ante data list [--data-path <경로>] [--db-path <경로>]            # 보유 데이터셋 목록 (종목명 병기, InstrumentService 연동)
ante data schema [--data-path <경로>]                             # OHLCV 데이터 스키마 조회
ante data storage [--data-path <경로>]                            # 저장 용량 현황 (MB 단위, timeframe별)
ante data validate [--symbol <종목>] [--timeframe <주기>] [--fix] [--data-path <경로>]  # Parquet 파일 무결성 검증
```

### `ante backtest` — 백테스트

`--data-path`를 생략하면 canonical data root(`data.path`)에서 Parquet 데이터를 읽는다.

```bash
ante backtest run <strategy_path> --start <날짜> --end <날짜> [--symbols <종목,...>] [--balance <초기자금>] [--timeframe <주기>] [--data-path <경로>]  # 진행률 바 표시 (text 모드)
ante backtest history <strategy_name> [--limit N] [--db-path <경로>]  # 전략별 백테스트 실행 이력
```

### `ante report` — 리포트

```bash
ante report schema                 # 리포트 제출 스키마 조회 (Agent용)
ante report submit <json_path> [--run <run_id>] [--db-path <경로>]  # 리포트 제출
ante report list [--status <상태>] [--db-path <경로>]  # 리포트 목록 조회
ante report view <report_id> [--db-path <경로>]        # 리포트 상세 조회
ante report performance [--period daily|monthly] [--bot-id <봇ID>] [--start <날짜>] [--end <날짜>] [--year <연도>]  # 기간별 성과 집계
```

`report performance`의 기간 옵션은 `--period`별로 배타적이다. `--start`/`--end`는
`--period daily` 전용, `--year`는 `--period monthly` 전용이며 (`--period` 기본값은
`daily`), period와 맞지 않는 옵션을 함께 지정하면 DB 접근 이전에
`CLI_OPTION_CONFLICT` 에러 코드와 exit code 1로 거부한다(빈 집계 반환 금지).

추가로 `--period daily`에서 `--start`/`--end`가 모두 지정되고 시작일(`--start`)이
종료일(`--end`) 이후이면(inverted date range), 위 period-exclusive 검증 직후·DB
접근 이전에 `INVALID_DATE_RANGE` 에러 코드와 exit code 1로 거부한다(빈 집계 반환
금지). 검증 순서는 period-exclusive(`CLI_OPTION_CONFLICT`)가 먼저이므로
`--period monthly --start ... --end ...`는 여전히 `CLI_OPTION_CONFLICT`로
거부되며 `INVALID_DATE_RANGE`에 도달하지 않는다.

또한 `--year`는 `--period monthly` 전용의 양수(>0) calendar year다.
`--period monthly --year`에 `0` 또는 음수가 지정되면, 위 period-exclusive
검증 직후·DB 접근 이전에 `REPORT_VALIDATION_ERROR` 에러 코드와 exit code 1로
거부한다(빈 집계 반환 금지). 상한·미래연도는 검증하지 않는다(양수 여부만 검증).
검증 순서는 period-exclusive(`CLI_OPTION_CONFLICT`)가 먼저이므로
`--period daily --year 0`/`--year -1`은 여전히 `CLI_OPTION_CONFLICT`로 거부되며
(`--year`는 monthly 전용) `REPORT_VALIDATION_ERROR`에 도달하지 않는다.

### `ante feed` — 데이터 피드 (DataFeed)

CLI 정의는 `src/ante/feed/cli.py`에 있으며 `ante.cli.main`에서 서브커맨드로 등록된다.
모든 feed 커맨드는 `@require_auth`와 `@require_scope` 데코레이터로 인증/권한 검증을 수행한다.

```bash
ante feed init [data_path]               # 운영 디렉토리 초기화, 기본 config 생성. 생략 시 data.path 사용 (scope: data:write)
ante feed status [--data-path <경로>]     # 수집 상태 조회 (scope: data:read)
ante feed config set <KEY> <VALUE> [--data-path <경로>]       # API 키를 .feed/.env에 저장 (scope: data:write)
ante feed config list [--data-path <경로>]                    # 등록된 설정값 목록 (마스킹 표시) (scope: data:read)
ante feed config check [--data-path <경로>]                   # API 키 존재 여부 확인 (scope: data:read)
ante feed inject <path> --symbol <종목> [--timeframe <주기>] [--source <소스>] [--data-path <경로>]  # CSV 파일에서 데이터 주입 (scope: data:write)
ante feed run backfill [--since <날짜>] [--data-path <경로>]  # 과거 데이터 1회 수집 (scope: data:write)
ante feed run daily [--date <날짜>] [--data-path <경로>]      # 어제(또는 지정일) 데이터 1회 수집 (scope: data:write)
ante feed start [--data-path <경로>]                          # 내장 스케줄러로 backfill/daily 자동 실행하는 상주 프로세스 (scope: data:write)
```

> 상세: [data-feed.md](../data-feed/data-feed.md)

### `ante config` — 설정 관리

```bash
ante config get [key]              # 설정 조회 (키 생략 시 전체 목록)
ante config set <key> <value>      # 동적 설정 변경
ante config history <key>          # 설정 변경 이력 조회
```

### `ante approval` — 승인 요청 관리

```bash
ante approval request --type <type> --title <title> [--body <text>] [--params <json>] [--reference-id <id>] [--expires-in 72h]  # 승인 요청 생성
ante approval list [--status <상태>]        # 승인 요청 목록
ante approval info <approval_id>            # 승인 요청 상세
ante approval review <approval_id> --result pass|warn|fail [--detail <text>]  # 승인 요청 리뷰
ante approval cancel <approval_id>          # 승인 요청 취소
ante approval approve <approval_id>         # 승인 요청 승인
ante approval reject <approval_id>          # 승인 요청 거부
ante approval reopen <approval_id> [--data <json>]  # 거절된 요청 재상신 (params/body 수정 가능)
ante approval audit-types [--status <상태>]   # legacy invalid-type row 식별 (#1472, scope approval:read)
ante approval cancel-invalid <approval_id>    # legacy invalid-type row administrative cleanup (#1472, scope approval:admin)
```

### `ante init` — 시스템 초기 설정

설치 후 최초 1회 실행하는 **비대화형** 설정 커맨드. 인증 면제.
파일시스템 골격(`system.toml`·`secrets.env`·빈 DB·data/run/logs 디렉토리) 생성 + master 계정 + 가상 탐색용 테스트 계좌를 1회 생성한다.

```bash
ante init [--member-id owner] [--name Owner] [--dir <경로>]
```

**플래그:**

| 플래그 | 기본값 | 설명 |
|--------|--------|------|
| `--member-id` | `owner` | master 멤버 ID |
| `--name` | `Owner` | master 표시 이름 |
| `--dir` | `~/.config/ante/` | 설정 디렉토리 경로 |

**생성 산출물:**

인스턴스 파일/디렉토리와 DB 레코드 2개를 생성한다.

- 파일: `<dir>/system.toml`, `<dir>/secrets.env` (placeholder 주석), `<dir>/db/ante.db` (스키마 적용)
- 디렉토리: `<dir>/data/`, `<dir>/run/`, `<dir>/logs/`
- DB 레코드: master member 1개, default test account (`broker_type="test"`) 1개

`system.toml`은 `db.path = "db/ante.db"`, `data.path = "data"`,
`runtime.socket_path = "run/ante.sock"`, `runtime.pid_path = "run/ante.pid"`,
`logging.directory = "logs"`처럼 `config_dir` 기준 상대 경로를 기록한다.
1.0 정책상 `config_dir`은 데이터/설정 프로필 경계이며, 단일 active runtime
정책 하에서 동시 namespace로 사용하지 않는다.

**내부 실행 순서**: 1. 디렉토리 생성 → 2. master bootstrap → 3. test account 생성

**출력:**

패스워드·토큰·recovery key를 **자동 생성**하여 1회만 출력한다. 사용자는 입력하지 않는다.

**멱등성 (I4 — 파일 + master 레코드 기반 재진입):**

- 3개 파일 + master row + test account row가 **모두 존재**하면 거부 (`"init이 이미 완료된 상태입니다"`, exit code 1)
- 그 외 경로에서는 **누락된 것만** 생성. 즉:
  - 파일 누락 → 누락 파일 재생성
  - `data/`, `run/`, `logs/` 디렉토리 누락 → 누락 디렉토리 재생성
  - master row 없음 → master bootstrap 실행 (비밀값 즉시 출력하여 후속 단계 실패 시에도 복구 가능)
  - test account row 없음 → test account 생성

**옵셔널 도메인 입력 (Telegram / KIS 실계좌 / DataFeed):**

`ante init`은 이들을 다루지 않는다. 필요 시 다음 명령을 사용한다:

- KIS 실계좌: 서버 정지 상태에서 `ante account create --broker-type kis-domestic --account-id <id> --name <name> --trading-mode live` 등 [비대화형 시그니처](#ante-account--계좌-관리)로 실행
- Telegram: `<dir>/secrets.env` 직접 편집 (`TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`)
- DataFeed API 키: `ante feed config set ANTE_DATAGOKR_API_KEY <key>` / `ANTE_DART_API_KEY`
  ([비대화형 입력 계약의 명시적 예외](02-design-decisions.md#비대화형-입력-계약-cli-non-interactive-input-contract))

**비범위:**

- stdin prompt: 없음 ([비대화형 입력 계약](02-design-decisions.md#비대화형-입력-계약-cli-non-interactive-input-contract))
- 시드 데이터 주입: 지원하지 않음 (PR #609 이후 관련 인프라 제거됨)

### `ante member` — 멤버(에이전트) 관리

> master 계정 생성은 `ante init`에 통합되었다. 별도 `ante member bootstrap` 명령은 제거됨(재설계 2026-04).

권한 모델 SSOT는 [02-design-decisions.md — Member admin mutation 권한 모델](02-design-decisions.md#인증-미들웨어)와
[../member/02-design-decisions.md — Member admin mutation 권한 모델](../member/02-design-decisions.md#권한-범위-scope)이다.
member admin mutation은 1.0 계약에서 **master-only**이며, agent token으로 호출하면
service layer `MemberService._assert_master`에서 거부되어 exit 1로 종료한다.
`member:admin` scope는 vocabulary에 정의되어 있으나 reserved (1.0 미사용)다.

```bash
ante member register --id <member_id> --type human|agent [--org <org>] [--name <name>] [--scopes <csv>]  # 멤버 등록 (master-only)
ante member list [--type human|agent] [--org <org>] [--status active|suspended|revoked]  # 멤버 목록 (scope: member:read)
ante member info <member_id>                            # 멤버 상세 (scope: member:read)
ante member list-invalid-roles [--format json]          # MemberRole enum 외 role 을 가진 legacy row 식별 (운영 cleanup; runbook 07 참조)
ante member suspend <member_id>                         # 멤버 일시 정지 (master-only)
ante member reactivate <member_id>                      # 멤버 재활성화 (master-only)
ante member revoke <member_id> --yes                    # 멤버 권한 영구 해제 (master-only, --yes 누락 시 CLI_CONFIRMATION_REQUIRED)
ante member rotate-token <member_id>                    # 인증 토큰 갱신 (master-only)
ante member set-emoji <member_id> <emoji>               # 멤버 이모지 설정 (master-only)
ante member reset-password --recovery-key <key> (--new-password-env ENV_NAME | --new-password-file PATH)  # 비밀번호 초기화 (공개 명령 allowlist — recovery key가 인증 수단)
ante member regenerate-recovery-key (--password-env ENV_NAME | --password-file PATH)  # 복구 키 재발급 (공개 명령 allowlist — 현재 패스워드가 인증 수단)
```

> 후속 implementation 정렬: #1543 (Web API/CLI 표면 가드 master-only로 일치),
> #1544 (oracle host probe scope 기대값 정렬). 본 결정 SSOT는 #1542이며,
> 부모 #1511(oracle host probe scope drift)에서 시작된 정합 작업이다.

`member list/info`와 `member list-invalid-roles`는 오프라인 조회가 가능하다. 단,
`member list-invalid-roles`는 `MemberService.initialize()`로 schema migration DDL을
수반하므로 "read-only"가 아니다(runtime IPC는 우회한다). 그 외 member 상태·토큰·
패스워드·복구키 변경 커맨드는 서버 실행 중 IPC로 서버에 위임한다. 서버는
MemberService 실행 후 필요한 세션 무효화, 토큰 무효화, 감사 로그, member/security
알림을 같은 런타임 경로에서 처리한다. 같은 `config_dir`의 서버가 정지된 상태에서는
bootstrap/recovery 및 비상 revoke를 위해 직접 MemberService를 생성하는
maintenance fallback을 허용한다.

`member list-invalid-roles`는 `MemberRole` enum SSOT(`master`/`admin`/`default`)에
없는 `role` 값을 가진 legacy row를 두 카테고리(`actionable` / `legacy_revoked`)로
분리해 보여준다. 운영자는 `actionable` row를 `ante member revoke <member_id> --yes`로
cleanup한다. `token_hash`는 모든 출력 모드에서 표시되지 않으며, 토큰 존재 여부는
`has_token: bool`로만 노출된다. 자세한 절차는
[runbook 07](../../runbooks/07-member-invalid-role-cleanup.md)에 정의되어 있다.

### `ante instrument` — 종목 관리

```bash
ante instrument list [--exchange <거래소>] [--type <유형>] [--listed-only] [--db-path <경로>]  # 종목 목록
ante instrument sync [--exchange <거래소>]                  # KIS API에서 종목 마스터 동기화
ante instrument search <query> [--limit N] [--listed-only] [--db-path <경로>]  # 종목 검색
ante instrument import <filepath> [--dry-run] [--db-path <경로>]  # CSV/JSON 종목 데이터 주입
```

> canonical exchange 계약 SSOT: [core.md `## Canonical Exchange Vocabulary`](../core/core.md#canonical-exchange-vocabulary).
> instrument는 canonical-only(`*` 거부) 주 신규 입력 표면이다. `list`/`sync`/`import`의
> non-canonical `--exchange` / import payload는 non-zero exit + 구조화 error payload로 거부되어야
> 한다(`ORACLE_INVALID_EXCHANGE` 출처). enforcement 정렬은 #1577에서 다룬다(현재 코드/스펙 drift).

### `ante notification` — 알림 관리

`notification_history` 테이블 제거 후 public leaf command는 없다. 텔레그램 채팅방 자체가
발송 이력을 담당한다.

### `ante audit` — 감사 로그 조회

```bash
ante audit list [--member <member_id>] [--action <prefix>] [--from-date <날짜>] [--to-date <날짜>] [--limit N] [--offset N]
```

`audit list`의 `--from-date`/`--to-date`가 모두 지정되고 시작 날짜
(`--from-date`)가 종료 날짜(`--to-date`) 이후이면(inverted date range) DB 접근
이전에 `INVALID_DATE_RANGE` 에러 코드와 exit code 1로 거부한다(빈 결과 반환
금지). 한쪽만 지정·둘 다 미지정·동일 날짜는 정상 처리한다.

### `ante signal` — 외부 시그널 채널

```bash
ante signal connect --key <sk_...>   # 양방향 JSON Lines 시그널 채널 수립
```

### `ante update` — 업데이트

```bash
ante update [--check] [--version <version>] [--yes] [--force]
```

**옵션 의미 분리** (비대화형 입력 계약):

| 옵션 | 의미 | 누락/충돌 시 |
|------|------|--------------|
| `--check` | PyPI 버전 조회만 수행 (dry-run, 확인 불필요) | 단독 사용 가능 |
| `--yes` (`-y`) | 확인 우회 — `--check`이 아닌 모든 실제 업데이트 실행에 필수 | 미사용 + `--check` 미사용 → `CLI_CONFIRMATION_REQUIRED` |
| `--force` | 서버 실행 중이면 자동 중지 후 업데이트 | 미사용 + 서버 실행 중 → `UPDATE_SERVER_RUNNING` |

- `--check`은 단순 조회이므로 `--yes`/`--force` 영향 없음. `--check`과 `--yes`를 동시에 사용해도
  `--check`이 우선한다(충돌 정책: `--check` 우선).
- prompt 기반 확인 경로(`click.confirm`)는 제거되었다. 모든 확인은 옵션으로 명시한다.
