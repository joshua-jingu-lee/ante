# Account 모듈 세부 설계 - Account ID 계약

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

이 문서는 Ante 시스템 전역에서 통용되는 **Account ID 계약**의 SSOT다.
account-scoped 데이터/이벤트/명령은 모두 본 문서가 정의한 형식·정책을
따라야 하며, 모듈별 fallback (None, 빈 문자열, ``"default"``) 사용은
허용되지 않는다.

## 형식

| 항목 | 값 |
|---|---|
| 정규식 | ``^[a-zA-Z0-9\-]{3,30}$`` |
| 길이 | 3 ~ 30자 |
| 허용 문자 | 영문 대소문자, 숫자, 하이픈 |
| 인코딩 | UTF-8 ASCII subset |
| 대소문자 구분 | 구분함 (``"Account"``와 ``"account"``는 별개 ID) |

소스 of truth: ``ante.account.scoping.ACCOUNT_ID_PATTERN``.

## Runtime invalid (어떤 시점에도 거부)

다음 값은 account-scoped 데이터/이벤트/명령에서 **항상** invalid이다.
``ante.account.scoping.is_invalid_account_id``가 ``True``를 반환하고,
``require_account_id``는 :class:`InvalidAccountIdError`를 raise한다.

- ``None``
- 빈 문자열 ``""``
- ``ante.account.scoping.INVALID_RUNTIME_ACCOUNT_IDS`` 멤버:
  - ``"default"``
- ``ACCOUNT_ID_PATTERN``과 불일치하는 모든 값

> ``"default"``는 fallback 예약어이므로 신규 생성도, runtime 사용도
> 불가하다.

## 신규 생성 제한 (creation 시점만 거부)

신규 Account 생성에서는 위 runtime invalid에 더해
``ante.account.scoping.RESTRICTED_NEW_ACCOUNT_IDS`` 멤버를 추가로 거부한다.

- ``"test"`` — bootstrap seed 전용. ``ante init`` →
  :meth:`AccountService.create_default_test_account`로만 생성된다.

따라서 ``"test"``는 **runtime valid**이지만 **creation invalid**이다.
``is_invalid_account_id("test")``는 ``False``,
``validate_new_account_id("test")``는 :class:`InvalidAccountIdError`를 raise.

## Bootstrap seed

``ante init``이 자동 생성하는 ``"test"`` 계좌는 본 helper를 우회하는
**유일한** 경로다.

