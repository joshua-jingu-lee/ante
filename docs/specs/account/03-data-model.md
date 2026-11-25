# Account 모듈 세부 설계 - 데이터 모델

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 데이터 모델

### AccountStatus

정의: `ante.account.models.AccountStatus` (코드가 정본이다).

- `ACTIVE` (`"active"`): 정상 운영
- `SUSPENDED` (`"suspended"`): 거래 정지 (Kill Switch, 수동 정지)
- `DELETED` (`"deleted"`): 소프트 딜리트

### TradingMode

정의: `ante.account.models.TradingMode` (코드가 정본이다).

- `VIRTUAL` (`"virtual"`): 가상거래 (시뮬레이션)
- `LIVE` (`"live"`): 실제거래

### Account

소스: `src/ante/account/models.py`

- `account_id`: 영문+숫자+하이픈, 3–30자
- `name`: 표시 이름
- `exchange`: "KRX", "NYSE", "NASDAQ", "TEST"
- `currency`: "KRW", "USD"
- `timezone`: "Asia/Seoul", "America/New_York"
- `trading_hours_start`: "09:00" (현지 시간, HH:MM)
- `trading_hours_end`: "15:30" (현지 시간, HH:MM)
- `trading_mode`: VIRTUAL / LIVE
- `broker_type`: "kis-domestic", "test", "mock" (kis-overseas는 1.1)
- `credentials`: 인증 정보 (암호화 저장)
- `broker_config`: 브로커 동작 설정
- `buy_commission_rate`: 매수 수수료율
- `sell_commission_rate`: 매도 수수료율 (세금 포함)
- `market_order_reserve_buffer_rate`: 시장가 매수 reserve buffer 비율 (Account-level Treasury reserve policy, #1333). quote 만으로 reserve 하면 가격 변동을 흡수하지 못하므로 ``reserve_basis = quantity * quote * (1 + market_order_reserve_buffer_rate)`` 식으로 보수적으로 잠근다.

### 필드 설명

| 필드 | 필수 | 기본값 | 수정 | 설명 |
|------|------|--------|:----:|------|
| **식별** | | | | |
| `account_id` | O | — | 불가 | 고유 식별자 (영문+숫자+하이픈, 3–30자). 형식·정책 SSOT는 [14-account-id-contract.md](14-account-id-contract.md) |
| `name` | O | — | 가능 | 사용자에게 표시되는 이름 |
| **시장** | | | | |
| `exchange` | O | — | 불가 | 대상 거래소 코드 (KRX, NYSE, NASDAQ, TEST) |
| `currency` | O | — | 불가 | 거래 통화 (ISO 4217) |
| `timezone` | - | `"Asia/Seoul"` | 가능 | 거래소 현지 시간대 (IANA) |
| `trading_hours_start` | - | `"09:00"` | 가능 | 거래 시작 시각 (현지 시간, HH:MM) |
| `trading_hours_end` | - | `"15:30"` | 가능 | 거래 종료 시각 (현지 시간, HH:MM) |
| **거래 모드** | | | | |
| `trading_mode` | - | `VIRTUAL` | 불가 | 거래 모드 (VIRTUAL / LIVE) |
| **브로커** | | | | |
| `broker_type` | O | — | 불가 | 브로커 어댑터 유형 |
| `credentials` | - | `{}` | cold-path | 브로커 인증 정보 (암호화 저장) |
| `broker_config` | - | `{}` | cold-path | 브로커 동작 설정 (예: KIS `is_paper`) |
| **비용** | | | | |
| `buy_commission_rate` | - | `0` | cold-path | 매수 수수료율 |
| `sell_commission_rate` | - | `0` | cold-path | 매도 수수료율 (세금 포함) |
| `market_order_reserve_buffer_rate` | - | BrokerPreset 기본값 | cold-path | 시장가 매수 reserve buffer 비율 (#1333). Treasury 가 시장가 매수 reserve 산정 시 보수적으로 잠가둘 추가 비율. `broker_config` 가 아니라 Account 소속 reserve policy 다. |
| **상태** | | | | |
| `status` | - | `ACTIVE` | 상태 전이 | 계좌 상태 (ACTIVE / SUSPENDED / DELETED) |

`cold-path` 필드는 수정 가능하지만 서버 정지 상태에서만 변경한다. 서버 실행 중에는
`AccountStructuralChangeRequiresStoppedServerError`로 차단한다.

### 불변 필드 정책 (D-ACC-06)

`exchange`, `currency`, `trading_mode`, `broker_type`는 생성 후 수정할 수 없다. 이 4개 필드는 계좌의 정체성을 결정하는 근본 속성이며, 런타임 중 변경 시 다음 정합성 문제가 발생한다:

- **trading_mode**: 봇 시작 시 Virtual/Live 컨텍스트가 결정되므로, 변경 시 실행 중인 컨텍스트와 DB 상태가 불일치
- **broker_type**: 브로커 어댑터 인스턴스가 캐싱되므로, 변경 시 기존 어댑터와 새 타입이 충돌
- **exchange / currency**: Treasury 잔고, 거래 기록, 종목 체계가 시장에 종속되므로, 변경 시 모든 하위 데이터의 정합성이 파괴됨

거래 모드나 브로커를 변경해야 하는 경우, 새 계좌를 생성하여 전환한다. `update()` 호출 시 불변 필드가 포함되면 `AccountImmutableFieldError`를 발생시킨다.

> canonical exchange 계약 SSOT: [core.md `## Canonical Exchange Vocabulary`](../core/core.md#canonical-exchange-vocabulary).
> `exchange`는 identity 필드이며 account는 canonical-only(`*` 거부) 표면이다.
> 계좌 생성과 structural/identity 필드 변경(`exchange` 등)은 cold-path 가드가
> 입력 무관 409(invariant I1, 422 아님)다.
> mutable-only 필드(`name`/`timezone`/`trading_hours_start`/`trading_hours_end`)는
> 런타임 허용이며 409가 아니다. 1.0 preset은 `KRX`,`TEST`만 제공한다
> (canonical-known 5종과 별개). 표면별 정렬은 #1578에서 다룬다.
> 참고: 이 문서의 `exchange` 설명/표에 남아 있는 `{KRX, NYSE, NASDAQ, TEST}` 나열은
> canonical-known 5종(`{KRX, NYSE, NASDAQ, AMEX, TEST}`) 대비 **`AMEX` 누락 drift**다.
> 이 이슈(#1575)는 normative 값 집합을 재작성하지 않으며, account schema/서비스 검증의
> canonical 정렬(`AMEX` 포함 여부 포함)은 #1578에서 수행한다.

### BrokerPreset

브로커별 프리셋을 내부에 정의하여, 계좌 생성 시 거래소·브로커 선택만으로 나머지 필드를 자동 채운다. 사용자가 명시적으로 지정하지 않은 필드는 프리셋 기본값이 적용된다.

소스: `src/ante/account/models.py`

- `market_order_reserve_buffer_rate`: #1333: Account 의 ``market_order_reserve_buffer_rate`` 초기값.

### BROKER_PRESETS

소스: `src/ante/account/presets.py`

- `BROKER_PRESETS["test"].market_order_reserve_buffer_rate`: #1333: 결정적 거동.
- `BROKER_PRESETS["kis-domestic"].market_order_reserve_buffer_rate`: #1333: 0.5%.
- `BROKER_PRESETS["mock"].required_credentials`: 가상 전용 (#2541)
- `BROKER_PRESETS`: kis-overseas 프리셋은 1.0 BROKER_REGISTRY 가 미지원이므로 본 1.0 stage 에서는 정의하지 않는다 (#1333). 1.1 KISOverseasAdapter 도입 시 함께 추가하며, ``market_order_reserve_buffer_rate`` 는 그때 시장 사례에 맞춰 결정한다. legacy DB 의 ``broker_type='kis-overseas'`` row 는 ``accounts.market_order_reserve_buffer_rate`` DDL default(0.005) 를 그대로 유지한다.

| broker_type | exchange | currency | timezone | trading_hours | buy_commission | sell_commission | market_order_buffer | default_account_id | default_name | required_credentials |
|-------------|----------|----------|----------|--------------|----------------|----------------|---------------------|--------------------|--------------|----------------------|
| `test` | `TEST` | `KRW` | `Asia/Seoul` | 00:00–23:59 | 0 | 0 | 0 | `test` | `테스트` | `app_key`, `app_secret` |
| `kis-domestic` | `KRX` | `KRW` | `Asia/Seoul` | 09:00–15:30 | 0.015% | 0.195% | 0.5% | `domestic` | `국내 주식` | `app_key`, `app_secret`, `account_no` |
| `mock` | `TEST` | `KRW` | `Asia/Seoul` | 00:00–23:59 | 0 | 0 | 0 | `mock` | `모의` | 없음(`[]`) |

프리셋 수수료는 어댑터 config와 Treasury에만 쓰인다. 가상 계좌의 체결 수수료는 `VirtualExecutor`의 기본값이다([broker-adapter/06-broker-presets.md](../broker-adapter/06-broker-presets.md)).

> **향후 지원**: `kis-overseas` 는 1.0 단계에서 BROKER_REGISTRY 가 미지원이므로
> BROKER_PRESETS 에 정의하지 않는다. KISOverseasAdapter 구현, `BROKER_REGISTRY`
> 등록, 그리고 그에 맞는 `market_order_reserve_buffer_rate` 결정은 1.1 이후로
> 미룬다. 향후 `ib` (Interactive Brokers) 등 프리셋 추가로 대응.

### BROKER_REGISTRY

정의: `ante.account.service._BROKER_REGISTRY` (코드가 정본이다).

- `_BROKER_REGISTRY`: "kis-overseas": KISOverseasAdapter,  ← 1.1 에서 등록

`BROKER_PRESETS`, 이 `_BROKER_REGISTRY`, CLI의 `--broker-type` 검증에 쓰는
`ante.broker.registry.BROKER_REGISTRY`([broker-adapter/05-broker-registry.md](../broker-adapter/05-broker-registry.md))
세 곳의 keys 가 일치해야 신규 계좌 생성이 preset 기본값과 어댑터 클래스를 동시에
찾는다. 세 곳 모두 `{"test", "kis-domestic", "mock"}` 만 노출한다 (#1333, #2541).
`mock`과 `test`는 가상 전용이다. `(mock, live)`와 `(test, live)` 조합은 계좌 생성과 어댑터 조립에서
`InvalidBrokerTypeError`로 거부한다([broker-adapter/12-test-broker-adapter.md](../broker-adapter/12-test-broker-adapter.md#가상-전용)).

`AccountService.get_broker()`가 `broker_type`으로 이 레지스트리에서 어댑터 클래스를 조회한다. 등록되지 않은 `broker_type`으로 브로커 생성을 시도하면 `InvalidBrokerTypeError`가 발생한다.

소스: `src/ante/account/service.py`
