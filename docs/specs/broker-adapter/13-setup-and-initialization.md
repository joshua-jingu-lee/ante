# Broker Adapter 모듈 세부 설계 - 설정 및 초기화

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 설정 및 초기화

### 브로커 전환

Account 모델의 `broker_type`으로 어댑터를 결정한다. `AccountService.get_broker(account_id)`가 `BROKER_REGISTRY`에서 어댑터 클래스를 조회하고, 계좌의 설정(credentials, trading_mode 등)을 config로 전달하여 인스턴스를 생성한다.

### 설정 예시

계좌 기반 설정 체계를 사용한다. 아래는 `ante account create` 또는 설정 파일로 등록하는 계좌 예시이다.

```toml
# 국내주식 계좌
[[accounts]]
account_id = "domestic"
broker_type = "kis-domestic"
trading_mode = "live"       # "live" (실거래) | "virtual" (가상거래, 브로커 호출 안 함)

[accounts.credentials]
app_key = "your_app_key"
app_secret = "your_app_secret"
account_no = "12345678-01"

[accounts.broker_config]
is_paper = true             # true: 모의투자 엔드포인트, false: 실전투자 엔드포인트

# 테스트 브로커 계좌
[[accounts]]
account_id = "test"
broker_type = "test"
trading_mode = "virtual"

[accounts.options]
seed = 42
initial_cash = 100000000
tick_interval = 1.0
```

`__init__.py`에서 `BrokerAdapter`, `KISBaseAdapter`, `KISDomesticAdapter`, `KISStreamClient`, `CircuitBreaker`, `CircuitState`, `CommissionInfo`, `OrderRegistry`, `MockBrokerAdapter`, `TestBrokerAdapter`, `BROKER_REGISTRY` 및 예외 클래스(`BrokerError`, `AuthenticationError`, `APIError`, `OrderNotFoundError`, `RateLimitError`, `CircuitOpenError`)를 export한다.
