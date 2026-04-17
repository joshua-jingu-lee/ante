# Approval 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# 타 모듈 설계 시 참고

- **Notification**: `ApprovalCreatedEvent` 구독 시 결재 요약 + 승인/거절 버튼을 포함한 메시지 발송. 양방향 어댑터는 사용자 응답을 수신하여 `ApprovalService`를 호출한다.
- **Report**: 전략 채택 흐름이 Report 직접 채택 → Approval을 통한 채택으로 변경
- **Treasury**: `budget_change` 승인 시 `update_budget()` 호출
- **BotManager**: `bot_create`, `bot_stop` 승인 시 해당 동작 호출
- **Web API**: 결재 목록 조회·승인·거절 API 엔드포인트 필요
