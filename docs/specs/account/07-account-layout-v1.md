# Account 모듈 세부 설계 - 1.0 시점 계좌 구성

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 1.0 시점 계좌 구성

```
Account "test"                Account "domestic"
├── exchange: TEST            ├── exchange: KRX
├── currency: KRW             ├── currency: KRW
├── timezone: Asia/Seoul      ├── timezone: Asia/Seoul
├── hours: 00:00–23:59        ├── hours: 09:00–15:30
├── broker: test              ├── broker: kis-domestic
├── credentials: {}           ├── credentials:
│                             │   app_key: PSxxx
│                             │   app_secret: xxx
│                             │   account_no: 50123456-01
├── broker_config: {}         ├── broker_config:
│                             │   is_paper: false
├── buy_commission: 0         ├── buy_commission: 0.00015
├── sell_commission: 0        ├── sell_commission: 0.00195
├── trading_mode: virtual     ├── trading_mode: live
│                             │
├── Rule Engine               ├── Rule Engine
│   (MDD 15%, 손실 5%)       │   (MDD 15%, 손실 5%)
├── Treasury (KRW)            ├── Treasury (KRW)
└── Bots [...]                └── Bots [...]

독립 모듈
├── Strategy Registry (exchange 메타데이터로 시장 구분)
├── Data Store
│   └── KRX/005930/1d/...
└── Backtest Engine
```

> **1.1 예정**: Account "us-stock" (NYSE / USD / kis-overseas) 추가. 브로커 프리셋에 `kis-overseas`는 1.0에서 정의만 해두고, 실제 어댑터 구현 및 US 데이터 파이프라인은 1.1에서 지원.
