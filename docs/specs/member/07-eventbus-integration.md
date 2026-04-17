# Member 모듈 세부 설계 - 이벤트 버스 연동 (EventBus Integration)

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# 이벤트 버스 연동 (EventBus Integration)

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `MemberRegisteredEvent` | 멤버 등록 시 | 감사 로그 |
| `MemberSuspendedEvent` | 멤버 정지 시 | Notification (알림), 감사 로그 |
| `MemberRevokedEvent` | 멤버 폐기 시 | Notification (알림), 감사 로그 |
| `MemberAuthFailedEvent` | 인증 실패 시 | Notification (보안 알림), 감사 로그 |
| `NotificationEvent` | 인증 실패 시 | NotificationService → Telegram 어댑터 (category: "member") |

`MemberAuthFailedEvent`는 연속 실패 시 Notification을 통해 master에게 보안 경고를 발송한다.
