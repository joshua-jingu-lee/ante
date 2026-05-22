# Account 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 타 모듈 설계 시 참고

- **Bot 스펙**: `BotConfig.account_id`로 소속 계좌를 지정한다. 봇 생성 시 계좌의 exchange와 전략의 `StrategyMeta.exchange` 호환성을 검증한다. `AccountSuspendedEvent` 구독 시 해당 계좌의 봇만 중지한다.
- **Treasury 스펙**: Treasury는 계좌별로 인스턴스가 분리된다. Account의 `currency`로 통화를 구분하고, `buy_commission_rate`·`sell_commission_rate`·`market_order_reserve_buffer_rate` (3 rate 필드)를 Account에서 조회한다. `market_order_reserve_buffer_rate`는 시장가 매수 reserve 산정 시 `reserve_basis = quantity * quote * (1 + buffer)` 식으로 적용되는 Account-level 정책이며, broker config 가 아니다 (#1333).
- **Rule Engine 스펙**: Rule Engine은 계좌별로 인스턴스가 분리된다. 계좌별 설정값(MDD 한도 등)을 Account에 종속하여 관리한다.
- **Broker Adapter 스펙**: `AccountService.get_broker(account_id)`로 계좌의 BrokerAdapter 인스턴스를 조회한다. `BROKER_REGISTRY`에 등록된 `broker_type`만 인스턴스 생성 가능.
- **Gateway 스펙**: 주문 요청 시 `account_id`로 대상 계좌를 식별하고, 해당 계좌의 BrokerAdapter로 라우팅한다.
- **Trade 스펙**: 거래 기록은 `account_id`로 scoping된다. 계좌에 종속되지 않으나 조회·필터링 시 계좌 단위로 분리.
- **Strategy 스펙**: 전략은 글로벌 Registry에 등록하고, `StrategyMeta.exchange`로 대상 시장을 명시한다. 봇 배정 시 계좌 exchange와 호환성을 검증한다.
- **Lifecycle cold-path 계약**: 계좌 생성/삭제/credentials 변경/broker_config·commission·market_order_reserve_buffer_rate 변경은 서버 정지 상태에서만 허용한다 (#1333: 9 STRUCTURAL_FIELDS). 서버 실행 중에는 조회, suspend/activate, 비구조 필드 수정, 계좌별 rule 변경만 허용한다.
- **CLI 스펙**: `ante account create/delete/set-credentials`는 cold-path 전용이며 서버 실행 중이면 거부한다. `list/info/credentials/suspend/activate`, `ante system halt/clear-halt`는 런타임 중 실행 가능하다.