| 항목 | 값 |
|---|---|
| seed account_id | ``BROKER_PRESETS["test"].default_account_id`` (= ``"test"``) |
| 진입점 | :meth:`AccountService.create_default_test_account` |
| 우회 메커니즘 | private :meth:`AccountService._create_seed_account` helper (only invoked by ``create_default_test_account``) |
| pair 가드 | ``(broker_type, default_account_id)`` 가 ``BROKER_PRESETS`` 의 동일 항목과 정확히 일치해야 함 (#1216 P2) |
| broker_type | ``"test"`` |
| trading_mode | ``VIRTUAL`` |

public :meth:`AccountService.create` API에는 ``_bootstrap`` 같은 우회 플래그가
**노출되지 않는다**. CLI ``ante account create``, Web POST ``/api/accounts``,
IPC handlers를 비롯한 모든 외부 호출자는 ``validate_new_account_id`` 의
RESTRICTED ( ``"test"`` ) / fallback ( ``"default"`` ) 거부를 거치며,
seed 자동 생성은 :meth:`AccountService.create_default_test_account` 만의
책임이다 (#1216 P2).

## fallback 금지 정책

account-scoped 데이터/이벤트는 fallback 값을 **저장하거나 발행하지
않는다**. 다음 경로는 모두 ``require_account_id``로 진입 시점에서
검증되어야 한다 (후속 #1217/#1218/#1219에서 반영).

- account-scoped 명령: ``ante bot/treasury/account ...`` 등
  ``--account`` / ``--account-id`` 옵션을 받는 명령
- account-scoped 이벤트: ``AccountSuspendedEvent``, ``OrderFilledEvent``,
  ``BotStartedEvent`` 등 ``account_id`` 필드를 가진 이벤트
- account-scoped 캐시 키 / DB row 식별자

violations:

| 잘못된 패턴 | 올바른 패턴 |
|---|---|
| ``account_id = config.get("account_id", "default")`` | ``account_id = require_account_id(config.get("account_id"), context="...")``  |
| ``account_id = account_id or ""`` | ``account_id = require_account_id(account_id, context="...")`` |
| 빈 문자열을 wildcard로 해석 | wildcard 의미가 필요하면 별도 sentinel 도입 (1.0 범위 외) |

## invalid account_id 에러코드 (SSOT — #1623/#1633)

이 절은 account-scoped CLI / IPC / oracle 표면에서 invalid
``account_id`` ( ``None`` / 빈 문자열 / ``"default"`` / 패턴 위반 )를
거부할 때 노출되는 **안정 에러코드의 단일 출처(SSOT)** 다. #1623
split A/B/C ( #1634 / #1635 / #1636 ) 및 후속 follow-up은 이 절을
참조하며, 임의의 신규 코드를 도입하지 않는다.

### 결정 — `VALIDATION_ERROR` 재사용 고정

invalid ``account_id``는 다음 세 표면 모두에서 **항상**
``InvalidAccountIdError.code = "VALIDATION_ERROR"`` 코드로 노출된다.

| 표면 | 노출 경로 | 코드 |
|---|---|---|
| account-scoped CLI JSON error | ``require_account_id`` → :class:`InvalidAccountIdError` → CLI JSON error payload | ``VALIDATION_ERROR`` |
| IPC broker dispatch | ``broker.status`` / ``broker.balance`` / ``broker.positions`` / ``broker.reconcile`` handler 의 ``require_account_id`` → :class:`InvalidAccountIdError` → IPC server ``getattr(e, "code", "EXECUTION_ERROR")`` | ``VALIDATION_ERROR`` |
| oracle host probe | ``ANTE_ORACLE_HOST_PROBE_MODE=cli_account_id_invalid_contract`` 가 기대하는 nonzero clean invalid account_id 응답 | ``VALIDATION_ERROR`` |

근거 (코드 현실과 정합):

- ``src/ante/account/errors.py`` 의 ``InvalidAccountIdError.code =
  "VALIDATION_ERROR"`` 클래스 속성. 자동 ``VALIDATION_ERROR`` 매핑은
  IPC server 의 ``getattr(e, "code", "EXECUTION_ERROR")`` 폴백을 타는
  구조이므로 **``require_account_id`` 를 실제로 경유하여
  :class:`InvalidAccountIdError` 가 raise 되는 IPC handler 경로에
  한정**된다. 현재 그 경로는 broker IPC dispatch
  ( ``broker.status`` / ``broker.balance`` / ``broker.positions`` /
  ``broker.reconcile`` — 각 handler 가 ``require_account_id`` 호출,
  ``src/ante/ipc/registry.py:303``/``:318``/``:330``/``:344`` )와
  ``bot.create`` ( ``registry.py:160`` 의 ``require_account_id`` )
  이다. account-scoped CLI JSON error 경로
  ( ``_create_treasury`` / ``_create_rule_engine`` →
  ``Treasury.__init__`` / ``RuleEngine.__init__`` 의
  ``require_account_id`` ) 및 oracle host probe 도 같은 helper 를
  경유하므로 동일하게 ``VALIDATION_ERROR`` 로 노출된다.
- **예외 — 현재 미정렬 경로**: ``treasury.allocate`` /
  ``treasury.deallocate`` IPC 는 ``_handle_treasury_allocate`` /
  ``_handle_treasury_deallocate`` ( ``src/ante/ipc/registry.py:188``/
  ``:199`` )가 ``account_id = args["account_id"]`` 를 그대로
  ``svc.treasury_manager.get(account_id)`` 에 전달하며
  **``require_account_id`` 를 경유하지 않는다**. 따라서 invalid
  ``account_id`` 가 이 두 IPC 에서 ``VALIDATION_ERROR`` 로 **자동
  매핑되지 않는다**(완료/자동매핑으로 오인 금지). 이 정렬은
  결정표 bucket **E** ( ``_handle_treasury_*`` →
  ``treasury_manager.get`` raw ) 의 non-broker mutating IPC
  follow-up 에서 해당 handler 를 ``require_account_id`` 경유로
  정렬할 때 비로소 ``VALIDATION_ERROR`` 로 닫힌다. 결정표
  ``ante treasury allocate`` / ``deallocate`` 행( **E — follow-up
  후보** )과 정합한다.
- IPC 에러코드 계약 가드 ``tests/unit/test_ipc_error_code_mapping.py``
  가 ``InvalidAccountIdError.code == "VALIDATION_ERROR"`` 및
  ``require_account_id`` 경유 IPC 응답 ``error.code ==
  "VALIDATION_ERROR"`` 를 고정한다(미경유
  ``treasury.allocate``/``deallocate`` 는 E follow-up 정렬 시 본
  가드 범위에 편입된다).
- 형식 위반 메시지 자체는 위 [`### 메시지 형식 보존`](#메시지-형식-보존)
  계약을 따른다. 본 절은 **에러코드**의 SSOT이고, 메시지 문자열은
  별도 계약이다(둘은 충돌하지 않는다).

### 신 도메인코드 도입 예외 절차

invalid ``account_id`` 에 ``VALIDATION_ERROR`` 재사용이 불가능하다는
근거(예: IPC 계약 충돌)가 확인되는 경우에만 신 도메인코드를 도입한다.
그 경우 도입을 결정하는 **같은 이슈의 스펙**에 다음을 먼저 남긴다:

1. 재사용 불가 사유 (구체적 충돌 지점),
2. IPC 호환성 영향 (어떤 IPC handler 응답 코드가 바뀌는지),
3. ``tests/unit/test_ipc_error_code_mapping.py`` 등 갱신 대상 테스트 범위.

#1633 은 재사용 고정 결정이므로 본 절차에 해당하지 않는다(신코드 0).

## account-scoped CLI inventory 결정표 (SSOT — #1623/#1633)

이 표는 6개 CLI command 파일( ``account`` / ``bot`` / ``broker`` /
``rule`` / ``strategy`` / ``treasury`` )에서 ``account_id`` 를 입력받는
**모든 Click 입력 표면** ( ``@click.argument("account_id")`` positional
+ account 관련 ``@click.option`` )의 전수 inventory이자 #1623 split
분류 SSOT다. 표 본체는 본 문서에 고정하며,
[`docs/specs/cli/03-commands.md`](../cli/03-commands.md#account-scoped-account_id-입력-표면--14-account-id-contract-참조)
는 본 표를 참조한다.

### enumeration 방법론

- **포함 기준**: Click decorator 기준 — ``@click.argument("account_id")``
  ( positional; 예 ``ante account info default`` 가 #1623 실제 실패
  표면) + account 관련 ``@click.option`` ( ``--account`` /
  ``--account-id`` ). flag-only 한정 금지(positional 누락 0). raw
  ``rg`` line count 는 SQL/출력/payload 비표면 매치를 다수 포함하므로
  검증 기준으로 쓰지 않는다 — **unique CLI command path** 목록으로
  산출한다.
- **diff 분류**: (i) Click decorator 산출 code 목록 ↔ (ii)
  03-commands.md account-scoped command 목록을 비교해
  ``match`` / ``spec-only`` (코드 미등록) / ``code-only`` (spec
  미기재) 로 폐쇄한다.
- **row-count 동치**: 결정표 row 수 == enumerate된 unique command
  path 수( ``match`` + ``code-only`` ) + ``spec-only`` 별도 행. 현
  코드 표면( ``treasury snapshot`` , ``strategy performance`` 포함)
  누락 0.

### 분류 bucket

| bucket | 의미 | #1623 매핑 |
|---|---|---|
| **A** | read-only lookup/filter ingress | #1634 |
| **B** | treasury·rule local construction lifecycle ( ``_create_treasury`` / ``_create_rule_engine`` 경유) | #1635 |
| **C** | broker IPC envelope ( ``broker.status/balance/positions/reconcile`` ) | #1636 |
| **D** | account-lifecycle / cold-path / AccountService mutation — #1634/35/36 범위 아님 | follow-up / 구현대상아님 |
| **E** | non-broker mutating IPC ( ``_handle_treasury_*`` → ``treasury_manager.get`` raw, ``bot.create`` ) — #1634/35/36 범위 아님 | follow-up |

**일반 규칙(구조적 폐쇄)**: enumerate된 **모든** Click ``account_id``
command 표면은 본 표에 **명시 row 1개씩** 필수다(rule-only / implicit
금지). A/B/C 는 **#1623 probe 실패 집합과 동형인 표면만** 배정하며,
그 외(D 계열·E 계열·2-bucket 걸침·진정 애매)는 명시
follow-up / scope-extension / 구현대상아님 / 문서수정 결정으로 닫는다
(임의 배정·누락 0). ``spec-only`` / ``code-only`` 행은 각각
``구현대상아님`` / ``문서수정`` / ``후속`` 중 하나로 확정한다.

### 결정표

| CLI command path | account_id 입력형태 | code/spec 상태 | 진입 패턴 | #1623 split 분류 (결정) |
|---|---|---|---|---|
| `ante account info <account_id>` | positional arg | match | read-only `svc.get` lookup ingress | **A — #1634** (#1623 실제 실패 표면 `account_info_default`/`account_info_bad_pattern`) |
| `ante account credentials <account_id>` | positional arg | match | read-only `svc.get` 마스킹 lookup ingress | **A — #1634** (`account info` 와 동형 read-only ingress) |
| `ante bot list --account <account_id>` | option | match | read-only DB filter ingress | **A — #1634** (#1623 `bot_list_default`) |
| `ante treasury status --account <account_id>` | option | match | local construction lifecycle (`_create_treasury` → `require_account_id`) | **B — #1635** (#1623 `treasury_status_default`) |
| `ante rule list --account <account_id>` | option | match (본 #1633 에서 03-commands.md rule 섹션·명령 표에 `--account <account_id>` 기재 보정 후 `match` 로 닫음 — 보정 전 `code-only`: 코드 `rule.py:93` `@click.option("--account","account_id",required=True)` 존재, 03-commands.md 미기재였음) | local construction lifecycle (`_create_rule_engine` → `RuleEngine.__init__` `require_account_id`) | **B — #1635** (#1623 `rule_list_default`; DB lifecycle 누수 포함) |
| `ante rule info <rule_id> --account <account_id>` | option | match (본 #1633 에서 03-commands.md 보정 후 `match`; 보정 전 `code-only`: 코드 `rule.py:189` `@click.option("--account","account_id",required=True)` 존재, 03-commands.md 미기재였음) | local construction lifecycle (`_create_rule_engine`) | **B — #1635** (`rule list` 와 동형 construction; #1635 본문 `rule info` 포함) |
| `ante broker status --account <account_id>` | option | match | broker IPC dispatch (`broker.status`, handler `require_account_id`) | **C — #1636** |
| `ante broker balance --account <account_id>` | option | match | broker IPC dispatch (`broker.balance`) | **C — #1636** (#1623 `broker_balance_default`) |
| `ante broker positions --account <account_id>` | option | match | broker IPC dispatch (`broker.positions`) | **C — #1636** |
| `ante broker reconcile --account <account_id>` | option | match | broker IPC dispatch (`broker.reconcile`) | **C — #1636** |
| `ante account suspend <account_id>` | positional arg | match | AccountService mutation / lifecycle (runtime IPC) | **D — follow-up 후보** (account-lifecycle invalid account_id 점검; #1623 probe 집합 아님 — #1634/35/36 임의 포함 금지) |
| `ante account activate <account_id>` | positional arg | match | AccountService mutation / lifecycle (runtime IPC) | **D — follow-up 후보** (동 lifecycle/mutation) |
| `ante account delete <account_id>` | positional arg | match | AccountService mutation / lifecycle (cold-path) | **D — follow-up 후보** (동 lifecycle/mutation) |
| `ante account set-credentials <account_id>` | positional arg | match | AccountService mutation (cold-path) | **D — follow-up 후보** (동 lifecycle/mutation) |
| `ante account repair-timezone <account_id> <new_timezone>` | positional arg | match | AccountService mutation (cold-path) | **D — follow-up 후보** (동 lifecycle/mutation) |
| `ante account create --account-id <account_id>` | option | match | 신규 Account 생성 (cold-path) | **D — 구현대상아님** (`validate_new_account_id` cold-path 가 이미 검증 — 별도 계약, #1623 drift 아님) |
| `ante treasury allocate <bot_id> <amount> --account <account_id>` | option | match | non-broker mutating IPC (`treasury.allocate` → `_handle_treasury_allocate` → `treasury_manager.get` **raw**, `require_account_id` 미경유) | **E — follow-up 후보** (#1635 construction-lifecycle 범위 아님; #1623 probe 집합 아님) |
| `ante treasury deallocate <bot_id> <amount> --account <account_id>` | option | match | non-broker mutating IPC (`treasury.deallocate` → `_handle_treasury_deallocate` → `treasury_manager.get` **raw**) | **E — follow-up 후보** (동 mutating IPC) |
| `ante bot create --account <account_id>` | option | match | mutating IPC (`bot.create` handler `require_account_id`; 단 `--account` 생략 시 single-active resolver) | **E — follow-up 후보** (#1623 probe 집합 아님; 구현 시 경로 확인 후 동 결정) |
| `ante treasury snapshot --account <account_id>` | option | match | read-only persisted snapshot 조회 (`_create_treasury` → `require_account_id`) | **E — follow-up 후보** (#1623 probe 집합 아님; `treasury status` 와 helper 공유하나 #1635 본문은 `treasury status`로 한정 — 임의 #1635 확장 금지, 동 follow-up) |
| `ante strategy performance <name> --account-id <account_id>` | option | match | read-only 성과 DB 집계 (#1218 edge resolver 제거, `--account-id` required) | **E — follow-up 후보** (#1623 probe 집합 아님; #1634 read-only ingress 와 패턴 유사하나 probe 실패 집합 외 — 임의 #1634 포함 금지, 동 follow-up) |
| `ante broker health [--account <account_id>]` | option | **spec-only** (03-commands.md:114·400 에 기재; `broker.py` 미등록 — status/balance/positions/reconcile 만 존재) | (코드 미존재) | **문서수정** (03-commands.md drift 교정 후속; 코드 표면 없으므로 #1634/35/36 비대상) |
| `ante broker price <symbol> [--account <account_id>]` | option | **spec-only** (03-commands.md:117·403 에 기재; `broker.py` 미등록) | (코드 미존재) | **문서수정** (03-commands.md drift 교정 후속; 코드 표면 없으므로 #1634/35/36 비대상) |

> row-count 동치 검증: 위 표 결정 row 23개 = code 표면 21개( ``match`` ;
> ``code-only`` 0) + ``spec-only`` 2개( ``broker health`` /
> ``broker price`` ). enumerate된 unique CLI command path 수 21개와
> 동치(누락 0). ``treasury snapshot`` · ``strategy performance`` 포함.
>
> match/spec-only/code-only 집계: ``match`` 21 / ``spec-only`` 2 /
> ``code-only`` 0. ``rule list`` · ``rule info`` 는 코드
> ( ``src/ante/cli/commands/rule.py:93``/``:189`` 의
> ``@click.option("--account","account_id",required=True)`` )에는 존재하나
> 03-commands.md rule 섹션·offline 명령 표에는 미기재였으므로 본 정정
> **이전** 상태는 ``code-only`` 2 였다. 본 #1633 (docs-only)이
> 03-commands.md 의 rule 섹션·offline 명령 표 양쪽에 rule
> ``--account <account_id>`` 표면을 함께 기재 보정하여 두 행을
> ``code-only → match`` 로 닫았다(일관 처리: 동일 docs-only 범위 내
> 03-commands.md drift 즉시 교정이 ``code-only`` 후속 항목을 별도로
> 미루는 것보다 정합적이고 row-count·집계 동치를 보존). 따라서 보정 후
> 최종 ``code-only`` 0, 위 23/21/2 동치는 유지된다. ``rule`` 행의
> #1623 split 분류는 정정과 무관하게 **B(#1635, rule construction
> lifecycle)** 로 불변이다(상태 컬럼만 정정, 분류·진입 패턴·row 수
> 무변경).

> D/E = follow-up 항목( ``account suspend/activate/delete/set-credentials/repair-timezone`` ,
> ``treasury allocate/deallocate`` , ``bot create`` ,
> ``treasury snapshot`` , ``strategy performance`` )은 본 이슈
> #1633 의 통합 follow-up 후보로 묶이며 사람이 등록한다(자동 생성
> 금지). ``account create`` ( ``validate_new_account_id`` 가 이미
> 검증)와 ``broker health`` / ``broker price`` ( spec-only, 코드
> 표면 없음)는 follow-up 대상이 아니다.

## Helper API

소스: ``src/ante/account/scoping.py``.

```python
from ante.account.scoping import (
    ACCOUNT_ID_PATTERN,           # re.Pattern[str]
    INVALID_RUNTIME_ACCOUNT_IDS,  # frozenset[str] = {"default"}
    RESTRICTED_NEW_ACCOUNT_IDS,   # frozenset[str] = {"test"}
    is_invalid_account_id,        # (str | None) -> bool
    require_account_id,           # (str | None, *, context: str = "") -> str
    validate_new_account_id,      # (str | None) -> str
)
```

| 함수 | 사용 시점 | 거부 대상 | 예외 |
|---|---|---|---|
| ``is_invalid_account_id`` | runtime branch (boolean check만 필요할 때) | ``None``/``""``/``"default"``/패턴 위반 | — (bool 반환) |
| ``require_account_id`` | account-scoped 명령/이벤트/캐시 진입점 | 위와 동일 | :class:`InvalidAccountIdError` |
| ``validate_new_account_id`` | 신규 Account 생성 (cold-path) | 위 + ``"test"`` | :class:`InvalidAccountIdError` |

### 메시지 형식 보존

``validate_new_account_id``의 형식 위반 메시지는 기존
``AccountService.create``의 ``InvalidAccountIdError`` 형식을 보존한다:

```
account_id 형식이 올바르지 않습니다: '<value>'. 영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다.
```

이 형식은 ``ante account create`` CLI 표면에서 ``str(e)``로 그대로
노출되므로 수정하면 사용자/Agent의 에러 처리 표면이 깨진다.

## 사용처 (1.0)

| 호출 위치 | 함수 | 비고 |
|---|---|---|
| ``AccountService.create`` (public) | ``validate_new_account_id`` | 우회 수단 없음. seed 예약어 ``"test"`` 도 무조건 거부 (#1216 P2) |
| ``AccountService._create_seed_account`` (private) | ``require_account_id`` + ``(broker_type, default_account_id)`` pair 가드 | ``create_default_test_account`` 만의 호출 경로 |
| ``AccountService.create_default_test_account`` | (private helper 호출) | seed account_id ``"test"`` 직접 사용 |

### #1217 후속 SPLIT 분담

#1217 (단일 PR)이 9회 Codex review FAIL → SPLIT 권고에 따라 다음 3개
이슈로 분리되어 진행한다. 각 SPLIT은 lifecycle 영향 / 적용 표면을
구분하며, write/execute 경로 fallback 제거 + Event marker 패턴은
SPLIT 단위로 다음 표에 기재된 위치에서만 적용한다.

#### #1240 (SPLIT-1) 적용 위치

write/execute 경로 fallback 제거 + Event marker 패턴 (lifecycle 영향
없는 contract drift). 본 SPLIT에서 적용된다.

| 호출 위치 | 형태 | 비고 |
|---|---|---|
| `Event.__post_init__` (eventbus/events.py) | ClassVar marker `_requires_account_id` + `is_invalid_account_id` 검증 | account-scoped 이벤트 20+개. 마커 정책은 [`docs/specs/eventbus/eventbus.md`](../eventbus/eventbus.md) `Account-scoped 이벤트 marker (#1217 → #1240 SPLIT-1)` 섹션 참조 |
| `Treasury.__init__` | `account_id: str` (kw-only) + `require_account_id` | account-scoped 자금 관리 |
| `RuleEngine.__init__` | `account_id: str` (kw-only) + `require_account_id` | account-scoped 룰 엔진 |
| `RuleContext.__post_init__` | `require_account_id` | account-scoped 룰 평가 |
| `TradeRecord.__post_init__` | `require_account_id` | trades 테이블 write |
| `PositionSnapshot.__post_init__` | `require_account_id` | positions 캐시 write |
| `BotBudget` | `account_id: str` (required field) | bot_budgets 테이블 write |
| `DailyReportScheduler.__init__` | `account_id: str` (kw-only) + `require_account_id` | 일일 리포트 발행 |
| `PositionReconciler.reconcile` | `account_id: str` (kw-only) | 포지션 보정 |
| `TradeService.correct_position/insert_adjustment` | `account_id: str` (kw-only) | trade 보정 |
| `TradeRecorder.save_adjustment` | `account_id: str` (kw-only) + `require_account_id` | adjustment write |
| `PositionHistory.force_update/_update_position/_update_cache` | `account_id: str` (kw-only) | 포지션 강제 갱신 |
| IPC handlers (`broker.status/balance/positions/reconcile`) | `args["account_id"]` 진입 시 `require_account_id` | IPC routing (account-scoped command payload) |
| CLI commands (`treasury status/snapshot/allocate/deallocate`, `rule list/info`) | `--account` required | CLI UX |
| Web routes (`treasury`, `trades`) | runtime fallback (`getattr(..., "account_id", "")`) 제거 | write 경로 검증 활용 (read endpoint 정책 미변경) |

#### #1241 (SPLIT-2) 적용 위치

Bot/Main + Approval payload validation. 본 SPLIT 에서 적용 완료
(`#1217 → #1241 SPLIT-2`). CLI `--account required` 부분은 #1218 / #1219
범위로 분리되어 있어 본 SPLIT 에는 포함되지 않는다.

| 호출 위치 | 형태 | 비고 |
|---|---|---|
| `BotConfig.__post_init__` | `require_account_id` | 봇 생성 진입점 (#1217 → #1241 SPLIT-2) |
| `BotManager.load_from_db` | invalid account_id row warning + skip | SPLIT-1 패턴 (#1217 → #1241 SPLIT-2) |
| `cold_path_remove_bot` | `or "test"` fallback 제거 → `require_account_id` | cold-path bot delete (#1217 → #1241 SPLIT-2) |
| `ApprovalService.create/reopen` | account-scoped type (`budget_change`, `rule_change`, `bot_create`) 시 config-first → flat `params["account_id"]` 검증 | approval payload validation (#1217 → #1241 SPLIT-2) |
| `AutoApproveEvaluator.should_auto_approve` (`bot_create`) | mode 추출도 config-first → flat fallback | 자동 승인 (#1217 → #1241 SPLIT-2) |
| IPC `bot.create` payload | `args["account_id"]` 진입 시 `require_account_id` | IPC bot routing (#1217 → #1241 SPLIT-2) |
| `main.py` `_exec_rule_change` / `_exec_budget_change` / `_validate_budget_change` | `params.get("account_id", "test")` 제거 → `require_account_id` (validator 는 fail 반환) | approval executor/validator (#1217 → #1241 SPLIT-2) |
| CLI `bot create/remove/...`, `approval` 호출부 | `--account` required | CLI UX (#1218 영역, 본 SPLIT 미포함) |

#### #1242 (SPLIT-3) 적용 위치

APIGateway/Stream + multi-account lifecycle. 본 SPLIT 에서 적용 완료
(`#1217 → #1242 SPLIT-3`). DB schema (#1219) 와 read query 정책 (#1218)
은 별도 SPLIT 으로 분리되어 있으며, 동적 account add/remove 의 hot
reconfig 는 1.0 범위 외이다.

| 호출 위치 | 형태 | 비고 |
|---|---|---|
| `APIGateway.get_ohlcv/get_current_price/get_positions/get_account_balance/submit_order/cancel_order` | `account_id: str` (kw-only) + `require_account_id` | broker routing 진입점 (#1217 → #1242 SPLIT-3) |
| `StreamIntegration.__init__` | `account_id: str` (kw-only) + `require_account_id` | account-scoped 캐시 키 / stop_order trigger 격리 (#1217 → #1242 SPLIT-3) |
| `LiveDataProvider.__init__` | `account_id: str` (kw-only) + `require_account_id`, 내부 `_gateway.get_*` 호출 시 `account_id=self._account_id` 전달 | 봇 단위 인스턴스화 (`context_factory` 가 `BotConfig.account_id` 로 생성, strategy 인터페이스는 closure 방식으로 무변경) (#1217 → #1242 SPLIT-3) |
| `s.stream_integrations: dict[str, StreamIntegration]` | KIS 활성 계좌마다 인스턴스 등록, shutdown 에서 dict 순회 정리 | multi-account lifecycle pool, leak 방지 (#1217 → #1242 SPLIT-3) |
| `s.reconcile_schedulers: dict[str, ReconcileScheduler]` | 활성 broker 가 있는 모든 계좌에 dispatch | multi-broker pool, 첫 broker 선택 가드 제거 (#1217 → #1242 SPLIT-3) |
| `StopOrderManager.on_price_update` | `account_id: str` (kw-only) + `require_account_id`, `active_for_symbol` 에 `o.account_id == account_id` 필터 | cross-account trigger 차단 (#1217 → #1242 SPLIT-3) |
| `StopOrder.__post_init__` | `require_account_id(self.account_id)` | trigger payload 정합 (#1217 → #1242 SPLIT-3) |
| `StreamConnectedEvent` / `StreamDisconnectedEvent` | `_requires_account_id: ClassVar[bool] = True` + `account_id` 발행자 전달 | `KISStreamClient` per-account 인스턴스 정책 (#1217 → #1242 SPLIT-3) |
| `ResponseCache.invalidate` | substring → prefix-exact (`acc-1` invalidate 가 `acc-12` 유지) | account-scoped 캐시 키 격리 (#1217 → #1242 SPLIT-3) |
| `VirtualExecutor` / `_resolve_price` 호출 사이트 | `account_id` 명시 전달 | gateway/stream_integration ctor required 정렬 (#1217 → #1242 SPLIT-3) |

후속 영역은 다음 이슈로 이관:

- **#1218 (Edge resolver)** — account 생략 query의 all-account 정책 정렬,
  edge resolver, `strategy_performance` 계좌 추출. 본 SPLIT 에서 적용 완료
  (#1218 Edge resolver).
- **#1219 (DB schema)** — bot_budgets/treasury_state/trades/positions 테이블의
  `DEFAULT 'default'`/`DEFAULT 'test'` 제거 + NOT NULL 강제.

#### #1218 (Edge resolver) 적용 위치

Read query 정책 정렬 + edge resolver. 본 SPLIT 에서 적용 완료
(#1218 Edge resolver). DB schema (#1219) 는 별도 SPLIT 으로 분리되어 있다.

| 호출 위치 | 형태 | 비고 |
|---|---|---|
| CLI `strategy performance` (`src/ante/cli/commands/strategy.py`) | `--account-id` required, 미지정 시 `STRATEGY_MISSING_REQUIRED_ACCOUNT` 에러 | edge resolver 제거, query 정책 일관 (#1218 Edge resolver) |
| Web `GET /api/strategies` cumulative_return | 봇 미발견 strategy는 `cumulative_return = None`, `"default"` fallback 금지 | `StrategyListItem.cumulative_return: float \| None` 호환 (#1218 Edge resolver) |
| Web `GET /api/strategies/{id}/performance` | account_id query 미지정 + 봇에서 추출 불가 시 400 | `"default"` fallback 제거 (#1218 Edge resolver) |
| Web `GET /api/treasury` / `/api/portfolio/*` | account_id 미지정 = all-account 집계 (현재 분기 보존, 응답 schema 보존) | single-detail (`snapshot/{date}`) 은 명시 필수 (#1218 Edge resolver) |
| Web `POST /api/bots` resolver | `_resolve_single_active` 패턴 (정확히 1개일 때만 자동, 0/2+은 400 `BOT_MISSING_REQUIRED_ACCOUNT`) | CLI `_resolve_account_non_interactive` 와 일관 (#1218 Edge resolver) |
| `report.feedback.PerformanceFeedback.get_bot_performance` | bot 미발견 시 `BotNotFoundError` raise | `"default"` fallback 제거 (#1218 Edge resolver) |

## 테스트 게이트

| 테스트 파일 | 보장 |
|---|---|
| ``tests/unit/test_account_scoping.py`` | helper 12+ case (runtime/creation 정책 분리, 메시지 형식, ``"test"`` runtime valid / creation invalid) |
| ``tests/unit/test_account.py`` | ``AccountService.create``가 helper를 사용함 (``"default"``/``""``/``"test"`` 거부, bootstrap 경로 통과, 메시지 형식 보존) |
| ``tests/unit/test_cli_account_integration.py`` | CLI ``ante account create`` 메시지 형식 보존 (``str(e)`` contract) |
