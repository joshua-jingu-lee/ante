# Stable Error Taxonomy SSOT

> Parent decision: [#1816 Stable error contract & taxonomy epic](https://github.com/joshua-jingu-lee/ante/issues/1816)
> Sub-issue: [#1839 Stable error taxonomy spec + auth middleware code policy](https://github.com/joshua-jingu-lee/ante/issues/1839)
> Status: 1.0 normative — CLI/IPC가 공유하는 안정 에러 코드 taxonomy의 단일 SSOT.
> Envelope shape SSOT: [docs/specs/contracts/envelopes.md](envelopes.md) (재정의 금지, reference만)
> Implementation references (non-normative): `src/ante/cli/formatter.py`, `src/ante/cli/middleware.py`, `src/ante/ipc/server.py`, 도메인 `errors.py`/`exceptions.py` 분포.

## 목적

본 SSOT는 CLI(`--format json`)와 IPC(Unix domain socket)가 사용자/Agent에 노출하는
**안정 에러 코드(`code` 값) vocabulary와 분류 규칙**을 한 곳에 모은다.

- envelope 형태는 [envelopes.md](envelopes.md)가 SSOT다. 본 문서는 그 envelope의
  `code`/`error.code` 슬롯이 가지는 값의 **vocabulary와 분류**만 다룬다.
- 본 문서는 도메인 exception → public code mapping을 강제 등록 매트릭스로 만들지
  않는다. mapper/helper 도입(#1840)과 drift test(#1841), domain 정렬(#1842/#1843)
  은 후속 이슈 책임이다. 본 문서는 그 후속 이슈가 따라야 할 **명명/분류/허용
  범위 규칙**과 **대표 lock**, **auth middleware code 정책**을 normative로 고정한다.
- 본 문서는 production 코드를 바꾸지 않는다. 본 PR은 docs-only다.

## ErrorSpec 모델 (normative)

안정 에러 코드는 다음 모델로 분류된다.

```python
@dataclass(frozen=True)
class ErrorSpec:
    code: str            # 안정 코드 (SCREAMING_SNAKE_CASE)
    category: Literal[
        "validation",
        "auth",
        "permission",
        "not_found",
        "state_conflict",
        "service_unavailable",
        "external",
        "internal",
    ]
    exit_code: int = 1   # CLI 종료 코드 (기본 1)
    retryable: bool = False  # reserved — 소비자 정해질 때까지 의미 비고정
    default_message: str | None = None
```

본 모델은 문서 SSOT에서 명세하는 normative shape이다. mapper helper의 실제 도입과
runtime 사용은 [#1840](https://github.com/joshua-jingu-lee/ante/issues/1840) 책임이며
본 PR 범위 밖이다.

### 필드 규칙

| 필드 | 규칙 |
|------|------|
| `code` | SCREAMING_SNAKE_CASE 문자열. 도메인 prefix(`ACCOUNT_*`, `BOT_*`, `APPROVAL_*`, `MEMBER_*`, `BROKER_*`, `CONFIG_*`, `STRATEGY_*`, `REPORT_*`, `UPDATE_*`) 또는 도메인이 명확하지 않으면 `CLI_*` prefix. envelope의 `code`/`error.code`에 그대로 들어간다. |
| `category` | 위 8종 Literal 중 하나. 본 문서가 enumerate한 값만 normative. 새 카테고리 도입은 본 문서를 갱신하는 contract change다. |
| `exit_code` | 기본 `1`. click 기본 usage exit 2 전면 정렬은 본 SSOT 범위 밖(별도 이슈). 0(success) + error envelope는 [envelopes.md](envelopes.md)에 의해 금지된다. |
| `retryable` | 기본 `False`. **reserved** — 본 1.0 시점에서 소비자가 정해지지 않았다. CLI/IPC envelope에 직렬화하지 않는다. |
| `default_message` | optional. helper가 사용할 fallback 메시지. envelope `message`는 호출자가 도메인 문구를 제공할 수 있다. |

### Category 의미

| Category | 의미 | 대표 code 예 |
|----------|------|--------------|
| `validation` | 입력 계약 위반(필수 옵션 누락, enum 비멤버, 형식 오류, 도메인 식별자 형식 위반) | `VALIDATION_ERROR`, `CLI_MISSING_REQUIRED_INPUT`, `CLI_OPTION_CONFLICT`, `CONFIG_VALIDATION_ERROR`, `STRATEGY_VALIDATION_ERROR`, `APPROVAL_VALIDATION_ERROR`, `REPORT_VALIDATION_ERROR`, `INVALID_DATE_RANGE`, `INVALID_DATE` |
| `auth` | 인증 누락/실패 | `AUTH_REQUIRED`, `AUTH_FAILED` |
| `permission` | 인증은 됐으나 scope/role 부족 | `PERMISSION_DENIED`, `MEMBER_INVALID_SCOPE` |
| `not_found` | 대상 resource 존재하지 않음 | `BOT_NOT_FOUND`, `ACCOUNT_NOT_FOUND`, `APPROVAL_NOT_FOUND`, `MEMBER_NOT_FOUND` |
| `state_conflict` | 대상이 요청한 상태 전이를 허용하지 않는 상태 | `BOT_STATE_CONFLICT`, `ACCOUNT_ALREADY_DELETED`, `UPDATE_SERVER_RUNNING` |
| `service_unavailable` | 서버 lifecycle / 의존 서비스 미구성으로 dispatch 거부 | `SERVICE_UNAVAILABLE`, `SERVICE_NOT_CONFIGURED` |
| `external` | broker/외부 API 실패로 ante가 dispatch 책임을 다한 뒤 외부 시스템에서 발생한 오류 | `BROKER_API_ERROR`, `BROKER_AUTH_FAILED` |
| `internal` | 코드 버그/예외 미분류 fallback | `EXECUTION_ERROR`, `UNKNOWN_COMMAND` |

위 표는 normative classification이다. 새 code는 본 표의 category 중 하나에
귀속되어야 한다. 어디에도 속하지 않는다면 본 SSOT의 갱신이 선행 조건이다.

## 명명 규칙

본 SSOT는 다음 명명 규칙을 normative로 lock 한다.

1. **모양**: SCREAMING_SNAKE_CASE만 허용. lowercase/CamelCase/dot.separated는 본
   1.0 vocabulary에서 normative가 아니다. 예외는 [Legacy alias](#legacy-alias)
   섹션에서만 등록된다.
2. **도메인 prefix**: 도메인이 명확하면 도메인 prefix를 사용한다(`ACCOUNT_*`,
   `BOT_*`, `APPROVAL_*`, `MEMBER_*`, `BROKER_*`, `CONFIG_*`, `STRATEGY_*`,
   `REPORT_*`, `UPDATE_*`). 도메인이 없으면 `CLI_*` prefix(예:
   `CLI_MISSING_REQUIRED_INPUT`, `CLI_OPTION_CONFLICT`, `CLI_CONFIRMATION_REQUIRED`).
3. **공통 코드**: `VALIDATION_ERROR`, `EXECUTION_ERROR`, `SERVICE_UNAVAILABLE`,
   `SERVICE_NOT_CONFIGURED`, `UNKNOWN_COMMAND`는 도메인 prefix 없이 공통 vocabulary로
   유지한다. 도메인이 명확한 위반은 도메인 prefix specialize를 권장한다.
4. **명명 규칙 예외 (legacy date-range)**: `INVALID_DATE_RANGE` / `INVALID_DATE`는
   `backtest run` CLI가 이미 사용 중인 호환 유지용 legacy/common date-range
   코드로 `CLI_*` prefix 예외다(SSOT: `docs/specs/cli/02-design-decisions.md` —
   본 문서가 reference하는 cli 입력 계약 예외 박스).

## `EXECUTION_ERROR` 허용 범위

`EXECUTION_ERROR`는 `internal` category fallback이다. 다음 두 경우에만 허용된다.

1. **코드 버그 / unexpected programming error** — assertion 실패, `KeyError`,
   `TypeError`, 알 수 없는 `Exception` 등 ante 도메인 의미를 갖지 않는 예외.
2. **Ante domain 밖 외부 라이브러리/OS/network 예외가 taxonomy로 미분류된 경우**
   — 외부 시스템 호출에서 올라온 미분류 `Exception`. 분류 가능한 broker/외부
   오류는 `external` category 코드(예: `BROKER_API_ERROR`)로 분류한다.

**금지** (drift):

- domain exception이 `code` 미부여로 `EXECUTION_ERROR`로 접히는 것.
- domain exception class를 새로 도입하면서 `code` 속성 또는 mapper 등록을
  생략하는 것.
- `fmt.error(str(e))` 처럼 code 없이 CLI error envelope을 노출하는 것(신규/수정
  callsite). drift test guard는 [#1841](https://github.com/joshua-jingu-lee/ante/issues/1841) 책임.

## Auth Middleware Code 정책 (normative)

본 1.0 시점에서 `src/ante/cli/middleware.py`는 다음 lowercase code를 envelope의
`code` 필드에 노출한다 (`src/ante/cli/middleware.py:87,182,235,249,279,293,509,859`).

- `auth_required`
- `auth_failed`
- `permission_denied`

본 SSOT는 다음 두 단계를 normative로 결정한다.

### 결정

1. **현재 단계 (본 PR + #1815/#1816 후속 epic 진행 중)**: lowercase code를
   **유지**한다. 즉시 SCREAMING_SNAKE migration을 강제하지 않는다.
2. **목표 단계**: 본 SSOT는 `AUTH_REQUIRED` / `AUTH_FAILED` / `PERMISSION_DENIED`를
   normative SCREAMING_SNAKE code로 lock 한다. 후속 migration은
   [#1815 CLI command contract epic](https://github.com/joshua-jingu-lee/ante/issues/1815)의 auth registry
   책임이며, migration timing은 본 PR 범위 밖이다.

### Legacy alias

본 SSOT는 다음 alias를 normative legacy alias로 등록한다.

| Normative code | Legacy alias (1.0 envelope value) | Category | 비고 |
|----------------|-----------------------------------|----------|------|
| `AUTH_REQUIRED` | `auth_required` | `auth` | `@require_auth` 미충족 (`ctx.obj["member"] is None`) |
| `AUTH_FAILED` | `auth_failed` | `auth` | `ANTE_MEMBER_TOKEN`으로 `MemberService.authenticate()` 실패 |
| `PERMISSION_DENIED` | `permission_denied` | `permission` | 인증 OK이나 scope 부족 |

규칙:

- **현재 envelope value**: lowercase legacy alias가 그대로 envelope `code`에
  노출된다. 본 SSOT는 lowercase value를 envelope 형태 SSOT(`envelopes.md`)의 1.0
  허용 범위(`code: string`) 안에서 **legacy alias로 명시적으로 허용**한다.
- **새 callsite 금지**: 신규 도입되는 auth-관련 error envelope은 lowercase legacy
  alias를 사용하지 않고 normative SCREAMING_SNAKE code(`AUTH_REQUIRED`/`AUTH_FAILED`/
  `PERMISSION_DENIED`)를 사용한다. 현재 8개 lowercase callsite는 #1815 auth
  registry migration까지 유지된다.
- **소비자 매칭 정책**: oracle/Agent는 본 SSOT의 normative code와 legacy alias를
  같은 fault로 간주해야 한다. drift test(#1841)는 두 표현이 같은 의미를
  가리킨다는 invariant를 lock 한다.
- **drift 정의**: lowercase code의 의미가 SCREAMING_SNAKE 대응값과 1:1
  대응하지 않거나, lowercase가 위 3개 외 다른 값으로 확장되거나, 위 3개 외
  새로운 auth 관련 lowercase code가 도입되면 drift다.

## `SERVICE_NOT_CONFIGURED` (normative)

본 SSOT는 `SERVICE_NOT_CONFIGURED`를 `service_unavailable` category 안정 코드로
등록한다.

- **소비자**: [#1819 IPC CommandSpec metadata epic](https://github.com/joshua-jingu-lee/ante/issues/1819)의
  dispatch wrapper가 `required_services` 부재를 검출할 때 사용한다.
- **의미**: 핸들러가 필요로 하는 service가 `ServiceRegistry`에 구성되어 있지
  않아 dispatch가 거부되는 경우. lifecycle 차원의 `SERVICE_UNAVAILABLE`(서버
  shutdown/draining/stopped)과 의미를 분리한다.
- **분류 차이**:
  - `SERVICE_UNAVAILABLE` — 서버 lifecycle 상태(`SHUTTING_DOWN`/`DRAINING`/
    `STOPPED`) 또는 일시적 dispatch 거부. 본 SSOT의 ipc.md/envelopes.md와 정렬.
  - `SERVICE_NOT_CONFIGURED` — 의존 service가 registry에 없음. 영구적
    misconfiguration. #1819 후속 도입.

## CLI direct ↔ CLI→IPC equivalence — 대표 fault lock

같은 fault는 다음 두 경로에서 같은 public code를 노출해야 한다.

- CLI direct path: command → service → exception → CLI error envelope
- CLI→IPC path: command → `ipc_send` → IPC server → exception → IPC error envelope → CLI error envelope

본 SSOT는 다음 4건을 normative 대표 lock으로 등록한다.

| Domain exception | Public code | Category | 비고 |
|------------------|-------------|----------|------|
| `InvalidAccountIdError` (`src/ante/account/errors.py`) | `VALIDATION_ERROR` | `validation` | `src/ante/ipc/registry.py:151,360,654`에서 이미 `VALIDATION_ERROR`로 정렬됨 (#1633 SSOT) |
| `BotNotFoundError` (`src/ante/bot/exceptions.py`) | `BOT_NOT_FOUND` | `not_found` | `BOT_NOT_FOUND_CODE` 재사용 SSOT (`src/ante/bot/exceptions.py`) |
| `ApprovalNotFoundError` (`src/ante/approval/errors.py`) | `APPROVAL_NOT_FOUND` | `not_found` | class-level `code: str = "APPROVAL_NOT_FOUND"` 부여됨 |
| `MemberInvalidScopeError` (`src/ante/member/errors.py`) | `MEMBER_INVALID_SCOPE` | `permission` | scope 부족 시 권한 분류, lowercase `permission_denied`와 별개의 도메인-prefix code |

규칙:

- 본 4건은 후속 drift test(#1841)와 domain 정렬(#1842) 작업의 회귀 lock이다.
- 새 domain exception을 추가할 때는 본 표 형식으로 후속 PR에서 SSOT를 확장한다.
  본 SSOT는 모든 exception을 enumerate하지 않는다 — 본 PR 범위 밖이다.

## Broker external code 분리

본 SSOT는 broker 원천 code(KIS `msg_cd` 등)와 ante public envelope code를 분리한다.

- **Public envelope code (normative)**: `BROKER_API_ERROR`, `BROKER_AUTH_FAILED`
  같은 ante taxonomy code만 envelope의 `code`/`error.code`로 노출한다. category는
  `external`.
- **원천 code**: KIS `msg_cd`, broker HTTP status, exchange reject reason 등은
  envelope의 `code`/`error.code`로 노출하지 않는다.
  - 옵션 A — `details.broker_code` 필드를 통해 envelope `details` slot 안쪽으로
    노출한다 ([Details 필드 reserved](#details-필드-reserved) 참조).
  - 옵션 B — log-only로 보관한다.
  - 본 PR은 spec만 결정하며 옵션 A/B 중 어느 것으로 구현할지의 결정은 후속
    이슈에 위임한다. 본 SSOT가 lock 하는 것은 "envelope 최상위 code 슬롯에는
    ante taxonomy code만 들어간다"는 invariant다.

## Details 필드 reserved

본 SSOT는 envelope의 `code`/`message` 외의 보조 정보를 위한 **`details: dict | None`
slot을 reserved**로 선언한다.

- **목적**: broker_code, 위반 필드 이름, 위치 정보 등 envelope 본문을 변경하지
  않고 보조 정보를 노출하기 위한 미래 슬롯.
- **현재 상태**: 본 SSOT 1.0은 `details`를 envelope에 강제 도입하지 않는다.
  envelope 4형태의 normative shape은 [envelopes.md](envelopes.md)의 1.0 lock을
  그대로 따른다. `details` 필드 도입의 normative 결정은 별도 SSOT 이슈
  (envelope shape 변경) 책임이다.
- **본 SSOT의 역할**: details slot의 vocabulary(예: `details.broker_code`)에 대한
  의미는 본 문서가 reserved로 등록만 한다. 실제 구현 도입 시 본 문서의 갱신이
  선행 조건이다.

## Redaction 정책 (normative)

envelope `message`(CLI error의 `message`, IPC error의 `error.message`)는 사용자
또는 Agent에게 노출 가능한 텍스트만 포함한다.

**금지 항목**:

- Member token, recovery key, password, plaintext credentials
- Broker API key/secret, app_key/app_secret
- 내부 stack trace 라인, 파일 경로의 시스템 사용자 식별 부분
- 인증 cookie, session ID 등 인증 자료

**규칙**:

- domain exception을 envelope `message`로 변환할 때 호출자는 redaction 책임을
  진다. mapper helper 도입(#1840) 시 redaction 헬퍼가 같은 규칙을 따른다.
- 본 SSOT는 redaction의 **정책 normative**만 lock 한다. redaction 구현 전면화
  (모든 callsite scrub, 자동 검증 test)는 후속 이슈 책임이다.

## Reserved fields 정리

본 SSOT는 다음 필드를 envelope 또는 ErrorSpec에서 **reserved**(현재 1.0에서
강제 도입하지 않으나 미래 의미를 lock)로 선언한다.

| 필드 | 위치 | 1.0 상태 | 비고 |
|------|------|----------|------|
| `retryable` | `ErrorSpec.retryable` | 기본 `False`, reserved | 소비자 정해질 때까지 envelope에 직렬화 금지 |
| `details` | envelope error 슬롯(`error.details` 또는 CLI error의 `details`) | 미도입, reserved | 도입 결정 시 envelope shape SSOT 갱신 선행 |
| `exit_code` | `ErrorSpec.exit_code` | 기본 `1`, 명시적 | click usage exit 2 전면 정렬은 별도 이슈 |

## 후속 작업과 분리

본 SSOT가 lock 하는 항목 vs 후속 이슈에서 다룰 항목.

| 항목 | 본 SSOT(#1839) | 후속 책임 |
|------|----------------|-----------|
| Taxonomy 명명/category/대표 lock | normative | — |
| auth lowercase legacy alias 정책 | normative (유지 + alias 등록) | #1815 auth registry migration |
| `SERVICE_NOT_CONFIGURED` 등록 | normative | #1819 dispatch wrapper 도입 |
| `EXECUTION_ERROR` 허용 범위 | normative | #1841 drift test guard |
| broker external code 분리 (public taxonomy 분리 invariant) | normative | broker 원천 노출 구현 — 별도 이슈 |
| `details` slot 의미 reserved | normative (slot은 도입 안 함) | envelope shape SSOT 갱신 별도 이슈 |
| redaction 정책 | normative (규칙만) | 구현 전면화 — 후속 이슈 |
| `ErrorSpec` mapper / helper 도입 | spec만 (shape) | [#1840](https://github.com/joshua-jingu-lee/ante/issues/1840) |
| drift test guard / fmt.error code 누락 guard | — | [#1841](https://github.com/joshua-jingu-lee/ante/issues/1841) |
| account domain 정렬 + CLI direct↔IPC 동등성 | 대표 lock만 | [#1842](https://github.com/joshua-jingu-lee/ante/issues/1842) |
| 나머지 domain (member/approval/bot/treasury/broker/strategy) 정렬 | — | [#1843](https://github.com/joshua-jingu-lee/ante/issues/1843) |
| Click usage exit code 2 정렬 | — | 별도 이슈 |
| Success JSON output 표준화 | — | [#1815](https://github.com/joshua-jingu-lee/ante/issues/1815) |
| IPC metadata 확장 | — | [#1819](https://github.com/joshua-jingu-lee/ante/issues/1819) |
| Offline service factory | — | [#1818](https://github.com/joshua-jingu-lee/ante/issues/1818) |

## 변경 정책

- 본 SSOT는 1.0 normative이며 taxonomy 변경(새 category, 새 reserved field,
  legacy alias 추가/제거, normative code 재명명)은 contract change다.
- 도메인별 새 안정 code 추가는 본 SSOT의 **명명 규칙과 category 분류**를 따르고
  대표 fault lock 표에 추가하는 후속 PR로 진행한다.
- envelope shape(`code`/`message`/`details` slot 형태) 변경은 본 SSOT가 아닌
  [envelopes.md](envelopes.md)를 우선 갱신한다. 본 SSOT는 그 결과를 reference로
  반영한다.
- auth middleware lowercase legacy alias의 제거는 [#1815](https://github.com/joshua-jingu-lee/ante/issues/1815) auth
  registry migration 완료 시점에 본 SSOT의 [Legacy alias](#legacy-alias) 절을
  갱신하는 후속 PR로 다룬다. 본 PR은 그 시점까지 alias를 normative로 유지한다.

## Non-Goals

본 SSOT가 다루지 **않는** 항목:

- envelope shape(`status`/`code`/`message`/`error.code`/`error.message`/`id`/
  `result`/`data`/`details`)의 정의 — [envelopes.md](envelopes.md) SSOT.
- vocabulary code module(`ContractKind`/`EnvelopeForm`/`AuthMode`) —
  [src/ante/contracts/vocab.py](../../../src/ante/contracts/vocab.py) (#1822) SSOT.
- drift test 공통 helper — [tests/unit/contracts/helpers.py](../../../tests/unit/contracts/helpers.py) (#1823) SSOT.
- migration domain 순서 — [contracts/README.md](README.md)의 Migration Domain
  Order (#1820) SSOT.
- 모든 exception class enumerate / exception → code 전수 매핑 — #1842/#1843
  domain 정렬 PR에서 점진적으로 등록.
- runtime helper/mapper 구현 — [#1840](https://github.com/joshua-jingu-lee/ante/issues/1840).
- drift test 구현 — [#1841](https://github.com/joshua-jingu-lee/ante/issues/1841).
- broker 원천 code 노출 구현 전면화.
- redaction 구현 전면화.
- CLI text mode 출력 형태 / `fmt.error` 사람 친화 문구 표준화.
- success envelope payload migration (#1815).
- IPC `CommandSpec` metadata 확장(`required_services`, audit metadata 등) (#1819).
- offline service factory (#1818).
