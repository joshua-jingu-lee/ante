# Trade 모듈 세부 설계 - 이벤트 버스 연동 (EventBus Integration)

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# 이벤트 버스 연동 (EventBus Integration)

| 구분 | 이벤트 | 처리 |
|------|--------|------|
| 구독 | `OrderFilledEvent` | 체결 완료 → 거래 기록 + 포지션 갱신 |
| 구독 | `OrderRejectedEvent` | 룰 검증 실패 → 거부 기록 |
| 구독 | `OrderFailedEvent` | 주문 실행 실패 → 실패 기록 |
| 구독 | `OrderCancelledEvent` | 주문 취소 완료 → 취소 기록 |
| 발행 | `DailyReportEvent` | 장 마감 후 매일 무조건 발행 — Treasury 스냅샷, Rule Engine 일별 집계 트리거 |
| 발행 | `NotificationEvent` | 매수/매도 체결, 주문 취소 실패, 일일 성과 요약 시 (category: "trade") |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
