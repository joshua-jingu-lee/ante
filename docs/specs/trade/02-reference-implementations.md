# Trade 모듈 세부 설계 - 참고 구현체 분석

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# 참고 구현체 분석

| 구현체 | 거래 기록 | 성과 계산 | 포지션 추적 | 저장소 |
|--------|---------|---------|-----------|-------|
| NautilusTrader | OrderEvent 체인 + Fill 기록 | PortfolioAnalyzer (실시간 계산) | Position 객체 (상태 머신) | 인메모리 + 외부 카탈로그 |
| FreqTrade | Trade 모델 (ORM) | stats 모듈 (조회 시 계산) | Trade.is_open 플래그 | SQLite/PostgreSQL |

**Ante의 위치**:
- FreqTrade의 Trade 모델 패턴 채택 (SQLite 영속, 조회 시 계산)
- NautilusTrader의 이벤트 기반 자동 기록 패턴 채택 (EventBus 구독)
- 실시간 성과 계산은 불필요 — 조회 시 계산 (N100 환경에서 리소스 절약)
