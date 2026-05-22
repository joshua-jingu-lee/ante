# Bot 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 타 모듈 설계 시 참고

- **Account 스펙 작성 시**: Bot은 account_id로 Account에 소속. AccountSuspendedEvent 발행 시 해당 계좌의 봇 일괄 중지
- **Treasury 스펙 작성 시**: ContextFactory가 계좌별 자금 할당(`TreasuryManager.get(account_id)`) + 포지션 조회(Trade) 인터페이스를 StrategyContext에 주입
- **Data Pipeline 스펙 작성 시**: ContextFactory가 DataProvider를 StrategyContext에 주입
- **Rule Engine 스펙 작성 시**: OrderRequestEvent에 bot_id, account_id 포함 — 봇별·계좌별 룰 조회에 활용
- **Web API 스펙 작성 시**: BotManager의 create/start/stop/list를 REST API로 노출
- **CLI/IPC 스펙 작성 시**: `bot create/start/stop/remove`와 `signal-key --rotate`는 런타임 IPC로 서버 BotManager에 위임한다. 실행 중 조회는 서버 live 상태가 필요하면 IPC를 우선 사용하고, 서버 정지 중에는 persisted snapshot만 조회한다. `ante bot start/stop/status`는 Web API 봇 라우트(`POST /api/bots/{bot_id}/start`, `POST /api/bots/{bot_id}/stop`, `GET /api/bots/{bot_id}`)와 1:1 정렬되며, `start`의 `app_key` credential preflight·`BotDetailResponse` envelope·`bot.start`/`bot.stop` audit action 이름은 Web API 라우트 동작과 같은 SSOT를 사용한다.
- **Notification 스펙 작성 시**: BotErrorEvent 구독 → 텔레그램 알림 발송
