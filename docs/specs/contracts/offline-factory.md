# CLI Offline Service Factory Contract

> Parent epic: [#1818 CLI offline service composition factory & runtime guard SSOT](https://github.com/joshua-jingu-lee/ante/issues/1818)
> Owning issue: [#1854 CLI offline service factory 계약 및 read_only 초기화 정책 정리](https://github.com/joshua-jingu-lee/ante/issues/1854)
> Status: 1.0 normative — CLI `offline` / `cold-path` execution class가 사용하는 service composition factory의 책임/비책임, read_only 초기화 정책, ctx 기반 path resolution 정책의 단일 SSOT.
> Scope: 본 문서는 SSOT spec. production factory 구현(`open_cli_db`)은 [#1855](https://github.com/joshua-jingu-lee/ante/issues/1855)에서 도입되어 `src/ante/cli/db_context.py`에 존재한다.
> Migration order: [docs/specs/contracts/README.md#migration-domain-order](README.md#migration-domain-order)와 [#1820](https://github.com/joshua-jingu-lee/ante/issues/1820)에서 SSOT로 결정된 `account → member → approval → bot → treasury → broker → strategy → 기타` 순서를 따른다. 본 문서는 본 순서를 **재선언하지 않는다**.

## 목적

CLI `offline` 및 `cold-path` execution class (cf.
[docs/specs/cli/03-commands.md](../cli/03-commands.md))의 명령은 서버 runtime을
거치지 않고 직접 `Database` + `EventBus` + domain service를 구성한다. 본 SSOT는
다음 4개의 결정을 단일 위치에 lock 한다.

1. CLI offline service factory의 **책임 / 비책임** 경계
2. **`read_only`** 초기화 정책 (옵션 B: `Database` API 변경 없이 factory 레벨에서
   `service.initialize()` skip)
3. **ctx 기반 DB path resolution** 정책 (ctx 명시 전달 권장, 암시 fallback
   deprecated)
4. **read-only 분류 예외 목록** — service `initialize()` 안에서 schema/DDL이
   자동 발동되어 read-only 명령에서도 schema migration이 trigger되는 commands

본 문서는 [#1818](https://github.com/joshua-jingu-lee/ante/issues/1818) Normative
Decisions의 spec-only 응축이다. 코드 이슈(#1855/#1856/#1857)는 본 문서를
SSOT로 reference하며, 도입된 helper는 `src/ante/cli/db_context.py`의
`open_cli_db`다.

## 1. Factory 책임 / 비책임

### 1.1 책임 (in-scope)

CLI offline service factory는 다음만 책임진다.

- **DB lifecycle**
  - `Database(get_db_path(ctx))` 인스턴스 생성
  - `await db.connect()` 호출
  - 정상/예외/취소(`asyncio.CancelledError`/`KeyboardInterrupt`) 경로 모두에서
    `await db.close()` 보장
- **EventBus 생성**
  - offline 명령이 EventBus를 필요로 하는 경우 `EventBus()` 생성. EventBus는
    in-memory subscriber 없이 사용되며, factory 종료 시 별도 close 의무를
    부여하지 않는다 (`EventBus` 자체가 close API를 가지지 않는다는 baseline 유지).
- **Service lifecycle**
  - 도메인 service 인스턴스 생성 (예: `AccountService(db=db, eventbus=eventbus)`)
  - **read-write 명령**의 경우 `await service.initialize()` 호출
  - **read-only 명령**의 경우 `service.initialize()` **skip** (§2 참조; 예외는
    §4 참조)
- **Cleanup 패턴 (#1722 baseline 유지)**
  - `service` 생성/`initialize()` 이후의 모든 라이프사이클을 `except BaseException`
    블록으로 감싸 실패 시 `await db.close()` 보장
  - close 자체 실패는 inner `try/except`로 흡수해 원본 예외(예:
    `EncryptionKeyMissingError`)가 호출자에게 안정 `code`로 전달되도록 한다.
  - 본 패턴은 #1755 회귀(aiosqlite worker thread leak → asyncio 종료 시
    `busy_timeout` 대기로 CLI 프로세스 hang)를 구조적으로 차단하기 위한
    contract다.
- **Config-dir / DB path resolution**
  - `ctx`에서 `--config-dir`/`ANTE_CONFIG_DIR` 값을 추출 (`get_config_dir(ctx)`)
  - 해당 config-dir 기준으로 `get_db_path(ctx)`를 호출해 DB 경로를 산출
  - `--db-path` 명시 override가 명령에 존재하는 경우 (예: `ante approval list
    --db-path`), factory는 caller가 산출한 경로를 입력으로 받는다 (factory가
    Click option parsing을 직접 수행하지 않는다).

### 1.2 비책임 (out-of-scope)

CLI offline service factory는 다음을 **수행하지 않는다**. 이 책임은 caller (CLI
command 본체 또는 별도 wrapper)가 가진다.

- **IPC 호출 여부 결정** — IPC client 호출, IPC 응답 파싱, IPC 실패 시 fallback
  분기는 `runtime IPC` execution class의 책임이다. offline factory는 IPC-aware로
  가지 않는다.
- **`runtime` vs `offline` 분기** — execution class 분류는 CLI command registry
  (#1815)와 `docs/specs/cli/03-commands.md`의 allowlist 표가 SSOT다. offline
  factory는 이미 "offline 경로"를 선택한 caller만 호출한다.
- **`runtime IPC + snapshot fallback` / `runtime IPC + cold-path fallback`
  분기** — fallback 결정은 caller가 갖는다. factory는 fallback 경로 안에서만
  호출된다.
- **active runtime guard** — `cold-path` 명령의 `assert_no_active_runtime`
  호출은 caller 책임이다. factory는 guard를 호출하지 않는다.
- **Audit logging** — `audit.*` 이벤트 emission, IPC dispatch wrapper의
  `audit_action` auto-fire (#1851)는 handler/wrapper 책임이다. factory는 audit
  side-effect를 발화하지 않는다.
- **Auth / scope 검증** — `require_auth` / `require_scope` decorator는 CLI
  command 본체에 attach된다. factory는 auth context를 검증하거나 reject하지
  않는다.
- **Envelope 직렬화** — `fmt.success`/`fmt.error`/`emit_cli_error` 호출은 caller
  책임이다. factory는 envelope을 생성하지 않으며,
  [`docs/specs/contracts/envelopes.md`](envelopes.md) 자체를 재정의하지 않는다.
- **Error code 매핑** — domain exception → public `code` 매핑은
  [`docs/specs/contracts/error-taxonomy.md`](error-taxonomy.md)와 #1816/#1843이
  SSOT다. factory는 본 SSOT를 재정의하지 않으며, 예외를 swallow하지 않는다
  (cleanup 직후 re-raise).

## 2. `read_only` 초기화 정책

### 2.1 결정

**옵션 B (factory-level skip)**를 normative로 채택한다.

- `Database.__init__` signature는 변경하지 않는다. 현재 baseline
  (`src/ante/core/database.py`의 `Database(db_path: str)`)을 그대로 유지한다.
  본 SSOT는 `Database` API에 `read_only` kwarg를 추가하지 **않는다**.
- 대신 factory가 호출 시점에 `read_only: bool` (또는 동등 분류) 값을 받아
  다음을 결정한다.
  - `read_only=True`: `service.initialize()` 호출을 **skip**한다. 해당 service
    가 `_db.execute_script(...)` / `_db.execute(ALTER ...)` 등의 schema/DDL
    trigger를 가지더라도 read-only 명령 경로에서는 그것을 발화하지 않는다.
  - `read_only=False`: `service.initialize()`를 호출한다. schema migration /
    DDL이 발동될 수 있다.

### 2.2 read-only / read-write 분류 결정 기준

- 1차 SSOT: [docs/specs/cli/03-commands.md](../cli/03-commands.md)의
  execution class + 명령 의미(`list`/`info`/`status`/`logs`/`history`/`view` 등은
  read-only).
- 2차 SSOT (구현 후): #1815 CLI command contract registry의 `OutputContract`
  `kind` (e.g. `entity` / `collection`) 및 execution class. registry 도입 후
  factory는 caller로부터 명시 인자 (`read_only: bool`)를 받거나 registry에서
  derive할 수 있다.
- 본 SSOT는 분류의 enumeration(전 CLI 명령의 read-only 여부 표)을 재선언하지
  **않는다**. enumeration은 [docs/specs/cli/03-commands.md](../cli/03-commands.md)
  + #1815 registry가 SSOT다.

### 2.3 옵션 A를 채택하지 않은 이유

Plan v1 Codex review 권고:

- `Database`에 `read_only: bool = False`를 추가하는 옵션 A는 본 spec PR 범위가
  아닌 `Database` API 변경이다. spec-only PR (#1854)에서 `Database` API
  contract를 변경하면 docs PR과 code PR이 충돌한다.
- factory-level skip(옵션 B)은 `Database` API를 그대로 두고도 invariant
  ("read-only 명령은 schema/DDL trigger하지 않는다")를 만족한다.
- #1855/#1856/#1857 구현 시 `Database` API에 `read_only` mode 추가가
  고려되었으나, 본 spec은 옵션 B(factory-level skip)를 normative로 채택한
  결정만 lock하며 — 향후 `Database` API에 `read_only` mode를 추가하는 결정이
  내려지더라도 본 spec과 충돌하지 않는다.

## 3. ctx 기반 path resolution 정책

### 3.1 결정

- **명시 ctx 전달이 권장 (recommended)**. factory 신규 signature는 ctx를 명시
  인자로 받는다. 예:
  ```python
  async with open_cli_db(ctx) as db:
      ...

  async with open_cli_account_service(ctx, read_only=True) as service:
      ...
  ```
- factory 내부는 `get_db_path(ctx)` / `get_config_dir(ctx)`를 호출한다. ctx
  없는 `get_db_path()` 호출은 **factory 내부에서 금지**한다.
- **암시 ctx fallback은 deprecated**. 현재 `src/ante/cli/main.py:get_db_path()`
  는 `ctx is None` 시 `click.get_current_context(silent=True)`로 암시 조회를
  수행한다. 본 fallback은 legacy 호환을 위해 helper 자체에서는 유지하되,
  **신규 factory 코드가 fallback에 의존하는 것은 금지**한다.
- 본 정책은 #1818 본문의 결정과 정합한다 — "신규 factory 내부에서는
  `get_db_path(ctx)`를 기본으로 사용한다. ctx 없는 path resolution은
  legacy/deprecated path로 문서화한다."

### 3.2 후속 책임 (현재 진행 중 항목)

- ctx 없는 `get_db_path()` 호출의 점진 제거는 진행 중이다. 잔여 callsite:
  `src/ante/cli/commands/signal.py:48`, `src/ante/cli/commands/broker.py:34,354`
  — 이들은 #1855/#1856/#1857 후속 cleanup 대상이다.
- 본 SSOT는 helper 자체의 deprecation timeline을 강제하지 않는다. fallback
  helper signature 자체는 #1855/#1856/#1857 migration이 완료된 이후 별도
  이슈로 제거를 검토한다.

## 4. read-only 분류 예외 (initialize-fires-DDL)

### 4.1 정책

§2의 옵션 B는 "read-only 명령은 `service.initialize()`를 skip한다"고 lock
한다. 그러나 일부 service는 `initialize()` 안에 schema migration / DDL을 가지고
있어, 만약 schema가 부재한 상태에서 read 호출 (`SELECT ...`)을 수행하면
`OperationalError: no such table: ...`이 raise된다. 즉, **fresh DB나
non-bootstrapped DB에서는 read-only 명령이라도 schema가 한 번은 생성되어야**
한다.

본 절은 이러한 service를 명시 예외로 lock한다. 본 예외 목록에 해당하는
service는 read-only 명령에서도 `initialize()`를 호출한다 (즉 옵션 B의 skip
규칙에서 제외된다).

### 4.2 예외 목록 (baseline 2026-05-27 KST)

본 표는 `src/ante/{domain}/service.py`의 `initialize()` 본문이 schema /
migration DDL을 발화하는 service를 열거한다. baseline 측정값이며, 후속 PR이
service를 변경하면 본 표를 갱신한다.

| Service | `initialize()` 본문 요약 | read-only 명령 예시 | 분류 |
|---------|--------------------------|---------------------|------|
| `AccountService` | `_CREATE_TABLE_SQL` + `_ACCOUNTS_BUFFER_MIGRATION` ALTER + backfill (#1333) + 계좌 캐시 로드 | `account list`, `account info`, `account credentials` | **예외 (initialize 발동)** |
| `MemberService` | `MEMBER_SCHEMA` + `_EMOJI_MIGRATION` + `_TOKEN_EXPIRES_MIGRATION` | `member list`, `member info` | **예외 (initialize 발동)** |
| `ApprovalService` | `APPROVAL_SCHEMA` | `approval list`, `approval info` | **예외 (initialize 발동)** |
| `AuditLogger` | schema 생성 | `audit list`/`audit logs` 등 read 경로 | **예외 (initialize 발동)** |
| `DynamicConfigService` | schema 생성 + cache hydrate | `config get` (dynamic key) | **예외 (initialize 발동)** |

### 4.3 후속 분리 가능성

본 예외는 **service `initialize()` 내부에 read path와 schema 부트스트랩이
얽혀 있기 때문**에 발생한다. #1855는 factory 책임 경계(spec §2)를 lock하는
방향으로 진행됐으며, `Database` API에 `read_only` mode를 도입하지 않는
옵션 B 정책은 본 spec §2 결정에 따라 유지된다. 향후 다음 중 하나를 채택하면
본 표는 축소될 수 있다 — 본 SSOT는 어느 쪽도 강제하지 않는다.

- service에 `ensure_schema()` / `open_existing()` 등의 분리 entrypoint 도입 →
  read-only factory는 `ensure_schema()`만 호출, write path는 기존
  `initialize()` 호출
- factory가 schema 부재를 감지해 `ensure_schema()` 호출 후 read 진행

본 표는 baseline lock일 뿐, 후속 schema separation 결정은 별도 spec change로
다룬다.

### 4.4 예외 외 service

본 표에 없는 service (예: `TradeService`, `TreasuryService`,
`BotManager`(offline read 경로 한정), `StrategyRegistry`(read 명령),
`PositionHistoryService`, `BacktestRunStore`, `InstrumentService` 등)는
read-only 명령에서 `initialize()` skip이 가능한 후보다. 단, **#1855/#1856
구현 시점에** 각 service의 `initialize()` 본문을 재확인해 skip 가능 여부를
1:1 검증한다. 본 SSOT는 baseline만 lock하고, skip 가능 service를 enumerate하지
않는다 (drift 위험을 피하기 위해).

## 5. Migration Order

본 spec은 #1855/#1856/#1857의 domain migration 순서를 **재선언하지
않는다**. SSOT는 다음 두 곳이다.

- [docs/specs/contracts/README.md#migration-domain-order](README.md#migration-domain-order)
- [#1820](https://github.com/joshua-jingu-lee/ante/issues/1820)

요지: `account → member → approval → bot → treasury → broker → strategy →
기타`. 단, #1818 본문에 명시된 예외 — "cleanup 회귀 차단 가치 때문에
account/member/approval을 같은 1차 PR(#1856)에 함께 다뤘다" — 가
허용된다.

본 절은 SSOT reference이며, 본 spec PR에서 순서를 재정의하면 drift다. drift
발견 시 본 spec을 갱신하지 않고 SSOT 두 곳을 정렬한다.

## 6. 현재 구현체 baseline

본 SSOT 작성 시점(2026-05-27 KST, `main`) 기준 측정값이다 — #1818 본문
스냅샷의 재확인이다. 후속 PR이 본 baseline을 변경하면 본 절을 갱신한다.

- `Database(get_db_path(...))` 직접 생성 callsite: **22곳**
  (`rg -n "Database\(.*get_db_path" src/ante/cli/commands/` 기준).
- 이 중 ctx 없는 `get_db_path()` 호출: 19곳.
- ctx 명시 `get_db_path(ctx)` 호출: 3곳.
- `src/ante/cli/commands/account.py:_create_account_service` — #1722 cleanup
  패턴의 canonical baseline. `except BaseException` + inner `try/except` close
  실패 흡수.
- `src/ante/cli/commands/approval.py` — #1755 `except BaseException` cleanup
  패턴이 5개 명령(`list`/`info`/`request`/`review`/`reopen`)에 반복.
- `src/ante/cli/commands/member.py` — `_create_service()` helper 존재 (account
  pattern 부분 미러).
- 그 외 domain (`treasury`/`bot`/`broker`/`strategy`/`rule`/`audit`/`config`/
  `instrument`/`backtest`/`signal`/`system`/`trade`/`report`) — DB/EventBus/
  service 생성/`initialize()`/`close()` 패턴이 분산.

본 baseline은 #1818 본문의 측정값과 일치한다. 후속 PR이 baseline을 변경하면
#1818 본문과 본 절을 함께 갱신한다.

## 7. 검증

본 SSOT는 docs-only이므로 자체 verification은 다음으로 충족된다.

- 본 문서가 `docs/specs/contracts/offline-factory.md`에 존재한다.
- [`docs/specs/contracts/README.md`](README.md)가 본 문서를 SSOT index entry로
  가리킨다.
- `docs/architecture/generated/project-structure.md`가 본 신규 파일을 반영해
  재생성되어 있다.
- `pytest tests/unit/` 회귀 0 (production code 변경 없음).
- 본 문서가 [#1818](https://github.com/joshua-jingu-lee/ante/issues/1818)
  Normative Decisions와 충돌하지 않는다.

## 8. 변경 정책

- 본 SSOT의 책임/비책임 경계 (§1), `read_only` 정책 (§2), ctx 정책 (§3),
  예외 목록 (§4) 변경은 contract change다. 별도 SSOT 이슈로 다룬다.
- 본 SSOT는 [`envelopes.md`](envelopes.md), [`error-taxonomy.md`](error-taxonomy.md)
  본문을 **재정의하지 않는다**. envelope shape / error taxonomy 변경은 각
  SSOT의 책임이다.
- baseline 측정값 (§6) 갱신은 contract change가 아니다. 후속 PR이 본 baseline을
  변경하면 본 절만 갱신한다.
- migration order (§5) 재선언은 금지다. 순서 변경은 #1820 + README SSOT에서
  결정한다.

## Non-Goals

본 SSOT가 다루지 **않는** 항목.

- factory production code 구현 — #1855/#1856/#1857에서 완료.
- CLI command migration enumeration — 동일.
- DI framework 도입.
- IPC routing / IPC fallback 통합.
- `Database` API 확장 (`read_only` kwarg 등) — 본 SSOT는 옵션 B를 채택해
  `Database` API 변경 없이 invariant를 만족하도록 lock 한다.
- runtime `src/ante/main.py` composition root 변경.
- envelope/error taxonomy 본문 변경.
- service `initialize()` schema 분리 — 본 spec §2가 factory-level skip(옵션 B)로
  lock; #1855/#1856/#1857 migration이 그 lock을 따른다.
