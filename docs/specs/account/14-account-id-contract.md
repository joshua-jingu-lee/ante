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
| `PaperExecutor` / `_resolve_price` 호출 사이트 | `account_id` 명시 전달 | gateway/stream_integration ctor required 정렬 (#1217 → #1242 SPLIT-3) |

후속 영역은 다음 이슈로 이관:

- **#1218 (Read query 정책)** — account 생략 query의 all-account 정책 정렬,
  edge resolver, `strategy_performance` 계좌 추출.
- **#1219 (DB schema)** — bot_budgets/treasury_state/trades/positions 테이블의
  `DEFAULT 'default'`/`DEFAULT 'test'` 제거 + NOT NULL 강제.

## 테스트 게이트

| 테스트 파일 | 보장 |
|---|---|
| ``tests/unit/test_account_scoping.py`` | helper 12+ case (runtime/creation 정책 분리, 메시지 형식, ``"test"`` runtime valid / creation invalid) |
| ``tests/unit/test_account.py`` | ``AccountService.create``가 helper를 사용함 (``"default"``/``""``/``"test"`` 거부, bootstrap 경로 통과, 메시지 형식 보존) |
| ``tests/unit/test_cli_account_integration.py`` | CLI ``ante account create`` 메시지 형식 보존 (``str(e)`` contract) |
