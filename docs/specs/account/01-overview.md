# Account 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 개요

Account는 **거래소·통화·브로커·수수료·인증 정보를 하나로 묶는 최상위 엔티티**다.
봇, Treasury, Rule Engine이 계좌에 종속되어 배타적으로 관리되며, 시장별 차이는 계좌 안에 캡슐화된다.

**주요 기능**:
- **시장 연동 정보의 완결적 소유**: 거래소·통화·브로커 유형·인증 정보·수수료 등
- **BrokerAdapter 인스턴스 생성·관리**: 계좌에 종속된 브로커 어댑터의 lazy init + 캐싱
- **계좌 CRUD 및 상태 관리**: ACTIVE / SUSPENDED / DELETED 상태 전이
- **Kill Switch 통합**: 계좌 정지/활성화를 통한 거래 중단 메커니즘

### Account가 하지 않는 것

- 주문 실행 → BrokerAdapter (Account가 생성한 인스턴스)
- 잔고·예산 관리 → Treasury (Account에 종속)
- 전략 정의·검증 → Strategy Registry (글로벌, 봇을 통해 계좌에 연결)
- 전략 성과·거래 기록 → Trade 모듈 (account_id로 scoping)
- 결재 처리 → Approval (account_id를 참조하여 맥락 구분)
- 룰 평가 → Rule Engine (Account에 종속)

### Account 중심의 모듈 구조

**Member만이 여러 Account에 걸쳐 존재하는 유일한 엔티티다.** Strategy, Data, Backtest는 계좌에 종속되지 않는 독립 모듈이다. 나머지 실행·자금·리스크 모듈은 Account 안에서 완결된다.

```
Member (owner, agent-01, ...)         ← 여러 Account에 연결
│
├── Account "test"
│   ├── BrokerAdapter (TestBroker)
│   ├── Treasury (KRW)
│   ├── Rule Engine (룰 인스턴스 + 설정값)
│   ├── Bot [...]
│   └── Instrument (TEST 종목)
├── Account "domestic"
│   ├── BrokerAdapter (KISDomestic)
│   ├── Treasury (KRW)
│   ├── Rule Engine (MDD 15%, 일일 손실 5%)
│   ├── Bot [...]
│   └── Instrument (KRX 종목)
└── Account "us-stock"              ← 향후 지원 (1.1)
    ├── BrokerAdapter (KISOverseas)
    ├── Treasury (USD)
    ├── Rule Engine (MDD 10%, 일일 손실 3%)
    ├── Bot [...]
    └── Instrument (NYSE 종목)

독립 모듈 (Account 밖)
├── Strategy Registry (전략 정의, exchange 메타데이터)
├── Data Store (exchange/symbol/timeframe 기준, 여러 계좌가 공유)
└── Backtest Engine (계좌 없이 독립 실행)
```

| Account에 종속 | Account로 scoping | Account 밖 (독립) |
|---------------|-------------------|-------------------|
| BrokerAdapter 인스턴스 | Strategy 성과/실행 이력 | Member (여러 Account에 연결) |
| Treasury (잔고, 예산) | Approval (account_id 참조) | Strategy Registry (정의 + exchange 메타) |
| Rule Engine (룰 인스턴스 + 설정값) | Trade 기록 | Data Store (시세 데이터, exchange 기준) |
| Bot (실행 단위) | | Backtest Engine |
| Instrument (종목 마스터) | | EventBus |
| Commission / Settlement 규칙 | | Audit Log |
| | | Notification |

**종속 vs scoping vs 독립 구분**:
- **종속**: 계좌가 삭제되면 함께 삭제되어야 하는 데이터. 계좌 없이 존재할 수 없음.
- **scoping**: 데이터 자체는 독립적이나 `account_id`로 범위가 지정됨. 조회·필터링·집계 시 계좌 단위로 분리.
- **독립**: 계좌와 무관하거나, 여러 계좌가 공유하는 모듈. 계좌 생성 전에도 사용 가능.
