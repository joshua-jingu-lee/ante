# Broker Adapter 모듈 세부 설계 - BrokerAdapter 인터페이스 (ABC)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# BrokerAdapter 인터페이스 (ABC)

구현: `src/ante/broker/base.py` 참조

BrokerAdapter는 증권사 API 어댑터의 추상 기본 클래스다. 생성 시 `config: dict[str, Any]`를 받으며, `is_connected: bool`, `exchange: str`, `currency: str` 상태를 관리한다.

### 클래스 변수

| 변수명 | 타입 | 설명 |
|--------|------|------|
| `broker_id` | `str` | 브로커 고유 식별자 (예: `"kis-domestic"`, `"test"`) |
| `broker_name` | `str` | 브로커 표시명 (예: `"한국투자증권 국내"`) |
| `broker_short_name` | `str` | 축약명 (예: `"KIS"`, `"TEST"`) |

### 인스턴스 속성

| 속성 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `config` | `dict[str, Any]` | — | 생성자에 전달된 설정 |
| `is_connected` | `bool` | `False` | API 연결 상태 |
| `exchange` | `str` | `config.get("exchange", "KRX")` | 거래소 코드 |
| `currency` | `str` | `config.get("currency", "KRW")` | 통화 코드 |

### 메서드 시그니처

