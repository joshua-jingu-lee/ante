# Web API 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# 타 모듈 설계 시 참고

- **CLI 스펙** ([cli.md](../cli/cli.md)): CLI와 Web API는 동일한 서비스 계층을 공유, 기능 대칭 유지
- **Account 스펙** ([account/README.md](../account/README.md)): 계좌 구조 변경은 cold-path 전용. 런타임 Web API는 계좌 생성/삭제/브로커 재초기화성 수정을 409로 차단한다.
- **EventBus 스펙** ([eventbus.md](../eventbus/eventbus.md)): `ExternalSignalEvent` 정의
- **Bot 스펙** ([bot/README.md](../bot/README.md)): `BotManager`가 REST API에서 호출됨 (생성/시작/중지)
- **Member 스펙** ([member/README.md](../member/README.md)): Web API의 member 변경은 런타임 경로다. 상태·토큰·패스워드·복구키 변경 후 세션 무효화, 감사 로그, 보안 알림을 같은 서버 프로세스에서 처리한다.
- **Report Store 스펙** ([report-store.md](../report-store/report-store.md)): 리포트 CRUD + 상태 변경 API
- **Notification 스펙** ([notification.md](../notification/notification.md)): 알림은 독립 채널 (텔레그램)
- **Treasury 스펙** ([treasury.md](../treasury/treasury.md#일별-자산-스냅샷-daily-asset-snapshot)): 일별 자산 스냅샷 API (`/api/treasury/snapshots/*`) — 포트폴리오 API는 스냅샷 기반 응답
- **Logging 스펙** ([logging/README.md](../logging/README.md)): 시스템 로그 인프라 — 헬스체크 응답 외 운영 로그는 JSONL로 파일 출력
