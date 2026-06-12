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
| `create` | `account: Account` | `Account` | 계좌 생성. **cold-path 전용**. account_id 형식/정책 검증은 [`validate_new_account_id`](14-account-id-contract.md) helper에 위임 (``"test"``, ``"default"``, ``None``, ``""``, 패턴 위반 거부). 우회 플래그를 노출하지 않으므로 외부 호출자는 RESTRICTED ( ``"test"`` ) 예약어를 신규 생성할 수 없다 (#1216 P2). account_id 중복 시 `AccountAlreadyExistsError`. broker_type 유효성 검증. seed 자동 생성은 :meth:`create_default_test_account` 가 private helper :meth:`_create_seed_account` 를 통해서만 수행한다 |
| `get` | `account_id: str` | `Account` | 계좌 조회. 없으면 `AccountNotFoundError`. DELETED 상태도 조회 가능 |
| `get_sync` | `account_id: str` | `Account \| None` | 인메모리 캐시에서 동기적으로 계좌 조회. ContextFactory 등 동기 컨텍스트용. 없으면 `None` 반환 |
| `list` | `status: AccountStatus \| None` | `list[Account]` | 계좌 목록 조회. status 필터 가능. DELETED 제외가 기본 |
| `update` | `account_id: str, **fields` | `Account` | 부분 수정. 런타임에는 비구조 필드만 허용. structural field 포함 시 `AccountStructuralChangeRequiresStoppedServerError`. DELETED 계좌는 수정 불가 (`AccountDeletedException`). 불변 필드(`exchange`, `currency`, `trading_mode`, `broker_type`) 포함 시 `AccountImmutableFieldError` |
| `suspend` | `account_id: str, reason: str, suspended_by: str` | `None` | status → SUSPENDED. 이미 SUSPENDED이면 `AccountAlreadySuspendedError` (409). `AccountSuspendedEvent` 발행 + 소속 봇 중지 트리거 |
| `activate` | `account_id: str, activated_by: str` | `None` | status → ACTIVE. DELETED 계좌는 활성화 불가. `AccountActivatedEvent` 발행 |
| `delete` | `account_id: str, deleted_by: str` | `None` | 소프트 딜리트 (status=DELETED). **cold-path 전용**. active Ante runtime이 살아 있으면 거부. 진입 직후 `bots` 테이블을 검사해 동일 `account_id`의 활성(non-deleted) 봇이 남아 있으면 `AccountHasActiveBotsError`로 차단(orphan bot 무결성). 1.0 정책상 `AccountDeletedEvent`는 발행하지 않는다 |
| `get_broker` | `account_id: str` | `BrokerAdapter` | 계좌의 BrokerAdapter 인스턴스 반환. lazy init. 최초 호출 시 생성하고 `connect()`를 수행하여 **연결에 성공한 경우에만 캐싱**한다. 연결 실패 시 캐시에 남기지 않고 예외를 전파하므로(미연결 어댑터 잔존 차단), 일시적 인증/네트워크 실패는 다음 호출에서 자연 회복한다. cache-hit은 connect 없이 즉시 반환. cache-miss는 per-account lock으로 직렬화하여 동시 호출 시에도 단일 인스턴스·단일 connect를 보장한다 |
| `get_cached_broker` | `account_id: str` | `BrokerAdapter \| None` | 이미 캐시된 BrokerAdapter만 반환(build/connect 없음). 미캐시면 `None`. 종료 루프처럼 "이미 연결된 어댑터만 끊는" 경로 전용 — 미캐시 계좌를 끊기 위해 새로 연결하는 회귀를 차단한다(동기 메서드) |
| `create_default_test_account` | — | `Account` | 테스트 계좌 자동 생성 (`ante init` 시 호출). 이미 존재하면 스킵 |
| `suspend_all` | `reason: str, suspended_by: str` | `int` | 모든 ACTIVE 계좌를 SUSPENDED로 전환. 전환된 수 반환 (시스템 전체 Kill Switch) |
| `activate_all` | `activated_by: str` | `int` | 모든 SUSPENDED 계좌를 ACTIVE로 복구. DELETED 계좌는 대상 제외 |

소스: `src/ante/account/service.py`

### 브로커 인스턴스 생성

`get_broker()`는 `broker_type`으로 `BROKER_REGISTRY`에서 어댑터 클래스를 조회하고, Account의 `credentials`, `broker_config`, `buy_commission_rate`, `sell_commission_rate`를 어댑터 config로 전달하여 인스턴스를 생성한다. 최초 호출 시 생성하고 이후 캐싱한다.

**캐시-연결 의미론**: `get_broker()`는 최초 생성 경로에서 어댑터의 `connect()`를 수행하고 **연결 성공 후에만 캐시에 기록**한다. connect가 실패하면 캐시에 어댑터를 남기지 않고 예외를 그대로 전파한다 — 일시적 인증/네트워크 실패로 `is_connected=False`인 미연결 어댑터가 캐시에 잔존해 장기 실행 runtime의 후속 소비자가 이를 재사용하는 일을 막는다. 이 원칙은 재연결 경로(`_reconnect_broker`)의 connect-성공-후-캐시 의미론과 동일하다. cache-hit 경로(런타임 hot-path)는 connect 호출 없이 캐시된 인스턴스를 즉시 반환한다.

**connect 멱등**: 모든 BrokerAdapter의 `connect()`는 멱등이다 — 이미 연결된 상태(`is_connected`이고 활성 세션 보유)면 새 세션을 만들지 않고 no-op으로 반환한다. 따라서 `get_broker()`가 connect한 어댑터에 호출자가 `connect()`를 재호출해도 세션 교체로 인한 누수가 없다. cache-miss 경로는 per-account 락으로 직렬화하고 락 안에서 캐시를 재검사(double-checked)하므로, 동일 계좌의 동시 `get_broker()` 호출도 단일 인스턴스·단일 connect로 수렴한다.

**cached-only 조회**: `get_cached_broker()`는 이미 캐시된 어댑터만 반환하며(build/connect 없음), 미캐시면 `None`을 반환한다. 종료 루프처럼 "이미 연결된 어댑터만 끊으면 되는" 경로는 이 접근자를 사용해, 미캐시 계좌를 끊기 위해 새로 인증/연결하는 회귀를 피한다(미캐시 = 끊을 연결도 없음).

> **`trading_mode`와 `broker_config`의 분리**: `trading_mode`는 시스템이 브로커 API를 실제로 호출할지 결정한다 (VIRTUAL=가상거래, LIVE=실거래). `broker_config`는 브로커 내부 동작 설정을 담는다. 예를 들어 KIS 브로커의 `is_paper`는 모의투자/실전투자 엔드포인트를 결정하는 브로커 내부 관심사이므로 `broker_config`에 속한다. `get_broker()`는 `trading_mode`로부터 `is_paper`를 파생하지 않는다.

### 런타임 구조 변경 차단

브로커 어댑터와 계좌별 consumer(Treasury, RuleEngine, Gateway, BotManager)는 서버 시작 시점의
계좌 topology를 기준으로 구성된다. 따라서 런타임 중에는 계좌 구조를 바꾸지 않는다.

**런타임 허용 필드**:
- `name`
- `timezone`
- `trading_hours_start`
- `trading_hours_end`
- 향후 추가되는 표시/운영 메타데이터 중 브로커 재초기화가 필요 없는 필드

**cold-path 전용 필드/작업** (9 필드):
- `create()`
- `delete()`
- `credentials`
- `broker_config`
- `buy_commission_rate`
- `sell_commission_rate`
- `market_order_reserve_buffer_rate` (#1333: Treasury 시장가 매수 reserve 정책)
- 계좌 생성 후 불변 필드: `exchange`, `currency`, `trading_mode`, `broker_type`

#### service-layer 가드 (#1144)

`AccountService`는 boot/cold-path/runtime을 구분하는 `_runtime_started: bool` 플래그를 갖는다(기본값 `False`). 부팅 시점에 일어나는 mutation — `create_default_test_account()`(계좌 0개 자동 생성)와 `_migrate_is_paper_to_broker_config()`(KIS 계좌 `broker_config` update) — 이 모두 끝난 직후 `main._init_account`가 `account_service.mark_runtime_started()`를 호출해 플래그를 `True`로 전환한다. `mark_runtime_started`는 멱등이며, 이후 cold-path 전용 메서드/필드 변경 요청은 다음 invariant에 따라 즉시 차단된다.

- **가드 우선순위**: `create()` / `delete()` / `update()`의 런타임 가드는 `get()`/DELETED/IMMUTABLE 등 어떤 다른 검사보다 *먼저* 평가된다. 즉, 존재하지 않거나 DELETED 상태인 계좌에 structural 키가 들어오더라도 cold-path 응답이 우선이다(structural cold-path > existence > deleted > immutable). `update()` 가드는 raw kwargs 키만 보고 값(None 포함)은 무관하다 — `update(account_id, credentials=None)`도 키 존재만으로 차단된다.
- **mutable-only 흐름**: structural 키와 교집합이 없는 호출(예: `update(account_id, name="…", timezone="…")`)은 런타임에서도 정상 동작한다. 가드는 `set(fields) & STRUCTURAL_FIELDS`가 비어 있으면 통과한다.
- **structural 필드 정합 (S4)**: service의 `STRUCTURAL_FIELDS` 상수 9개(#1333 으로 `market_order_reserve_buffer_rate` 추가)가 cold-path 가드의 단일 기준이다.
- **부팅 mutation 보호 (S3)**: `mark_runtime_started` 호출은 boot mutation 종료 *후*로 고정된다. migration이 플래그 활성 후로 옮겨가면 자기 자신의 structural `broker_config` update가 차단되어 부팅이 깨진다 — `tests/unit/test_account_runtime_init_order.py`가 이 순서를 강제한다.

#### 안정 에러 코드 (#1144 S5)

`AccountStructuralChangeRequiresStoppedServerError`는 클래스 레벨 속성 `code: str = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"`를 노출한다. IPC 서버는 모든 핸들러 예외에 대해 `getattr(e, "code", "EXECUTION_ERROR")`로 안정 코드를 우선 사용하며(없으면 기본 `EXECUTION_ERROR`), 기존 예외(`AccountAlreadySuspendedError` 등)는 `code` 속성이 없으므로 자동으로 `EXECUTION_ERROR`로 폴백되어 회귀가 발생하지 않는다.

#### CLI / 다중 active runtime 정책

CLI cold-path 명령(`ante account create/delete/set-credentials`)은 `_assert_no_active_runtime` guard(PID alive + IPC socket exists)로 서버 실행 여부를 먼저 확인하고, runtime이 살아 있으면 서비스 메서드를 호출하지 않는다(#1139). service-layer 가드는 그 1차 가드를 우회한 비정상 경로(예: 직접 코드 호출, 테스트 monkeypatch, 또는 향후 도입될 IPC `account.create/update`/등 핸들러)의 defense-in-depth 역할이다. 1.0 정책상 동일 OS user/home server 기준으로 active runtime은 항상 단일이며, `config_dir`은 데이터/설정 프로필 경계지 동시 namespace가 아니다.

### 에러 클래스

```python
class AccountError(Exception): ...
class AccountNotFoundError(AccountError): ...
class AccountAlreadyExistsError(AccountError): ...
class InvalidBrokerTypeError(AccountError): ...
class AccountDeletedException(AccountError): ...  # DELETED 계좌 수정/활성화 시도 시
class AccountImmutableFieldError(AccountError): ...  # 불변 필드 수정 시도 시 (exchange, currency, trading_mode, broker_type)
class AccountAlreadySuspendedError(AccountError): ...  # 이미 정지된 계좌 재정지 시도 시 (409)
class AccountStructuralChangeRequiresStoppedServerError(AccountError): ...  # 런타임 구조 변경 차단
class AccountHasActiveBotsError(AccountError): ...  # delete() 시 활성(non-deleted) 봇 잔존 시 (orphan bot 무결성)
```

소스: `src/ante/account/errors.py`
