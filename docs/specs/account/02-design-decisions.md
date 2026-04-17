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

**변경 전**: `ante init` → Master 계정 + KIS 연동 + 알림 + 데이터 API

**변경 후**: `ante init` → Master 계정 + **테스트 계좌 자동 생성** + **계좌 등록 (선택)** + 알림 + 데이터 API

`ante init` 대화형 흐름에서 테스트 계좌는 자동 생성되고, 이어서 실제 계좌(KIS 등) 등록 여부를 묻는다. 사용자가 원하면 계좌번호, APP KEY 등을 입력하여 바로 실전 계좌를 설정할 수 있다. 건너뛰면 이후 `ante account create`로 추가 가능.

```
$ ante init

[1/4] Master 계정 설정
  사용자명: ...
  비밀번호: ...

[2/4] 계좌 설정
  실제 거래 계좌를 등록하시겠습니까?
  등록하지 않으면 테스트 계좌가 자동으로 지정됩니다. (y/N): y

  거래소를 선택하세요:
    1) KRX (한국거래소)
    2) NYSE (뉴욕증권거래소)        ← 향후 지원 (1.1)
    3) NASDAQ (나스닥)              ← 향후 지원 (1.1)
  > 1

  브로커를 선택하세요:
    1) kis-domestic (한국투자증권 국내)
  > 1

  계좌 ID [domestic]: domestic
  이름 [국내 주식]: 국내 주식
  APP KEY: PSxxxxxxxx
  APP SECRET: ********
  계좌번호: 50123456-01
  ✓ 계좌 "domestic" 생성 완료 (KRX / KRW / kis-domestic)

  추가 계좌를 등록하시겠습니까? (y/N): N

[3/4] 알림 설정
  ...

[4/4] 데이터 API 설정
  ...
```

- **N 선택 시**: 테스트 계좌(`account_id: "test"`, `trading_mode: VIRTUAL`)만 자동 생성
- **Y 선택 시**: 실제 계좌를 등록하고, 테스트 계좌도 함께 생성
