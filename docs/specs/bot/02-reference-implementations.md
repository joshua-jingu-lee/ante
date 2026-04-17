# Bot 모듈 세부 설계 - 참고 구현체 분석

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 참고 구현체 분석

| 구현체 | 봇 관리 | 실행 방식 | 전략 연동 | 에러 격리 | 모의투자 |
|--------|---------|---------|---------|---------|---------|
| NautilusTrader | TradingNode + Actor 시스템 | 이벤트 콜백 (데이터 도착 시) | Strategy를 Node에 등록 | Actor 상태 머신 | 백테스트 모드로 대체 |
| FreqTrade | FreqtradeBot 단일 인스턴스 | 주기적 폴링 루프 | IStrategy 동적 로딩 | 단일 봇이므로 해당 없음 | dry-run 모드 |

**Ante의 위치**:
- FreqTrade의 주기적 루프 패턴 채택 (on_step 호출 주기를 봇이 관리)
- NautilusTrader의 Actor 격리 패턴 채택 (봇당 독립 Task)
- 복수 봇 동시 운영 지원 (FreqTrade는 단일 봇)
