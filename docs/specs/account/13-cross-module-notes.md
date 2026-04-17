# Account 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 타 모듈 설계 시 참고

- **Bot 스펙**: `BotConfig.account_id`로 소속 계좌를 지정한다. 봇 생성 시 계좌의 exchange와 전략의 `StrategyMeta.exchange` 호환성을 검증한다. `AccountSuspendedEvent` 구독 시 해당 계좌의 봇만 중지한다.
- **Treasury 스펙**: Treasury는 계좌별로 인스턴스가 분리된다. Account의 `currency`로 통화를 구분하고, `buy_commission_rate`·`sell_commission_rate`를 Account에서 조회한다.
- **Rule Engine 스펙**: Rule Engine은 계좌별로 인스턴스가 분리된다. 계좌별 설정값(MDD 한도 등)을 Account에 종속하여 관리한다.
- **Broker Adapter 스펙**: `AccountService.get_broker(account_id)`로 계좌의 BrokerAdapter 인스턴스를 조회한다. `BROKER_REGISTRY`에 등록된 `broker_type`만 인스턴스 생성 가능.
- **Gateway 스펙**: 주문 요청 시 `account_id`로 대상 계좌를 식별하고, 해당 계좌의 BrokerAdapter로 라우팅한다.
- **Trade 스펙**: 거래 기록은 `account_id`로 scoping된다. 계좌에 종속되지 않으나 조회·필터링 시 계좌 단위로 분리.
- **Strategy 스펙**: 전략은 글로벌 Registry에 등록하고, `StrategyMeta.exchange`로 대상 시장을 명시한다. 봇 배정 시 계좌 exchange와 호환성을 검증한다.
- **Web API 스펙**: 계좌 CRUD (`GET/POST /api/accounts`, `GET/PUT/DELETE /api/accounts/:id`), Kill Switch (`POST /api/accounts/:id/suspend`, `/activate`), 시스템 전체 Kill Switch (`POST /api/system/halt`, `/activate`)
- **CLI 스펙**: `ante account create/list/info/suspend/activate/delete/credentials/set-credentials`, `ante system halt/activate`
