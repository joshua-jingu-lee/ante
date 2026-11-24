# Broker Adapter 모듈 세부 설계 - TestBrokerAdapter — 개발/검증용 테스트 브로커

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# TestBrokerAdapter — 개발/검증용 테스트 브로커

> 소스: [`src/ante/broker/test.py`](../../../src/ante/broker/test.py)

KIS 실전 API 없이 시스템 전체 흐름을 검증할 수 있는 테스트 브로커. GBM(Geometric Brownian Motion) 기반 현실적 가격 시뮬레이션, 슬리피지, 부분 체결을 지원하며, 시드 기반으로 동일한 시나리오를 재현할 수 있다.

`exchange`, `currency`는 config에서 수신하며, 다양한 시장 환경을 시뮬레이션할 수 있다.

정의: `ante.broker.test.TestBrokerAdapter` (코드가 정본이다).

식별 값: `broker_id` = `"test"`, `broker_name` = `"테스트 브로커"`, `broker_short_name` = `"TEST"`.

### MockBrokerAdapter와의 차이

| 특성 | TestBrokerAdapter | MockBrokerAdapter |
|------|-------------------|-------------------|
| **용도** | 개발/검증 (현실적 시뮬레이션) | 가상 계좌 시나리오 검증 (가격 고정) |
| **브로커 타입** | `test` | `mock` (가상 계좌 전용) |
| **가격** | GBM 기반 랜덤 시뮬레이션 (조회할 때마다 움직임) | 정적 가격. 가격 주입 파일(`prices_file`) 또는 생성자 `prices`·`default_price` |
| **슬리피지** | 0.1~0.3% 자동 적용 | 없음 |
| **부분 체결** | 확률적 (수량 ≥ 100 시 30% 확률) | FillMode enum으로 결정적 제어. 가상 경로에서는 쓰이지 않음 (아래 「실전 경로의 체결 모드」) |
| **종목** | 가상 종목 6개 프리셋 | `get_instruments`는 하드코딩 2개. 가격은 주입한 종목 코드 |
| **재현성** | 시드 기반 동일 시퀀스 | 같은 가격 주입이면 같은 가격 |

두 브로커 모두 가상 계좌에서는 체결을 하지 않는다. 가상 계좌의 주문은 `VirtualExecutor`가 게이트웨이 가격으로 체결하고 브로커로 보내지 않는다([api-gateway.md](../api-gateway/api-gateway.md) "Virtual 주문 라우팅"). 그래서 가상 경로에서 어댑터가 정하는 것은 사실상 `get_current_price`가 돌려주는 가격이고, 위 표의 슬리피지·부분 체결 행은 실전 경로에만 해당한다. `mock`의 체결 모드가 실전 경로에서 뜻하는 것은 아래 「실전 경로의 체결 모드」를 따른다.

### 생성자 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `seed` | int | 42 | 시뮬레이션 시드 (재현 가능한 결과) |
| `initial_cash` | float | 100,000,000 | 초기 계좌 잔고 |
| `tick_interval` | float | 1.0 | 스트리밍 가격 갱신 간격 (초) |
| `exchange` | str | `"TEST"` | 거래소 코드 (config에서 수신) |
| `currency` | str | `"KRW"` | 통화 코드 (config에서 수신) |

### PriceSimulator — GBM 기반 가격 시뮬레이션

> 소스: [`src/ante/broker/test.py`](../../../src/ante/broker/test.py) `PriceSimulator` 클래스

GBM 모델로 현실적 가격 변동을 시뮬레이션한다. 일별 변동성을 틱 단위로 변환(`σ_tick = σ_daily / √23,400`)하고, exchange에 따라 호가 단위를 분기한다.

**가상 종목 프리셋** (`VIRTUAL_STOCK_PRESETS`):

| 종목코드 | 종목명 | 기준가 | 일변동성 |
|----------|--------|--------|----------|
| 000001 | 알파전자 | 72,000 | 1.8% |
| 000002 | 베타반도체 | 160,000 | 2.5% |
| 000003 | 감마소프트 | 210,000 | 2.2% |
| 000004 | 델타플랫폼 | 48,000 | 2.8% |
| 000005 | 엡실론모터스 | 230,000 | 1.5% |
| 000006 | 제타에너지 | 390,000 | 2.0% |

### 체결 시뮬레이션

- **시장가 주문**: 슬리피지 0.1~0.3% 자동 적용 (매수 시 가격 상승, 매도 시 가격 하락)
- **지정가 주문**: 슬리피지 없이 지정 가격으로 체결
- **부분 체결**: 수량 100주 이상 시 30% 확률로 발생 (체결 비율 30~90%)
- **잔고 부족**: 매수 시 잔고 부족이면 주문 거부

## 브로커 타입 `mock`

