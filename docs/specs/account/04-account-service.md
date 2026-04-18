# Account 모듈 세부 설계 - AccountService 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# AccountService 인터페이스

### 생성자

```python
AccountService(db: Database, eventbus: EventBus)
```

### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | `None` | 스키마 생성 + DB에서 계좌 목록 로드 |
| `create` | `account: Account` | `Account` | 계좌 생성. account_id 중복 시 `AccountAlreadyExistsError`. broker_type 유효성 검증 |
| `get` | `account_id: str` | `Account` | 계좌 조회. 없으면 `AccountNotFoundError`. DELETED 상태도 조회 가능 |
| `get_sync` | `account_id: str` | `Account \| None` | 인메모리 캐시에서 동기적으로 계좌 조회. ContextFactory 등 동기 컨텍스트용. 없으면 `None` 반환 |
| `list` | `status: AccountStatus \| None` | `list[Account]` | 계좌 목록 조회. status 필터 가능. DELETED 제외가 기본 |
| `update` | `account_id: str, **fields` | `Account` | 부분 수정. updated_at 자동 갱신. DELETED 계좌는 수정 불가 (`AccountDeletedException`). 불변 필드(`exchange`, `currency`, `trading_mode`, `broker_type`) 포함 시 `AccountImmutableFieldError` |
| `suspend` | `account_id: str, reason: str, suspended_by: str` | `None` | status → SUSPENDED. 이미 SUSPENDED이면 `AccountAlreadySuspendedError` (409). `AccountSuspendedEvent` 발행 + 소속 봇 중지 트리거 |
| `activate` | `account_id: str, activated_by: str` | `None` | status → ACTIVE. DELETED 계좌는 활성화 불가. `AccountActivatedEvent` 발행 |
| `delete` | `account_id: str, deleted_by: str` | `None` | 소프트 딜리트 (status=DELETED). 소속 봇 중지 후 상태 전환. `AccountDeletedEvent` 발행 |
| `get_broker` | `account_id: str` | `BrokerAdapter` | 계좌의 BrokerAdapter 인스턴스 반환. lazy init + 캐싱 |
| `create_default_test_account` | — | `Account` | 테스트 계좌 자동 생성 (`ante init` 시 호출). 이미 존재하면 스킵 |
| `suspend_all` | `reason: str, suspended_by: str` | `int` | 모든 ACTIVE 계좌를 SUSPENDED로 전환. 전환된 수 반환 (시스템 전체 Kill Switch) |
| `activate_all` | `activated_by: str` | `int` | 모든 SUSPENDED 계좌를 ACTIVE로 복구. DELETED 계좌는 대상 제외 |

소스: `src/ante/account/service.py`

### 브로커 인스턴스 생성

`get_broker()`는 `broker_type`으로 `BROKER_REGISTRY`에서 어댑터 클래스를 조회하고, Account의 `credentials`, `broker_config`, `buy_commission_rate`, `sell_commission_rate`를 어댑터 config로 전달하여 인스턴스를 생성한다. 최초 호출 시 생성하고 이후 캐싱한다.

> **`trading_mode`와 `broker_config`의 분리**: `trading_mode`는 시스템이 브로커 API를 실제로 호출할지 결정한다 (VIRTUAL=가상거래, LIVE=실거래). `broker_config`는 브로커 내부 동작 설정을 담는다. 예를 들어 KIS 브로커의 `is_paper`는 모의투자/실전투자 엔드포인트를 결정하는 브로커 내부 관심사이므로 `broker_config`에 속한다. `get_broker()`는 `trading_mode`로부터 `is_paper`를 파생하지 않는다.

### 브로커 캐시 무효화 규칙

브로커 어댑터는 생성 시점의 `credentials`, `broker_config`, `buy_commission_rate`, `sell_commission_rate`를 내부에 고정한다. 따라서 `update()`에서 이 필드 중 하나라도 변경되면 `AccountService`는 다음을 보장한다.

1. 캐시된 기존 어댑터를 `disconnect()`한다 (실패해도 업데이트 자체는 중단되지 않음 — 경고 로그만 기록).
2. 캐시에서 제거한 뒤 새 설정으로 어댑터를 재생성한다.
3. 새 어댑터의 `connect()`까지 수행하여, 이후 `get_broker()` 호출자가 별도 `connect()` 없이 바로 사용할 수 있도록 한다.

`name`, `timezone`, `trading_hours_start`, `trading_hours_end` 등 브로커 설정과 무관한 필드 수정은 기존 어댑터 캐시를 그대로 유지한다.

### 에러 클래스

```python
class AccountError(Exception): ...
class AccountNotFoundError(AccountError): ...
class AccountAlreadyExistsError(AccountError): ...
class InvalidBrokerTypeError(AccountError): ...
class AccountDeletedException(AccountError): ...  # DELETED 계좌 수정/활성화 시도 시
class AccountImmutableFieldError(AccountError): ...  # 불변 필드 수정 시도 시 (exchange, currency, trading_mode, broker_type)
class AccountAlreadySuspendedError(AccountError): ...  # 이미 정지된 계좌 재정지 시도 시 (409)
```

소스: `src/ante/account/errors.py`
