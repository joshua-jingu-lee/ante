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
| `get_account_balance()` | — | `Dict[str, float]` | 계좌 잔고 조회 (현금 + 주식 평가금액) |
| `get_positions()` | — | `List[Dict]` | 보유 포지션 조회 |
| `get_current_price()` | `symbol: str` | `float` | 현재가 조회 |
| `place_order()` | `symbol: str`, `side: str`, `quantity: float`, `order_type: str = 'market'`, `price: Optional[float] = None`, `stop_price: Optional[float] = None` | `str` | 주문 접수 (주문번호 반환) |
| `cancel_order()` | `order_id: str` | `bool` | 주문 취소 |
| `get_order_status()` | `order_id: str` | `Dict` | 주문 상태 조회 |
| `get_pending_orders()` | — | `List[Dict]` | 미체결 주문 목록 조회 |
| ~~`realtime_price_stream()`~~ | — | — | *스펙 아웃* — 오픈 시점 미포함 |
| ~~`realtime_order_stream()`~~ | — | — | *스펙 아웃* — 오픈 시점 미포함 |
| `get_account_positions()` | — | `List[Dict]` | 증권사 실제 보유 잔고 조회 (대사용) |
| `get_order_history()` | `from_date: Optional[str] = None`, `to_date: Optional[str] = None` | `List[Dict]` | 주문/체결 이력 조회 (대사용) |
| `get_instruments()` | `exchange: str = "KRX"` | `List[Dict]` | 종목 마스터 데이터 조회. KIS API `CTPF1702R` 사용 (KOSPI: J, KOSDAQ: Q) |
| `get_commission_info()` | — | `CommissionInfo` | 수수료 정보 반환 |

**헬퍼 메서드** (구현 제공, 오버라이드 가능):

| 메서드명 | 파라미터 | 반환값 | 설명 |
|----------|----------|--------|------|
| `normalize_symbol()` | `symbol: str` | `str` | 종목코드 표준화 (예: `'5930'` → `'005930'`) |
| `health_check()` | — | `bool` | API 연결 상태 확인 (`get_account_balance()` 호출로 판단) |

**`place_order()` 참고사항**: `stop`/`stop_limit` 주문은 BrokerAdapter가 직접 실행하지 않는다. KRX는 stop order를 네이티브로 지원하지 않으므로, 상위 계층(StopOrderManager)이 가격 모니터링 후 market/limit으로 변환하여 호출한다. 향후 네이티브 stop을 지원하는 브로커(예: Interactive Brokers) 구현 시 이 파라미터를 직접 활용할 수 있다.

**`get_account_positions()` 참고사항**: `get_positions()`와 동일한 API를 호출하되, 대사 전용으로 명시적으로 분리하여 용도를 명확히 한다. 반환 형식: `[{"symbol": "005930", "quantity": 900, "avg_price": 1000.0}, ...]`

**`get_order_history()` 반환 형식**: `[{"order_id": "...", "symbol": "005930", "side": "buy", "quantity": 100, "filled_quantity": 100, "price": 1000.0, "status": "filled", "timestamp": "..."}, ...]`