> 소스: [`src/ante/broker/mock.py`](../../../src/ante/broker/mock.py)

`broker_type` `mock`은 `MockBrokerAdapter`를 만든다. 실행할 때마다 같은 가격을 내는 브로커로 가상 계좌의 시나리오를 검증하는 데 쓴다. 프리셋은 [06-broker-presets.md](06-broker-presets.md)를 따른다(거래소 `TEST`, 수수료 0, 필수 자격증명 없음).

### 가상 전용

`mock`은 `trading_mode`가 `virtual`인 계좌에만 쓴다. `(mock, live)` 조합은 아래 두 곳에서 `InvalidBrokerTypeError`(`ACCOUNT_INVALID_BROKER_TYPE`)로 거부한다. 오류 메시지는 타입이 틀린 것이 아니라 `trading_mode`와의 조합이 허용되지 않는다는 것을 밝힌다.

| 지점 | 시점 | 비고 |
|------|------|------|
| `AccountService._persist_account` | 계좌 생성 (`create`와 seed가 공유하는 단일 지점) | `trading_mode`와 `broker_type`은 생성 뒤 바꿀 수 없으므로 수정 경로는 따로 막지 않는다 |
| `AccountService._build_broker_adapter` | 어댑터 조립 | DB를 직접 고친 행에 대한 방어 |

- 판정은 `Account.trading_mode`로 한다. 어댑터 config의 `trading_mode`는 `broker_config`가 덮어쓸 수 있으므로 판정에 쓰지 않는다.
- 가상 전용 브로커 타입의 집합은 한 곳에 두고 두 지점이 함께 쓴다.
- 런타임 준비 상태의 면제 매트릭스에는 `(mock, virtual)`만 둔다([account/02-design-decisions.md](../account/02-design-decisions.md) D-ACC-09).
- 필수 자격증명이 빈 목록이므로 계좌 생성 때 credential을 넘기면 `ACCOUNT_UNKNOWN_CREDENTIAL_KEY`로 거부된다([cli/03-commands.md](../cli/03-commands.md) `account create` 입력 계약).

제품은 `(mock, live)`를 거부한다. 운영 코드에는 이 조합을 여는 스위치가 없다. 데몬 구동 시나리오의 하네스가 자기가 띄운 하위 프로세스(CLI와 데몬)에 싣는 테스트 전용 코드가, 하네스가 넣은 환경 변수가 있을 때만 그 프로세스의 가상 전용 집합에서 `mock`을 뺀다. 다른 가상 전용 타입은 빼지 않는다. 주입이 효력을 내지 못하면 위 두 지점의 거부가 그대로 남는다. 그렇게 열린 계좌의 런타임 준비 상태는 면제 매트릭스의 기본 정책(넷 다 요구)을 따른다.

### 실전 경로의 체결 모드

체결 모드는 `mock` 계좌의 주문이 실전 경로(게이트웨이의 제출 → 주문 추적 → 체결 폴링 → 체결 반영 → 정산)를 지날 때 쓰인다. 가상 경로에서는 쓰이지 않는다. 모드는 계좌의 `broker_config`로 준다. 계좌 하나의 어댑터는 모드 하나를 쓴다.

```bash
ante account create --broker-type mock --trading-mode live \
  --broker-config fill_mode=partial --broker-config partial_fill_ratio=0.5
```

| `fill_mode` | `place_order` | 제품이 보는 것 |
|-------------|---------------|----------------|
| `immediate` (기본) | 주문을 받고 곧바로 전량 체결한다 | 다음 체결 폴링이 주문 이력에서 전량을 읽어 반영한다. 예약은 정산되고 남지 않는다 |
| `partial` | 주문 수량 × `partial_fill_ratio`(기본 0.5)를 체결하고 상태를 `partially_filled`로 둔다 | 다음 폴링이 그 수량을 반영한다. 나머지는 체결되지 않으므로 잔여 예약이 남고, 뒤의 폴링은 같은 누적 수량을 다시 반영하지 않는다 |
| `reject` | 주문을 받지 않고 `BrokerError`를 던진다 | 제출 실패(`OrderFailedEvent`)로 끝난다. 예약은 회수되고 거래 기록은 `failed`다. KIS의 거절(`place_order`의 예외)과 같은 경로다 |
| `delayed` | 주문을 받고 체결하지 않는다. 주문 뒤 그 어댑터의 `get_order_history`가 `delay_polls`(기본 2)번째로 불릴 때 전량 체결한다 | 그 차례의 체결 폴링이 전량을 반영한다. 그 전의 폴링은 미체결을 보고 예약은 그대로 남는다 |

