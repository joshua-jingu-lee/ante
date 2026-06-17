# Account 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 설계 결정

### D-ACC-01: 왜 Account가 최상위 엔티티인가

**문제**: 미국 증시 지원 시 거래소·통화·브로커·수수료 등의 시장별 차이를 어디서 관리할 것인가.

**선택지**:
1. ~~Bot에 exchange 필드 추가~~ — 봇마다 브로커·수수료·통화를 중복 설정해야 함
2. ~~BrokerAdapter에서 exchange로 분기~~ — 어댑터가 비대해지고, 증권사별 규칙 차이를 흡수하기 어려움
3. **Account를 최상위 엔티티로 도입** — 시장 연동 정보를 한곳에 캡슐화, 봇·Treasury·데이터가 계좌에 종속

**결정**: 3번. 각 계좌가 자신의 연동 정보를 완결적으로 소유하면, 특정 증권사의 규칙(예: KIS의 국내/해외 동일 계좌번호)이 시스템 전체로 누출되지 않는다.

### D-ACC-02: KIS 국내/해외가 같은 계좌번호인데 왜 분리하는가

KIS에서는 국내·해외 주식이 동일한 계좌번호와 APP KEY를 공유한다. 그러나 Ante에서는 별도 Account로 분리한다.

**이유**:
- API 경로, TR ID, 필수 파라미터가 완전히 다름 (domestic-stock vs overseas-stock)
- 예수금이 통화별로 분리 관리됨 (원화 vs USD)
- 다른 증권사(예: Interactive Brokers)는 완전히 별개의 인증·계좌 체계를 가질 수 있음
- credentials 중복 저장은 허용 — 확장성을 위한 의도적 선택

### D-ACC-03: Strategy는 왜 Account 밖인가

**문제**: 전략이 대상 시장 정보(exchange)를 알아야 하는데, Account에 종속시킬지 독립으로 둘지.

**선택지**:
1. ~~Account에 종속~~ — 같은 로직의 전략을 KRX/NYSE 양쪽에서 쓰려면 두 번 등록해야 함. 시장 중립 전략을 표현하기 어려움. 백테스트 시 계좌를 미리 정해야 하는 제약.
2. **글로벌 Registry + `StrategyMeta.exchange`** — 전략 하나를 여러 계좌에서 재사용 가능. 백테스트 시 계좌 없이 자유롭게 실행 가능.

**결정**: 2번. 전략은 글로벌 Registry에 등록하고, `StrategyMeta.exchange`로 대상 시장을 명시한다. 봇 생성 시 계좌의 exchange와 전략의 exchange 호환성을 검증하여 불일치를 방지한다.

```python
# 봇 생성 시 호환성 검증
if strategy.meta.exchange != "*" and strategy.meta.exchange != account.exchange:
    raise IncompatibleExchangeError(
        f"전략 '{strategy.meta.name}'은 {strategy.meta.exchange}용이지만, "
        f"계좌 '{account.account_id}'는 {account.exchange}입니다."
    )
```

`exchange="*"`인 전략은 시장 무관(OHLCV만 있으면 동작)하므로 어떤 계좌에든 배정 가능하다.

### D-ACC-04: Data Store와 Backtest는 왜 Account 밖인가

**문제**: 시세 데이터를 계좌에 종속시킬지 독립 모듈로 둘지.

**결정**: 독립 모듈. 시장 데이터는 계좌 고유 데이터가 아니라 공공 데이터다.

**이유**:
- KRX 삼성전자 일봉은 어떤 KRX 계좌에서 조회하든 동일
- 같은 exchange의 계좌를 추가해도 데이터를 다시 수집할 필요 없음
- 백테스트는 계좌 없이도 실행 가능해야 함 ("이 전략을 NYSE 데이터로 돌려보자"가 계좌 생성 전에도 가능)
- 데이터의 자연 키는 `(exchange, symbol, timeframe)`이지 `account_id`가 아님

Data Store는 `exchange/symbol/timeframe`으로 파티셔닝하며, 봇이 데이터를 조회할 때 자기 계좌의 exchange를 키로 사용한다.

### D-ACC-05: ante init에서 계좌를 어떻게 다루는가

**최초 설계**: `ante init` → Master 계정 + KIS 연동 + 알림 + 데이터 API (대화형)

