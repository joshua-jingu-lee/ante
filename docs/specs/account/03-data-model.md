# Account 모듈 세부 설계 - 데이터 모델

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 데이터 모델

### AccountStatus

```python
class AccountStatus(StrEnum):
    ACTIVE = "active"         # 정상 운영
    SUSPENDED = "suspended"   # 거래 정지 (Kill Switch, 수동 정지)
    DELETED = "deleted"       # 소프트 딜리트
```

### TradingMode

```python
class TradingMode(StrEnum):
    VIRTUAL = "virtual"   # 가상거래 (시뮬레이션)
    LIVE = "live"         # 실제거래
```

### Account

```python
@dataclass
class Account:
    # --- 식별 ---
    account_id: str                    # 영문+숫자+하이픈, 3–30자
    name: str                          # 표시 이름

    # --- 시장 ---
    exchange: str                      # "KRX", "NYSE", "NASDAQ", "TEST"
    currency: str                      # "KRW", "USD"
    timezone: str                      # "Asia/Seoul", "America/New_York"
    trading_hours_start: str           # "09:00" (현지 시간, HH:MM)
    trading_hours_end: str             # "15:30" (현지 시간, HH:MM)

    # --- 거래 모드 ---
    trading_mode: TradingMode          # VIRTUAL / LIVE

    # --- 브로커 ---
    broker_type: str                   # "kis-domestic", "test" (kis-overseas는 1.1)
    credentials: dict[str, str] = field(default_factory=dict)  # 인증 정보 (암호화 저장)
    broker_config: dict[str, Any] = field(default_factory=dict) # 브로커 동작 설정

    # --- 비용 ---
    buy_commission_rate: Decimal = Decimal("0")    # 매수 수수료율
    sell_commission_rate: Decimal = Decimal("0")   # 매도 수수료율 (세금 포함)

    # --- 상태 ---
    status: AccountStatus = AccountStatus.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

소스: `src/ante/account/models.py`

### 필드 설명

| 필드 | 필수 | 기본값 | 수정 | 설명 |
|------|------|--------|:----:|------|
| **식별** | | | | |
| `account_id` | O | — | 불가 | 고유 식별자 (영문+숫자+하이픈, 3–30자) |
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
| `credentials` | - | `{}` | 가능 | 브로커 인증 정보 (암호화 저장) |
| `broker_config` | - | `{}` | 가능 | 브로커 동작 설정 (예: KIS `is_paper`) |
| **비용** | | | | |
| `buy_commission_rate` | - | `0` | 가능 | 매수 수수료율 |
| `sell_commission_rate` | - | `0` | 가능 | 매도 수수료율 (세금 포함) |
| **상태** | | | | |
| `status` | - | `ACTIVE` | 상태 전이 | 계좌 상태 (ACTIVE / SUSPENDED / DELETED) |

### 불변 필드 정책 (D-ACC-06)

`exchange`, `currency`, `trading_mode`, `broker_type`는 생성 후 수정할 수 없다. 이 4개 필드는 계좌의 정체성을 결정하는 근본 속성이며, 런타임 중 변경 시 다음 정합성 문제가 발생한다:

- **trading_mode**: 봇 시작 시 Paper/Live 컨텍스트가 결정되므로, 변경 시 실행 중인 컨텍스트와 DB 상태가 불일치
- **broker_type**: 브로커 어댑터 인스턴스가 캐싱되므로, 변경 시 기존 어댑터와 새 타입이 충돌
- **exchange / currency**: Treasury 잔고, 거래 기록, 종목 체계가 시장에 종속되므로, 변경 시 모든 하위 데이터의 정합성이 파괴됨

거래 모드나 브로커를 변경해야 하는 경우, 새 계좌를 생성하여 전환한다. `update()` 호출 시 불변 필드가 포함되면 `AccountImmutableFieldError`를 발생시킨다.

### BrokerPreset

브로커별 프리셋을 내부에 정의하여, 계좌 생성 시 거래소·브로커 선택만으로 나머지 필드를 자동 채운다. 사용자가 명시적으로 지정하지 않은 필드는 프리셋 기본값이 적용된다.

```python
@dataclass
class BrokerPreset:
    exchange: str
    currency: str
    timezone: str
    trading_hours_start: str
    trading_hours_end: str
    buy_commission_rate: Decimal
    sell_commission_rate: Decimal
    default_account_id: str
    default_name: str
    required_credentials: list[str]
```

소스: `src/ante/account/models.py`

### BROKER_PRESETS

```python
BROKER_PRESETS: dict[str, BrokerPreset] = {
    "test": BrokerPreset(
        exchange="TEST", currency="KRW", timezone="Asia/Seoul",
        trading_hours_start="00:00", trading_hours_end="23:59",
        buy_commission_rate=Decimal("0"), sell_commission_rate=Decimal("0"),
        default_account_id="test", default_name="테스트",
        required_credentials=["app_key", "app_secret"],
    ),
    "kis-domestic": BrokerPreset(
        exchange="KRX", currency="KRW", timezone="Asia/Seoul",
        trading_hours_start="09:00", trading_hours_end="15:30",
        buy_commission_rate=Decimal("0.00015"), sell_commission_rate=Decimal("0.00195"),
        default_account_id="domestic", default_name="국내 주식",
        required_credentials=["app_key", "app_secret", "account_no"],
    ),
    # kis-overseas 프리셋은 정의만 해둔다.
    # KISOverseasAdapter 구현 및 BROKER_REGISTRY 등록은 1.1에서 지원.
    "kis-overseas": BrokerPreset(
        exchange="NYSE", currency="USD", timezone="America/New_York",
        trading_hours_start="09:30", trading_hours_end="16:00",
        buy_commission_rate=Decimal("0.001"), sell_commission_rate=Decimal("0.001"),
        default_account_id="us-stock", default_name="미국 주식",
        required_credentials=["app_key", "app_secret", "account_no"],
    ),
}
```

소스: `src/ante/account/presets.py`

| broker_type | exchange | currency | timezone | trading_hours | buy_commission | sell_commission |
|-------------|----------|----------|----------|--------------|----------------|----------------|
| `test` | `TEST` | `KRW` | `Asia/Seoul` | 00:00–23:59 | 0 | 0 |
| `kis-domestic` | `KRX` | `KRW` | `Asia/Seoul` | 09:00–15:30 | 0.015% | 0.195% |
| `kis-overseas` | `NYSE`, `NASDAQ`, `AMEX` | `USD` | `America/New_York` | 09:30–16:00 | 0.1% | 0.1% |

> **향후 지원**: `kis-overseas`는 프리셋만 정의해두고, KISOverseasAdapter 구현 및 `BROKER_REGISTRY` 등록은 1.1에서 지원한다. 따라서 "us-stock" Account 생성은 1.1 이후 가능하다. 향후 `ib` (Interactive Brokers) 등 프리셋 추가로 대응.

### BROKER_REGISTRY

```python
_BROKER_REGISTRY: dict[str, type[BrokerAdapter]] = {
    "test": TestBrokerAdapter,
    "kis-domestic": KISDomesticAdapter,
    # "kis-overseas": KISOverseasAdapter,  ← 1.1에서 등록
}
```

`AccountService.get_broker()`가 `broker_type`으로 이 레지스트리에서 어댑터 클래스를 조회한다. 등록되지 않은 `broker_type`으로 브로커 생성을 시도하면 `InvalidBrokerTypeError`가 발생한다.

소스: `src/ante/account/service.py`
