# Trade 모듈 세부 설계 - 테스트 고려사항

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# 테스트 고려사항

- TradeRecorder: OrderFilledEvent 수신 → trades 테이블에 기록 확인
- TradeRecorder: OrderRejectedEvent / OrderFailedEvent / OrderCancelledEvent 각각 기록 확인
- TradeRecorder: 동일 trade_id 중복 기록 방지 확인
- PositionHistory: 매수 시 수량 증가 + 평균 매입가 재계산 확인
- PositionHistory: 매도 시 수량 감소 + 실현 손익 계산 확인
- PositionHistory: 전량 매도 시 포지션 quantity=0 확인
- PerformanceTracker: 빈 거래 → 빈 지표 반환 확인
- PerformanceTracker: 수익/손실 거래 혼합 시 승률, 수익팩터 정확성 확인
- PerformanceTracker: MDD 계산 정확성 확인 (고점 후 하락 → 회복 → 재하락 시나리오)
- PerformanceTracker: 샤프 비율 — 30건 미만 시 None, 30건 이상 시 계산 확인
- TradeService: get_summary() — 포지션 + 성과 + 최근 거래 통합 반환 확인
- 필터 조합: bot_id + strategy_id + symbol + 기간 동시 필터링 확인
