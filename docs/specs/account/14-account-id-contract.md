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
| 우회 메커니즘 | ``AccountService.create(account, _bootstrap=True)`` 내부 키워드 |
| broker_type | ``"test"`` |
| trading_mode | ``VIRTUAL`` |

다른 모든 호출자(CLI ``ante account create``, Web POST ``/api/accounts``,
IPC handlers)는 ``_bootstrap`` 인자를 사용해서는 안 된다.

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
| ``AccountService.create`` | ``validate_new_account_id`` | bootstrap 경로는 ``_bootstrap=True``로 우회 |
| ``AccountService.create_default_test_account`` | (우회) | seed account_id ``"test"`` 직접 사용 |

후속 사용처는 #1217/#1218/#1219 영역이다 (본 이슈 범위 외):

- **#1217 (Trade/Treasury)** — `account_id` 진입점에서 ``require_account_id``
  호출, fallback (``"default"``, ``""``) 제거.
- **#1218 (CLI/Web/IPC)** — account-scoped 명령/엔드포인트 진입점에서
  ``require_account_id`` 호출.
- **#1219 (Event/EventBus)** — account-scoped 이벤트 발행 직전
  ``require_account_id`` 호출, 구독 측 fallback 제거.

## 테스트 게이트

| 테스트 파일 | 보장 |
|---|---|
| ``tests/unit/test_account_scoping.py`` | helper 12+ case (runtime/creation 정책 분리, 메시지 형식, ``"test"`` runtime valid / creation invalid) |
| ``tests/unit/test_account.py`` | ``AccountService.create``가 helper를 사용함 (``"default"``/``""``/``"test"`` 거부, bootstrap 경로 통과, 메시지 형식 보존) |
| ``tests/unit/test_cli_account_integration.py`` | CLI ``ante account create`` 메시지 형식 보존 (``str(e)`` contract) |
