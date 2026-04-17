# Broker Adapter 모듈 세부 설계 - 어댑터 계층 구조

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 어댑터 계층 구조

```
BrokerAdapter (ABC)
├── TestBrokerAdapter        — 개발/검증용 테스트 브로커
├── KISBaseAdapter (ABC)     — KIS 공통 레이어 (인증, HTTP, 에러 처리)
│   ├── KISDomesticAdapter   — 국내주식 전용 (기존 KISAdapter 리네이밍)
│   └── KISOverseasAdapter   — 해외주식 전용 (1.1 범위)
└── (향후) IBAdapter 등
```

> **1.1 범위**: `KISOverseasAdapter`는 이 문서에서 확장 포인트만 정의한다. 구현체는 1.1에서 작성하며, `BROKER_REGISTRY`에도 1.1에서 등록한다.
