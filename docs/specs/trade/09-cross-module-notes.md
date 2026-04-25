# Trade 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# 타 모듈 설계 시 참고

- **포지션 조회**: Trade 모듈이 포지션의 단일 소유자. 다른 모듈은 `TradeService.get_positions(bot_id)`로 조회
  - Rule Engine: 포지션 기반 리스크 룰 평가 시 TradeService에서 포지션 조회
  - Treasury: 포지션을 추적하지 않음 — 예산(현금)만 관리
  - Bot/Strategy: StrategyContext의 portfolio_view를 통해 간접 조회
- **Web API 스펙 작성 시**: TradeService를 REST API로 노출 — GET /trades, GET /performance, GET /bots/{id}/summary
- **CLI 스펙 작성 시**: `ante trade list/performance/summary` 커맨드 구현
- **Broker Adapter 스펙 작성 시**: OrderFilledEvent에 commission 필드 포함 필요
- **EventBus 스펙 갱신 시**: OrderCancelledEvent (취소 완료) 이벤트 타입 추가 (OrderCancelEvent는 취소 요청, OrderCancelledEvent는 취소 완료)
- **Bot 스펙 갱신 시**: 봇 성능 지표는 Trade 모듈의 거래 기록과 성과 지표를 참조한다.
- **Notification 스펙 작성 시**: 거래 체결 시 TradeRecord 정보를 포함한 알림 발송 (NotificationEvent에 거래 상세 포함)