- 제품이 체결을 반영하는 시점은 체결 폴링을 따른다. mock이 `place_order` 안에서 체결을 끝내도 제품의 거래 기록과 예산에는 다음 폴링 뒤에 보인다.
- 부분 체결 수량은 내림하지 않는다. 주문 수량과 비율의 곱이 정수가 아니면 소수 수량이 체결된다.
- 주문 장부는 어댑터의 메모리에만 있다. 데몬을 다시 띄우면 사라진다.

지연 모드의 횟수:

- `delay_polls`는 1 이상의 정수다. 불리언이나 정수가 아닌 값, 0 이하의 값은 생성자의 `BrokerError`다. 이전의 `delay_seconds`는 없어졌고 주어도 쓰지 않는다.
- 체결이 보이기 전에는 그 주문의 상태가 `pending`이고 체결 수량이 0이다. mock의 현금과 포지션도 바뀌지 않는다.
- 횟수는 주문마다 그 주문이 접수된 뒤의 호출을 센다. 어댑터는 계좌마다 따로 있으므로 다른 계좌의 조회는 세지 않는다.
- 데몬의 체결 폴링과 부팅 때의 따라잡기가 부르는 `get_order_history`는 횟수에 든다. 데몬이 켜져 있을 때의 `ante broker order-history`도 IPC로 데몬의 어댑터를 부르므로 횟수에 든다. `get_order_status`와 `get_pending_orders`는 세지 않는다.
- 체결이 보이기 전에 취소된 주문은 체결하지 않는다.

### 가격 주입 파일

가격은 데몬 프로세스 밖에서 파일로 주입한다. 파일 경로는 `broker_config`의 `prices_file`(문자열, 절대 경로)로 넘긴다.

```bash
ante account create --broker-type mock --trading-mode virtual \
  --broker-config prices_file=/abs/path/prices.json
```

파일은 JSON 객체다.

```json
{
  "prices": {"000001": 72000, "000002": 160000},
  "default_price": 50000
}
```

| 키 | 필수 | 값 |
|----|------|----|
| `prices` | O | 종목 코드 → 가격. 빈 객체 가능 |
| `default_price` | X | `prices`에 없는 종목의 가격 |

- 가격은 불리언이 아닌 유한한 JSON 수이고 0보다 크다. `true`, `NaN`, `Infinity`는 거부한다.
- 위 두 키 밖의 키는 허용하지 않는다.
- `prices_file`이 있으면 파일이 유일한 가격 원천이다. 파일에 없는 종목은 파일의 `default_price`가 있으면 그 값이고, 없으면 가격 조회가 `BrokerError`다(50,000 기본값으로 떨어지지 않는다).

**오류 조건**: 아래는 모두 생성자의 `BrokerError`다.

- `prices_file`이 상대 경로이거나 파일이 없다
- 내용이 JSON이 아니다
- 허용하지 않는 키가 있거나 `prices`가 없다
- 가격 값이 위 정의에 맞지 않는다
- 같은 config에 `prices_file`과 함께 `prices`나 `default_price`가 있다

**읽는 시점**: 어댑터를 만들 때 한 번 읽는다. 실행 중에는 다시 읽지 않으므로 가격을 바꾸려면 데몬을 다시 띄운다. 데몬이 꺼져 있을 때의 `ante broker …`는 CLI 프로세스에서 어댑터를 새로 만들므로 그때마다 파일을 읽는다.

**검증 시점**: 가격 파일의 검증은 계좌 생성이 아니라 어댑터가 처음 만들어질 때다. 계좌 생성은 `prices_file`의 값을 보지 않으므로 그 파일이 틀려도 통과한다. 가상 계좌에서는 첫 가격 조회가 그 시점이고, 실패하면 시장가 주문이 `virtual_market_price_unavailable`로 끝난다.

`prices_file`이 없으면 생성자 config의 `prices`, `default_price`를 쓴다(`default_price` 기본값 50,000). `mock` 계좌를 만들 때 `broker_config`의 `prices`(객체)의 각 값과 `default_price`는 위 가격 정의로 검사하고, 어기면 계좌 생성이 `VALIDATION_ERROR`로 실패한다. `set_price`는 메모리 값을 바꾸는 테스트 도우미다.

### 전략 거래소 선언

봇은 전략의 `exchange`가 계좌 거래소와 호환될 때만 만들 수 있다. `mock` 계좌(거래소 `TEST`)에 붙일 전략은 `exchange`를 `TEST`나 `*`로 선언한다. `test` 브로커도 같다.

### 결정성의 범위

같은 가격 주입으로 두 번 실행한 결과가 같다는 것은 식별자(`order_id`, `event_id` 등)와 시각 필드를 뺀 체결 필드(종목, 방향, 수량, 가격, 수수료)가 일치한다는 뜻이다. 식별자와 시각의 정규화는 #2542에서 정한다.
