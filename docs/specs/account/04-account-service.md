# Account 모듈 세부 설계 - AccountService 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# AccountService 인터페이스

### 생성자

정의: `ante.account.service.AccountService` (코드가 정본이다).

### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | `None` | 스키마 생성 + DB에서 계좌 목록 로드 |
| `mark_runtime_started` | — | `None` | 동기 메서드. 부팅 mutation이 끝난 뒤 런타임 시작을 표시해 cold-path 전용 변경을 막기 시작한다. 멱등이다. 아래 「service-layer 가드 (#1144)」 |
| `create` | `account: Account` | `Account` | 계좌 생성. **cold-path 전용**. account_id 형식/정책 검증은 [`validate_new_account_id`](14-account-id-contract.md) helper에 위임 (``"test"``, ``"default"``, ``None``, ``""``, 패턴 위반 거부). 우회 플래그를 노출하지 않으므로 외부 호출자는 RESTRICTED ( ``"test"`` ) 예약어를 신규 생성할 수 없다 (#1216 P2). account_id 중복 시 `AccountAlreadyExistsError`. broker_type 유효성 검증. 가상 전용 브로커 타입(`mock`, `test`)을 `trading_mode=live`로 만들면 `InvalidBrokerTypeError`(`ACCOUNT_INVALID_BROKER_TYPE`, 아래 「가상 전용 브로커 타입」). seed 자동 생성은 :meth:`create_default_test_account` 가 private helper :meth:`_create_seed_account` 를 통해서만 수행한다 |
| `get` | `account_id: str` | `Account` | 계좌 조회. 없으면 `AccountNotFoundError`. DELETED 상태도 조회 가능 |
| `get_sync` | `account_id: str` | `Account \| None` | 인메모리 캐시에서 동기적으로 계좌 조회. ContextFactory 등 동기 컨텍스트용. 없으면 `None` 반환 |
| `list` | `status: AccountStatus \| None` | `list[Account]` | 계좌 목록 조회. status 필터 가능. DELETED 제외가 기본 |
| `update` | `account_id: str, **fields` | `Account` | 부분 수정. 런타임에는 비구조 필드만 허용. structural field 포함 시 `AccountStructuralChangeRequiresStoppedServerError`. DELETED 계좌는 수정 불가 (`AccountDeletedException`). 불변 필드(`exchange`, `currency`, `trading_mode`, `broker_type`) 포함 시 `AccountImmutableFieldError` |
| `repair_timezone` | `account_id: str, new_timezone: str` | `Account` | 잘못된 timezone 값을 가진 계좌를 복구한다. **cold-path 전용**. 런타임이면 `AccountStructuralChangeRequiresStoppedServerError`, 그 밖에는 `update(account_id, timezone=new_timezone)`에 위임한다 |
| `suspend` | `account_id: str, reason: str, suspended_by: str` | `None` | status → SUSPENDED. 이미 SUSPENDED이면 `AccountAlreadySuspendedError` (409). 단, 이 실행에서 상태 쓰기가 실패해 미기록 표시가 남은 계좌는 상태 전이 없이 같은 상태 UPDATE를 다시 시도한다. `AccountSuspendedEvent` 발행(BotManager가 봇 중지와 주문 정리를 한다 — [05-eventbus-integration.md](05-eventbus-integration.md)). 상태 UPDATE가 `Exception`으로 실패하면 메모리의 정지를 되돌리지 않고 미기록 표시를 남긴 뒤, `AccountSuspendedEvent`와 실패 알림(critical) 한 건을 내고 `AccountSuspendNotPersistedError`(`EXECUTION_ERROR`)를 올린다. 메시지는 정지가 적용됐지만 DB에 기록되지 않아 재시작하면 활성으로 돌아온다는 뜻이고, 원인 예외는 `__cause__`로만 잇는다. 다시 시도한 쓰기가 성공하면 표시를 지우고 첫 쓰기가 성공한 경우와 같은 이벤트와 알림을 낸다 |
| `has_unpersisted_suspensions` | — | `bool` | 동기 메서드. 이 실행에서 상태 쓰기가 실패해 DB에 기록되지 않은 정지가 남아 있는지 돌려준다(텔레그램 `/status`가 쓴다). 아래 `suspend`의 미기록 표시 문단 |
| `activate` | `account_id: str, activated_by: str` | `None` | status → ACTIVE. DELETED 계좌는 활성화 불가. `AccountActivatedEvent` 발행 |
| `delete` | `account_id: str, deleted_by: str` | `None` | 소프트 딜리트 (status=DELETED). **cold-path 전용**. active Ante runtime이 살아 있으면 거부. 진입 직후 `bots` 테이블을 검사해 동일 `account_id`의 활성(non-deleted) 봇이 남아 있으면 `AccountHasActiveBotsError`로 차단(orphan bot 무결성). `bots` 조회가 실패하면 테이블이 없는 경우(`no such table` — 봇이 없다)만 0건으로 보고, 그 밖의 오류는 그대로 올려 삭제하지 않는다. 1.0 정책상 `AccountDeletedEvent`는 발행하지 않는다 |
| `get_broker` | `account_id: str` | `BrokerAdapter` | 계좌의 BrokerAdapter 인스턴스 반환. lazy init. 최초 호출 시 생성하고 `connect()`를 수행하여 **연결에 성공한 경우에만 캐싱**한다. 연결 실패 시 캐시에 남기지 않고 예외를 전파하므로(미연결 어댑터 잔존 차단), 일시적 인증/네트워크 실패는 다음 호출에서 자연 회복한다. cache-hit은 connect 없이 즉시 반환. cache-miss는 per-account lock으로 직렬화하여 동시 호출 시에도 단일 인스턴스·단일 connect를 보장한다 |
| `get_cached_broker` | `account_id: str` | `BrokerAdapter \| None` | 이미 캐시된 BrokerAdapter만 반환(build/connect 없음). 미캐시면 `None`. 종료 루프처럼 "이미 연결된 어댑터만 끊는" 경로 전용 — 미캐시 계좌를 끊기 위해 새로 연결하는 회귀를 차단한다. **async 메서드**: per-account lock으로 in-flight 초기 연결을 drain한 뒤 조회하므로, 종료 중 in-flight connect가 끝난 직후 캐시되어 disconnect를 놓치는 세션 잔존을 막는다 |
| `ensure_reconcile_applicable` | `account_id: str` | `None` | 수동 대사를 할 수 있는 계좌인지 판정한다. 계좌를 조회해(없으면 `AccountNotFoundError`) D-ACC-09 매트릭스에서 reconcile 이 면제인 계좌(가상)면 `AccountReconcileNotApplicableError`를 낸다. 브로커를 만들거나 연결하지 않는다([15-reconciliation.md](../broker-adapter/15-reconciliation.md)) |
| `create_default_test_account` | — | `Account` | 테스트 계좌 자동 생성 (`ante init` 시 호출). 이미 존재하면 스킵 |
| `suspend_all` | `reason: str, suspended_by: str` | `list[dict]` | 모든 ACTIVE 계좌를 SUSPENDED로 전환 (시스템 전체 Kill Switch). 미기록 표시가 남은 정지 계좌도 `suspend`로 다시 시도한다. DELETED를 뺀 ACTIVE·SUSPENDED 계좌별 결과(`account_id`·`previous_status`·`status`·`changed`)를 반환한다. 이미 목표 상태인 계좌는 `changed: false`이고, 다시 시도한 계좌도 `previous_status: suspended`·`changed: false`다. 한 계좌의 `suspend`가 예외로 실패해도 나머지 후보 계좌를 모두 시도한다. 실패가 하나라도 있으면 결과 목록을 돌려주지 않고 `AccountSuspendAllFailedError`(`ACCOUNT_SUSPEND_ALL_FAILED`)를 올린다. 이 오류는 실패한 계좌 id 목록과 이번 호출에서 정지된 계좌 수를 싣고, 원인 예외는 로그에만 남긴다. 작업 취소는 가두지 않는다. 상태 쓰기가 실패한 계좌는 `suspend`의 규칙대로 정지와 미기록 표시가 남아, 다시 보낸 `suspend_all`이 그 계좌를 다시 시도한다 |
| `activate_all` | `activated_by: str` | `list[dict]` | 모든 SUSPENDED 계좌를 ACTIVE로 복구. DELETED를 뺀 ACTIVE·SUSPENDED 계좌별 결과(`account_id`·`previous_status`·`status`·`changed`)를 반환한다. 이미 목표 상태인 계좌는 `changed: false`. 한 계좌의 `activate`가 예외로 실패하면 거기서 멈추고 뒤의 계좌는 시도하지 않는다. 이때 `AccountActivateAllFailedError`(`ACCOUNT_ACTIVATE_ALL_FAILED`)를 올리며, 실패한 계좌 id와 그 전에 활성화된 계좌 수를 싣고 원인 예외를 `__cause__`로 잇는다. 실패한 계좌는 `activate`의 규칙대로 호출 전 상태로 돌아간다 |

`activate`·`delete`는 상태 UPDATE가 실패하면(작업 취소 포함) 캐시에 든 그 계좌 객체의 `status`·`updated_at`을 호출 전 값으로 제자리에서 되돌리고 같은 예외를 다시 올린다. 이벤트는 UPDATE가 성공한 뒤에만 발행한다: `activate`의 `AccountActivatedEvent`·알림, 그리고 활성 계좌를 지울 때 `delete`가 내는 `AccountSuspendedEvent`(캐시에서 계좌를 뺀 뒤 발행). UPDATE가 커밋된 뒤에 취소가 닿으면 DB는 바뀐 채 캐시만 되돌아갈 수 있다 — `activate`라면 캐시가 정지로 남아 주문이 막히고, 재시작하면 DB 값을 따른다.

`suspend`는 상태 UPDATE가 실패해도 캐시를 되돌리지 않는다(주문이 막힌 채로 남는다). 미기록 표시는 `AccountService`의 메모리에만 있어, 재시작하면 그 계좌는 DB 값(활성)을 따른다. 작업 취소로 끝나면 표시만 남기고 이벤트를 내지 않는다 — 봇의 주문은 캐시의 정지 상태로 막히고, 봇 중지는 다음에 다시 보낸 정지가 이룬다. `activate`·`delete`는 상태 쓰기가 성공한 뒤에만 그 계좌의 표시를 지운다. CLI의 `account list`·`account info`·`system status`는 CLI 프로세스에서 DB를 읽으므로, 다시 보낸 정지의 쓰기가 성공하기 전까지 `account list`·`account info`는 그 계좌를 활성으로 보이고 `system status`는 그 계좌를 정지로 세지 않는다(텔레그램 `/status`는 데몬의 메모리를 읽어 정지로 센다). `AccountSuspendNotPersistedError`·`ACCOUNT_SUSPEND_ALL_FAILED`나 실패 알림을 받으면 정지를 다시 보낸다.

소스: `src/ante/account/service.py`

### 브로커 인스턴스 생성

`get_broker()`는 `broker_type`으로 `BROKER_REGISTRY`에서 어댑터 클래스를 조회하고, Account의 `credentials`, `broker_config`, `buy_commission_rate`, `sell_commission_rate`를 어댑터 config로 전달하여 인스턴스를 생성한다. 최초 호출 시 생성하고 이후 캐싱한다.

**캐시-연결 의미론**: `get_broker()`는 최초 생성 경로에서 어댑터의 `connect()`를 수행하고 **연결 성공 후에만 캐시에 기록**한다. connect가 실패하면 캐시에 어댑터를 남기지 않고 예외를 그대로 전파한다 — 일시적 인증/네트워크 실패로 `is_connected=False`인 미연결 어댑터가 캐시에 잔존해 장기 실행 runtime의 후속 소비자가 이를 재사용하는 일을 막는다. 이 원칙은 재연결 경로(`_reconnect_broker`)의 connect-성공-후-캐시 의미론과 동일하다. cache-hit 경로(런타임 hot-path)는 connect 호출 없이 캐시된 인스턴스를 즉시 반환한다.

**connect 멱등**: 모든 BrokerAdapter의 `connect()`는 멱등이다 — 이미 연결된 상태(`is_connected`이고 활성 세션 보유)면 새 세션을 만들지 않고 no-op으로 반환한다. 따라서 `get_broker()`가 connect한 어댑터에 호출자가 `connect()`를 재호출해도 세션 교체로 인한 누수가 없다. cache-miss 경로는 per-account 락으로 직렬화하고 락 안에서 캐시를 재검사(double-checked)하므로, 동일 계좌의 동시 `get_broker()` 호출도 단일 인스턴스·단일 connect로 수렴한다.

**cached-only 조회**: `get_cached_broker()`는 이미 캐시된 어댑터만 반환하며(build/connect 없음), 미캐시면 `None`을 반환한다. 종료 루프처럼 "이미 연결된 어댑터만 끊으면 되는" 경로는 이 접근자를 사용해, 미캐시 계좌를 끊기 위해 새로 인증/연결하는 회귀를 피한다(미캐시 = 끊을 연결도 없음). 조회는 `get_broker()`/`_reconnect_broker()`와 동일한 per-account lock 안에서 수행하여 in-flight 초기 연결을 drain한 뒤 캐시를 재확인한다(async 메서드). 동기 즉시 조회였다면, 종료 중 cache-miss `get_broker()`가 lock을 쥔 채 `connect()`를 대기하는 in-flight 구간을 `None`으로 보고 skip하고, 그 connect가 직후 성공해 disconnect 루프 종료 뒤 캐시에 기록된 세션이 DB close 이후까지 잔존했다 — lock 대기로 connect 완료를 기다린 뒤 조회해 이 윈도를 닫는다(연결 성공 시 캐시된 어댑터 반환→disconnect, 실패 시 `None`).

> **`trading_mode`와 `broker_config`의 분리**: `trading_mode`는 시스템이 브로커 API를 실제로 호출할지 결정한다 (VIRTUAL=가상거래, LIVE=실거래). `broker_config`는 브로커 내부 동작 설정을 담는다. 예를 들어 KIS 브로커의 `is_paper`는 모의투자/실전투자 엔드포인트를 결정하는 브로커 내부 관심사이므로 `broker_config`에 속한다. `get_broker()`는 `trading_mode`로부터 `is_paper`를 파생하지 않는다.

#### 가상 전용 브로커 타입

`mock`과 `test`는 가상 전용 브로커 타입이다. `(mock, live)`와 `(test, live)` 조합은 두 곳에서 `InvalidBrokerTypeError`(`ACCOUNT_INVALID_BROKER_TYPE`)로 거부한다. 메시지는 타입이 틀린 것이 아니라 `trading_mode`와의 조합이 허용되지 않는다는 것을 밝힌다.

- **계좌 생성**: `_persist_account`(`create`와 seed가 공유하는 단일 지점)에서 거부한다. `trading_mode`와 `broker_type`은 불변 필드라 수정 경로는 따로 막지 않는다.
- **어댑터 조립**: `_build_broker_adapter`가 같은 조합이면 같은 오류를 낸다. DB를 직접 고친 행에 대한 방어다.

판정은 `Account.trading_mode`로 한다. 어댑터 config의 `trading_mode`는 `broker_config`가 덮어쓸 수 있으므로 쓰지 않는다. 가상 전용 타입의 집합은 한 곳에 두고 두 지점이 함께 쓴다. 상세는 [broker-adapter/12-test-broker-adapter.md](../broker-adapter/12-test-broker-adapter.md#가상-전용)를 따른다.

제품에는 이 거부를 끄는 스위치가 없다. 데몬 구동 시나리오의 하네스는 자기 하위 프로세스에 싣는 테스트 주입으로 `(mock, live)`만 연다([broker-adapter/12-test-broker-adapter.md](../broker-adapter/12-test-broker-adapter.md#가상-전용)).

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

IPC 서버(`_dispatch`)는 `ipc_error_payload` → `error_spec_for_exception`으로 코드를 정한다. 에러 레지스트리(`EXCEPTION_TO_SPEC`)를 MRO로 찾는 것이 먼저이고, 그다음이 SCREAMING_SNAKE 모양의 `code` 속성이며, 둘 다 없으면 `EXECUTION_ERROR`다(정본: `src/ante/contracts/helpers.py`의 `error_spec_for_exception`). `AccountStructuralChangeRequiresStoppedServerError`(클래스 레벨 속성 `code: str = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"`도 노출한다)와 `AccountAlreadySuspendedError`는 레지스트리에 각자의 코드로 올라 있다.

#### CLI / 다중 active runtime 정책

CLI cold-path 명령(`ante account create/delete/set-credentials`)은 `_assert_no_active_runtime` guard(PID alive + IPC socket exists)로 서버 실행 여부를 먼저 확인하고, runtime이 살아 있으면 서비스 메서드를 호출하지 않는다(#1139). service-layer 가드는 그 1차 가드를 우회한 비정상 경로(예: 직접 코드 호출, 테스트 monkeypatch, 또는 향후 도입될 IPC `account.create/update`/등 핸들러)의 defense-in-depth 역할이다. 1.0 정책상 동일 OS user/home server 기준으로 active runtime은 항상 단일이며, `config_dir`은 데이터/설정 프로필 경계지 동시 namespace가 아니다.

### 에러 클래스

소스: `src/ante/account/errors.py`. `AccountError`는 `src/ante/core/account_id.py`에
정의되고 `ante.account.errors`가 재수출한다.

에러 코드: [`error-codes.md`](../../architecture/generated/error-codes.md)

- `AccountDeletedException`: DELETED 계좌 수정/활성화 시도 시
- `AccountImmutableFieldError`: 불변 필드 수정 시도 시 (exchange, currency, trading_mode, broker_type)
- `AccountAlreadySuspendedError`: 이미 정지된 계좌 재정지 시도 시 (409)
- `AccountStructuralChangeRequiresStoppedServerError`: 런타임 구조 변경 차단
- `AccountHasActiveBotsError`: delete() 시 활성(non-deleted) 봇 잔존 시 (orphan bot 무결성)
- `AccountReconcileNotApplicableError`: reconcile 이 면제인 계좌(가상)에 대한 수동 대사 시도 시 (`ensure_reconcile_applicable`)
- `AccountSuspendNotPersistedError`: 정지는 메모리에 적용됐지만 상태 DB 쓰기가 실패 시 (`suspend`). 코드는 `EXECUTION_ERROR`
- `AccountSuspendAllFailedError`: 일괄 정지에서 한 계좌 이상이 실패 시 (`suspend_all`)
- `AccountActivateAllFailedError`: 일괄 활성화가 한 계좌의 실패에서 멈출 시 (`activate_all`)
