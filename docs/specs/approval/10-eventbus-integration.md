# Approval 모듈 세부 설계 - 이벤트 버스 연동 (EventBus Integration)

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# 이벤트 버스 연동 (EventBus Integration)

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `ApprovalCreatedEvent` | 요청 생성 시 | 현재 직접 구독자 없음 (발행만; 사용자 알림은 아래 `NotificationEvent` 경유) |
| `ApprovalResolvedEvent` | 승인/거절/철회/만료 시 | 현재 직접 구독자 없음 (발행만; 사용자 알림은 아래 `NotificationEvent` 경유) |
| `NotificationEvent` | 요청 생성 시, 처리 완료 시 | NotificationService → Telegram 어댑터 |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
