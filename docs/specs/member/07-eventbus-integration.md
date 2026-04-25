# Member 모듈 세부 설계 - 이벤트 버스 연동 (EventBus Integration)

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# 이벤트 버스 연동 (EventBus Integration)

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `MemberRegisteredEvent` | 멤버 등록 시 | 감사 로그 |
| `MemberSuspendedEvent` | 멤버 정지 시 | SessionService 세션 무효화, Notification (알림), 감사 로그 |
| `MemberReactivatedEvent` | 멤버 재활성화 시 | 감사 로그 |
| `MemberRevokedEvent` | 멤버 폐기 시 | SessionService 세션 무효화, Notification (알림), 감사 로그 |
| `MemberTokenRotatedEvent` | 토큰 재발급 시 | 감사 로그 |
| `MemberPasswordChangedEvent` | 패스워드 변경/리셋 시 | SessionService 세션 무효화, Notification (보안 알림), 감사 로그 |
| `MemberRecoveryKeyRegeneratedEvent` | recovery key 재발급 시 | Notification (보안 알림), 감사 로그 |
| `MemberAuthFailedEvent` | 인증 실패 시 | Notification (보안 알림), 감사 로그 |
| `NotificationEvent` | 인증 실패 시 | NotificationService → Telegram 어댑터 (category: "member") |

`MemberAuthFailedEvent`는 연속 실패 시 Notification을 통해 master에게 보안 경고를 발송한다.
서버 실행 중 member 변경 CLI는 IPC로 서버 프로세스에서 실행되어 위 이벤트와 세션
무효화가 같은 런타임 안에서 처리되어야 한다. 서버 정지 상태의 maintenance fallback은
DB 감사 기록을 남기고, 서버 재시작 후 변경된 member 상태를 canonical DB에서 로드한다.