| 메서드명 | 파라미터 | 반환값 | 설명 |
|----------|----------|--------|------|
| `connect()` | — | `None` | API 연결 및 인증 |
| `disconnect()` | — | `None` | 연결 해제 |
| `get_account_balance()` | — | `Dict[str, float]` | 계좌 잔고 조회 (현금 + 주식 평가금액). KIS 반환 키: `cash`, `total_assets`, `purchase_amount`, `eval_amount`, `total_profit_loss`, `substitute_amount`(예수금 대용가능금액=대용증권 평가 기반). **`purchasable_amount`(주문가능액)는 종목 컨텍스트가 필요해 이 메서드가 산출하지 않으며 반환 dict에 포함하지 않는다 — `get_buyable()` 참조** (#2384) |
| `get_buyable()` | `symbol: str`, `price: Optional[float] = None`, `order_type: str = 'market'` | `Dict[str, float]` | 매수가능 조회 (KIS `inquire-psbl-order`, `@abstractmethod`). 반환 키: `order_buyable_amount`(미수없는 매수가능금액·**purchasable_amount SSOT**), `max_buyable_amount`, `order_cash`, `order_buyable_qty`, `max_buyable_qty`. **구현 #2384 merge 후 실행 가능** |
| `get_positions()` | — | `List[Dict]` | 보유 포지션 조회 |
| `get_current_price()` | `symbol: str` | `float` | 현재가 조회 |
| `place_order()` | `symbol: str`, `side: str`, `quantity: float`, `order_type: str = 'market'`, `price: Optional[float] = None`, `stop_price: Optional[float] = None` | `str` | 주문 접수 (주문번호 반환) |
| `cancel_order()` | `order_id: str` | `bool` | 주문 취소 |
| `modify_order()` | `order_id: str`, `*`, `quantity: Optional[float] = None`, `price: Optional[float] = None`, `order_type: str = 'limit'` | `bool` | 주문 정정 (`@abstractmethod`, #2391). **v1 = price-only**: `open` 주문의 가격 정정만 지원하며 수량은 불변(`quantity`는 #2393 forward-compat). KIS는 `order-rvsecncl`(`RVSE_CNCL_DVSN_CD='01'`) 공유. 수량 변경·예산증가 buy·부분체결/터미널·동시성은 Gateway가 broker 호출 전 fail-closed로 거부(고급=#2393) |
| `get_order_status()` | `order_id: str` | `Dict` | 주문 상태 조회 |
| `get_pending_orders()` | — | `List[Dict]` | 미체결 주문 목록 조회 |
| ~~`realtime_price_stream()`~~ | — | — | *스펙 아웃* — 오픈 시점 미포함 |
| ~~`realtime_order_stream()`~~ | — | — | *스펙 아웃* — 오픈 시점 미포함 |
| `get_account_positions()` | — | `List[Dict]` | 증권사 실제 보유 잔고 조회 (대사용) |
| `get_order_history()` | `from_date: Optional[str] = None`, `to_date: Optional[str] = None` | `List[Dict]` | 주문/체결 이력 조회 (대사용). **날짜 인자 어휘는 압축 `YYYYMMDD` 단일**이며 ISO `YYYY-MM-DD`를 받지 않는다 (#2412, 아래 참조) |
| `get_instruments()` | `exchange: str = "KRX"` | `List[Dict]` | 종목 마스터 데이터 조회. KIS API `CTPF1702R` 사용 (KOSPI: J, KOSDAQ: Q) |
| `get_commission_info()` | — | `CommissionInfo` | 수수료 정보 반환 |

**헬퍼 메서드** (구현 제공, 오버라이드 가능):

| 메서드명 | 파라미터 | 반환값 | 설명 |
|----------|----------|--------|------|
| `normalize_symbol()` | `symbol: str` | `str` | 종목코드 표준화 (예: `'5930'` → `'005930'`) |
| `health_check()` | — | `bool` | API 연결 상태 확인 (`get_account_balance()` 호출로 판단) |

**`place_order()` 참고사항**: `stop`/`stop_limit` 주문은 BrokerAdapter가 직접 실행하지 않는다. KRX는 stop order를 네이티브로 지원하지 않으므로, 상위 계층(StopOrderManager)이 가격 모니터링 후 market/limit으로 변환하여 호출한다. 향후 네이티브 stop을 지원하는 브로커(예: Interactive Brokers) 구현 시 이 파라미터를 직접 활용할 수 있다.

**시장가 주문과 reserve estimate 의 분리 (#1333)**: `place_order(order_type="market", price=None)` 은 가격을 지정하지 않는 시장가 주문을 의미하며, BrokerAdapter 는 broker 의 시장가 주문 계약을 그대로 사용한다. Treasury 가 시장가 매수 reserve estimate 를 위해 별도로 `get_current_price` 를 호출해 잠금 금액을 산정하지만, 그 quote 는 reserve 산정 입력이지 주문 가격이 아니다. BrokerAdapter 에 새 quote-estimate API 는 추가하지 않는다 — 기본 resolver 경로는 APIGateway / `BrokerAdapter.get_current_price` 다.

**`get_account_positions()` 참고사항**: `get_positions()`와 동일한 API를 호출하되, 대사 전용으로 명시적으로 분리하여 용도를 명확히 한다. 반환 형식: `[{"symbol": "005930", "quantity": 900, "avg_price": 1000.0}, ...]`

**`get_order_history()` 반환 형식**: `[{"order_id": "...", "symbol": "005930", "side": "buy", "quantity": 100, "filled_quantity": 100, "price": 1000.0, "status": "filled", "timestamp": "..."}, ...]`

**`get_order_history()` 날짜 인자 어휘 (#2412)**: `from_date`/`to_date`는 **압축 `YYYYMMDD`**(예: `"20260701"`) 문자열이며, 이것이 어댑터 계약의 단일 어휘다 — 어댑터는 ISO `YYYY-MM-DD`를 해석하지 않는다(새 어댑터도 자체 ISO 파싱을 추가하지 않는다). 공개 표면(CLI `ante broker order-history --from/--to`, IPC `broker.order_history` args)의 어휘는 ISO `YYYY-MM-DD`이고, 압축형으로의 변환은 **어댑터 호출 직전 모든 경로**(IPC 핸들러 / CLI 직접 연결 폴백)가 공유 헬퍼 하나 `ante.core.time.iso_to_kis_date`(`src/ante/core/time.py`)를 통과해 수행한다. `None`은 "미지정"이며 어댑터가 기본 구간을 산출한다. 어댑터가 ISO를 받을 수 있다고 가정하면 KIS 구현의 3개월 경계 판정 같은 **문자열 사전순 비교**가 예외도 경고도 없이 조용히 어긋난다(`08-kis-domestic-adapter.md` · `14-cli.md` · `docs/specs/cli/03-commands.md` `broker order-history` 절 참조).

**`get_account_balance()` vs `get_buyable()` 분리 (#2384)**: `purchasable_amount`(주문가능액)의 SSOT는 `get_buyable()`이 반환하는 `order_buyable_amount`(KIS `inquire-psbl-order`의 `nrcvb_buy_amt` — 미수 미사용 매수가능금액, 보수값)다. 무인자 `get_account_balance()`(`inquire-balance`)는 종목 컨텍스트가 없어 주문가능액을 산출할 수 없고, `inquire-balance`의 `psbl_sbst_amt`(예수금 대용가능금액=대용증권 평가 기반)는 현금-only 계좌에서 정상적으로 0이므로 주문가능액과 의미가 다르다(#2384 근본원인). 따라서 `psbl_sbst_amt`는 `get_account_balance()`의 `substitute_amount` 키로 보존하고 `purchasable_amount`로 덮어쓰지 않으며, `get_account_balance()` 반환 dict에서 `purchasable_amount` 키는 **제거**한다(무인자 메서드가 못 구하므로 '없는 게 진실'; CLI/Treasury는 `.get()`/별도 주입으로 처리). 주문가능액은 종목/단가/주문구분을 입력으로 받는 별도 `@abstractmethod` `get_buyable()`로 조회한다. 모의 rate-limit(5req/min)을 위해 두 호출은 분리되어 호출처가 빈도를 독립 제어한다. **결제일(T+2) 반영 매수가능금액은 본 계약 범위 밖이다**(`account/11-scope-out.md:11` 연기 유지 — 결제일 미반영 단순 주문가능액만). 본 계약은 **구현 #2384 merge 후 실행 가능**하다.

**`get_buyable()` 어댑터별 반환 정책 (#2384)**: `get_buyable()`는 `BrokerAdapter` ABC의 `@abstractmethod`이므로 모든 어댑터가 구현해야 한다(미구현 시 인스턴스화 불가). 어댑터별 규약은 다음과 같다.
- **KIS 어댑터**(`KISBaseAdapter` `@abstractmethod` → `KISDomesticAdapter` impl, `get_account_balance`과 동형 레이어): `inquire-psbl-order`를 호출해 위 키를 채운다(08-kis-domestic-adapter §inquire-psbl-order 참조).
- **가상 어댑터**(`MockBrokerAdapter`/`TestBrokerAdapter`): 브로커 호출 없이 보유 현금(`cash`) 기반으로 산정한다 — `order_buyable_amount = order_cash = cash`, `max_buyable_amount = cash`, `order_buyable_qty = max_buyable_qty = floor(cash / 단가)`(시장가/`price=None`이면 내부 현재가로 단가 대체, 단가 0이면 수량 0.0). 이 가상 구현으로 ABC 인스턴스화·테스트 경로가 깨지지 않으며 Virtual 모드에서 합리적 값을 반환한다.
- **KISOverseasAdapter**: 1.1 범위(구현체 미존재)로 본 계약의 대상이 아니다(`account/11-scope-out.md:7`).