**과도기**: `ante init` → Master + 테스트 계좌 자동 + 실계좌 대화형 등록 옵션 + 알림 + 데이터 API

**현행 (재설계 2026-04, #1125)**: `ante init` → **비대화형** 최소 bootstrap. master 멤버 1개 + default test account(`broker_type="test"`, `trading_mode=VIRTUAL`) 1개만 생성한다.

```bash
ante init [--member-id owner] [--name Owner] [--dir <경로>]
```

`ante init`은 더 이상 KIS 실계좌 / Telegram / DataFeed / 기존 broker→account 마이그레이션을 다루지 않는다. 사용자/Agent가 후속 명령으로 명시적으로 추가한다:

- 실거래 계좌(KIS 등): 서버 정지 상태에서 `ante account create`에 `--broker-type`, `--account-id`,
  `--name`, `--trading-mode`와 credential 옵션(`--credential`/`--credential-env`/`--credential-file`)을
  명시한다. 입력 계약은 [cli/02-design-decisions.md — 비대화형 입력 계약](../cli/02-design-decisions.md#비대화형-입력-계약-cli-non-interactive-input-contract),
  명령 시그니처는 [cli/03-commands.md — `ante account` 계좌 관리](../cli/03-commands.md#ante-account--계좌-관리)를 따른다.
- Telegram: `<config_dir>/secrets.env` 직접 편집 (`TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`)
- DataFeed API 키: `ante feed config set ANTE_DATAGOKR_API_KEY <key>` / `ANTE_DART_API_KEY`

`account create`에서 broker 책임 경계는 두 SSOT로 분리된다.

- `BROKER_REGISTRY` (`src/ante/broker/registry.py`): `broker_type` 문자열 → `BrokerAdapter`
  매핑. `--broker-type` enum 검증에 사용한다.
- `BrokerPreset` (`src/ante/account/models.py`의 dataclass): broker별 default 값 + `required_credentials`
  목록을 보유. `--credential*` key 검증의 SSOT다.

`--broker-config key=value`는 1.0 범위에서 free-form pass-through로 받아
`Account.broker_config: dict[str, Any]`에 저장한다. `BrokerPreset`에 `optional_broker_config`
필드를 신설하지 않으며, broker별 known optional key 검증은 broker adapter 초기화
시점으로 위임한다.

**1.0 silent ignore trade-off**: 1.0에서 broker adapter가 unknown `broker_config` key를
거부하지 않고 silent ignore할 수 있다(예: KIS adapter는 `config.get("is_paper", ...)`
형태로 known key만 읽음). 사용자가 오타나 잘못된 key를 `--broker-config`로 넘겨도
검증되지 않는다. 이는 1.0 의도된 trade-off이며, 후속 이슈에서 `BrokerPreset.optional_broker_config`
모델과 `UNKNOWN_BROKER_CONFIG_KEY` 검증을 도입한다.

테스트 계좌(`account_id: "test"`)는 `ante init`이 항상 자동 생성하므로, 사용자는 실계좌 등록 없이도 가상 자금으로 시스템 전체 흐름을 체험할 수 있다.

> 상세 init 계약 (생성 산출물·멱등성·플래그)은 [cli/03-commands.md](../cli/03-commands.md#ante-init--시스템-초기-설정) 참조.

### D-ACC-08: Account ID 계약 (runtime/creation 정책 분리)

**문제**: account-scoped 데이터/이벤트/명령에서 빈 문자열, ``None``,
``"default"`` 같은 fallback 값이 흘러들 때 cross-module 회귀가 발생한다.
또한 ``ante init``이 자동 생성하는 ``"test"`` 계좌는 runtime valid이지만
사용자가 같은 ID로 새 계좌를 만들 수 있어서는 안 된다.

**결정**: runtime invalid와 creation invalid를 분리한 helper 모듈
``ante.account.scoping``을 도입하고 본 helper를 모든 account-scoped
진입점의 SSOT로 삼는다.

- **runtime invalid**: ``None``/``""``/``"default"``/패턴 위반 — 모든 시점에서 거부
- **creation invalid**: 위에 더해 ``"test"`` 추가 거부 (bootstrap seed 전용)
- **bootstrap 우회**: ``AccountService.create_default_test_account``가
  private :meth:`AccountService._create_seed_account` helper를 통해서만
  RESTRICTED 가드를 우회한다. public ``create()`` API에는 우회 플래그가 없고,
  seed helper는 ``(broker_type, default_account_id)`` pair가 ``BROKER_PRESETS``
  와 정확히 일치할 때만 통과시킨다 (#1216 P2). 이 경로 외에는 우회 불가

상세 계약과 helper API는 [14-account-id-contract.md](14-account-id-contract.md)
참조. 후속 적용은 #1240 (SPLIT-1: Event marker + Trade/Treasury/Rule),
#1241 (SPLIT-2: Bot/Main + Approval payload),
#1242 (SPLIT-3: APIGateway/Stream + multi-account lifecycle),
#1218 (Read query / edge resolver), #1219 (DB schema/index)
에서 반영한다.

### D-ACC-09: Runtime readiness 축은 AccountStatus와 직교한다

> 계약 확정: #2396. 실제 동작은 구현 #2397(축 i readiness 모델)·#2398(축 ii active-order gate) 머지 후. 본 절은 스펙 계약만 정의한다.

**배경 (#2395)**: KIS 토큰 압박(`EGW00133`) + timeout으로 startup 중 일부 계좌의 broker / treasury / fill / reconcile 스케줄러가 건너뛰어진 채 기동되었으나, 이후 전략 경로가 별도 broker로 실주문·체결했다. fill scheduler가 부재해 **체결 DB 누락·미추적 포지션**이 발생했다. 근본 원인은 **active 주문 경로와 fill/treasury/reconcile readiness의 디커플링**이다. 주문 가능 여부가 service-health(스케줄러 등록 성공)와 분리되어 있었기 때문이다.

**결정**: `AccountStatus`(user kill-switch 축)와 **직교하는** 별도의 service-health 자동축으로 **per-account runtime readiness**를 도입한다. SSOT는 신규 `RuntimeReadinessRegistry`다.

#### (1) SSOT = `RuntimeReadinessRegistry` (registry-owned)

readiness 권위는 신규 `RuntimeReadinessRegistry` **단독**이다. `Services` 필드 `s.runtime_readiness`로 1개 인스턴스를 만들어 main(등록자)과 gateway / RuleEngine / Treasury(reader)에 **동일 인스턴스**를 주입한다.

- readiness를 `account_service`에 두면 broker 캐시 유무와 다시 결합되어 #2372(포지션 소유·broker 캐시 분리) 의도가 무너진다. authority는 broker 캐시가 아니라 **스케줄러 등록 성공/실패**다.
- `Services`의 `fill_schedulers` / `reconcile_schedulers` / `fill_catch_up_failed_accounts` dict는 **스케줄러 인스턴스 보관용**일 뿐이다. reader가 이 dict들을 직접 보면 state drift가 생기므로, registry가 이들을 **derivation source로 흡수**해 SSOT를 하나로 모은다. reader(gateway / RuleEngine / Treasury)는 registry만 조회한다.

#### (2) 4 플래그 (per-account, 디폴트 = not_ready)

per-account 4개 플래그를 둔다. 디폴트 초기값은 `not_ready`이며, 명시 `mark_ready` 이전에는 차단한다(**fail-closed**).

| 플래그 | ready 조건 | 비고 |
|---|---|---|
| `broker_ready` | `_init_gateway` connect 성공 시점 mark | get_cached_broker live-poll 아님([must_fix F]) |
| `treasury_sync_ready` | `_init_treasury_sync`가 해당 계좌 `treasury.start_sync` 성공 | VIRTUAL은 broker 없이 Trade-DB sync 시작 가능 |
| `fill_reconcile_ready` | `id in s.fill_schedulers` (catch_up_once + start 성공) | 등록 시점 registry mark |
| `reconcile_ready` | `id in s.reconcile_schedulers` (start 성공) | 등록 시점 registry mark |

`active_trading_ready(id)`는 **필요 플래그 전부의 AND**를 계산하는 단일 derive 함수로 정의하며, reader는 이 함수만 호출한다. 4 readiness(broker / treasury_sync / fill_reconcile / reconcile)는 전부 active-trading 전제이므로, 면제 매트릭스로 면제된 플래그를 `true`로 취급한 뒤 AND한다.

#### (3) 단일 mark 경로 ([must_fix F])

4 플래그 전부 등록자(`main._init_*`)가 connect / start **성공·실패 시점**에 `mark_ready(id, flag)` / `mark_not_ready(id, flag, reason)`로 명시 기록하는 단일 경로로 정의한다. main의 `_init_*`은 스케줄러 등록과 **동시에**(등록 직후 1:1, 별도 mirror·지연 동기화 아님) registry를 mark한다.

- `broker_ready`도 `get_cached_broker` live-poll이 아니라 `_init_gateway` connect 성공/실패 mark로 일원화한다. `get_cached_broker`는 per-account lock 조회라 active-order hot-path(매 주문 평가)에 부적합하다([must_fix F]).

#### (4) 면제 매트릭스 ([must_fix A], normative)

면제 키는 코드 실제 분기축에 정렬한다. `broker_type ∈ {test, kis-domestic}`이며 `virtual`은 `broker_type`이 아니라 `TradingMode` 값이다. `treasury_sync_ready`의 분기축은 `trading_mode`(VIRTUAL → broker=None Trade-DB sync / LIVE → get_broker 의존)이고, broker / fill / reconcile_ready의 분기축은 connect 성공 여부다.

| broker_type | trading_mode | broker_ready | treasury_sync_ready | fill_reconcile_ready | reconcile_ready |
|---|---|---|---|---|---|
| test | virtual | 면제(항상 ready) | 요구 | 면제 | 면제 |
| kis-domestic | virtual | 면제 | 요구 | 면제 | 면제 |
| kis-domestic | live | 요구 | 요구 | 요구 | 요구 |

- virtual은 broker API를 미호출하므로(주문은 `VirtualExecutor`가 가상 체결, [api-gateway.md](../api-gateway/api-gateway.md) "Virtual 주문 라우팅" 참조) broker / fill / reconcile이 무의미하다. test도 동일하다. **virtual / test fill·reconcile은 스케줄러 등록을 스킵하지 않고 등록을 유지하되 readiness eval에서만 면제한다([must_fix H], R2 확정)** — dict-key와 registry 이중 표상 drift를 막기 위함이다(등록 시 registry mark가 단일 경로).
- `BROKER_REGISTRY` 미래 타입의 default 정책은 **fail-closed**다(매트릭스에 미지정인 `(broker_type, trading_mode)` pair는 모든 플래그를 요구로 취급).

#### (5) 자동전이 ([must_fix B], normative)

- **startup 실패** (`get_broker` / `connect` / `start` 예외 → continue): 해당 플래그 `mark_not_ready(reason=EGW00133 / timeout / ...)`.
- **회복 전이원**: `_reconnect_broker`는 `update()` 가드(`mark_runtime_started` 후 차단)로 런타임 unreachable이라 회복 경로로 쓸 수 없다. 회복 전이원은 (a) `get_broker()` lazy cache-miss connect 성공 hook, 또는 (b) **신규 self-healing background retry loop**(net-new)다.
- **회복 시 self-healing 재등록**: broker 회복 후 fill_recovery + reconcile + treasury_sync를 **idempotent re-register**한 뒤 전부 성공 시 플래그를 ready로 전이한다. `catch_up_once`는 멱등(#1946 barrier `s.fill_catch_up_failed_accounts` 보존)이라 재등록이 안전하다.

#### (6) self-healing liveness invariant ([must_fix C], R3, normative)

self-healing background retry loop는 broker가 `not_ready`인 동안 **무기한 재시도**를 지속한다(bounded backoff / cooldown, `EGW00133` ~60s에 정렬). `max attempts`는 **계좌 lifetime이 아니라 per-burst / 연결시도 단위에만** 적용한다. 일시 토큰 압박이 영구 `not_ready`로 고착되어서는 안 된다.

> **liveness invariant (normative)**: broker 회복이 가능한 한, `not_ready` 계좌는 **유한시간 내 ready로 전이**한다. 이 invariant가 깨지면 transient 실패가 permanent로 역회귀하여 gate(축 ii) 도입 후 정상 주문이 영구 거부되어 #2395를 다른 형태로 재생산한다. gate soundness(축 ii)는 self-healing liveness(축 i)에 종속하므로, 구현 #2397의 liveness invariant가 구현 #2398 머지 전 검증되어야 한다.

self-healing backoff 주기 / 최대 시도 / startup 타임아웃은 config로 노출한다.

#### (7) 런타임 저하 백스톱 ([must_fix E])

`broker_ready`는 startup snapshot mark다. 런타임 중 broker가 저하(토큰 만료·세션 단절)되어도 `is_connected`가 토글되지 않을 수 있다. 이 경우는 (a) 별도 `mark_not_ready` 경로, 또는 (b) 계층 3 fail-closed 백스톱([11-order-flow.md](../broker-adapter/11-order-flow.md) 참조)이 안전망 역할을 한다.

#### (8) AccountStatus.SUSPENDED와 직교 (normative)

두 축은 **직교**한다.

- `AccountStatus.SUSPENDED`: user-initiated kill-switch([05-eventbus-integration.md](05-eventbus-integration.md), BotManager가 소속 봇 중지).
- runtime readiness: service-health 자동축. readiness `not_ready`는 봇을 stop하지 않고 active-order만 gate한다.

active-trading 차단 효과는 **일관**한다(둘 중 하나라도 막으면 거부). 단 readiness는 `AccountStatus`를 변경하지 **않는다**(SUSPENDED 자동 전이 금지 — user 결정 침해 방지). `RuleContext.account_status` dead field는 readiness gate와 별개로 유지하며, 정리(제거 vs 유지)는 별 PR로 권고한다(open question; [rule-engine/05-rule-context.md](../rule-engine/05-rule-context.md) caveat 참조).

> **구현 분할 anchor**: 구현 #2397(축 i readiness 모델·SSOT·self-healing, 선행 없음·독립)이 registry를 채운다(이 PR은 gate를 켜지 않음 — 관측-only, 주문 동작 불변). 구현 #2398(축 ii active-order gate)은 **#2397 필수 선행**이다. 구현 #2399(축 iii KIS token single-flight)는 독립이다.

### D-ACC-07: Account lifecycle cold-path contract

**결정**: 계좌 구조 변경은 서버 정지 상태에서만 허용한다. 서버 실행 중에는
계좌별 런타임 상태 전이와 조회만 허용하고, Treasury/RuleEngine/Gateway/Bot에 새 계좌나
새 브로커 설정을 hot wiring하는 것을 1.0 범위에서 지원하지 않는다.

**런타임 중 허용**:

| 작업 | CLI/IPC | 실행 경로 |
|---|---|---|
| 계좌 목록/상세 조회 | `account list`, `account info` | 읽기 |
| 인증 정보 마스킹 조회 | `account credentials` | 읽기 |
| 계좌 거래 정지 | `account suspend` | IPC → `AccountService.suspend()` |
| 계좌 거래 재개 | `account activate` | IPC → `AccountService.activate()` |
| 전체 거래 정지 | `system halt` | IPC → `AccountService.suspend_all()` |
| 전체 거래 정지 해제 | `system clear-halt` | IPC → `AccountService.activate_all()` (계좌 상태 복구만; 봇 자동 재시작 아님) |
| 비구조 필드 수정 | `account update` 계열 향후 명령 | `name`, `timezone`, `trading_hours` 등 브로커 재초기화가 필요 없는 필드만 |
| 계좌별 rule 변경 | `rule update` | DynamicConfig + `ConfigChangedEvent` |

**cold-path 전용**:

| 작업 | CLI | 서버 실행 중 동작 |
|---|---|---|
| 계좌 생성 | `account create` | `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER`로 거부 |
| 계좌 삭제 | `account delete` | 동일 |
| credentials 변경 | `account set-credentials`, credentials 변경 payload | 동일 |
| `broker_config` 변경 | structural update payload | 동일 |
| `buy_commission_rate` / `sell_commission_rate` 변경 | structural update payload | 동일 |
| `broker_type`, `exchange`, `currency`, `trading_mode` 변경 | 생성 후 불변. 변경하려면 서버 정지 상태에서 새 계좌 생성 + 기존 계좌 삭제 |

**차단 규칙**:

1. cold-path 전용 CLI는 먼저 같은 `config_dir`의 PID/socket으로 서버 실행 여부를 확인한다.
2. 서버가 실행 중이면 DB를 열기 전에 실패한다.
3. cold-path structural mutation은 runtime IPC 대상이 아니다.
4. 서버는 시작 시 DB의 계좌 목록을 로드하고, 그 구조를 해당 프로세스의 계좌 topology로 고정한다. 구조 변경 후에는 서버 재시작이 필요하다.
