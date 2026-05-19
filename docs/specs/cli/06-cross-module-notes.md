# CLI 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# 타 모듈 설계 시 참고

- **Web API 스펙**: CLI와 동일한 기능을 REST API로 노출, 내부 클라이언트 공유
- **Account 스펙**: `ante account create/delete/set-credentials`는 cold-path structural 커맨드이므로 서버 실행 중 차단한다. `account suspend/activate`와 `system halt/clear-halt`는 IPC 런타임 커맨드다.
- **Bot 스펙**: `ante bot create/start/stop/remove`와 `signal-key --rotate`는 IPC를 통해 서버의 BotManager를 호출하는 런타임 커맨드다. 실행 중 조회(`list/info/status/positions/signal-key`)도 서버 live 상태가 필요하면 IPC를 우선 사용한다. 단 `ante bot start/stop/status` CLI command은 미구현 (follow-up)이며 실재 bot CLI는 `create/info/list/positions/remove/signal-key`다. Bot 생성 시 `--strategy`는 등록된 `strategy_id`이며, 파일 경로를 직접 받지 않는다.
- **Broker Adapter 스펙**: `ante broker status/balance/positions/reconcile`은 서버가 보유한 BrokerAdapter 연결을 사용하는 런타임 IPC 커맨드다. 일반 운영 CLI에서 직접 broker adapter를 생성하거나 `broker order`를 제공하지 않는다.
- **Member 스펙**: `member list/info`는 오프라인 조회가 가능하다. 등록, 상태 변경, 토큰/패스워드/복구키 변경은 서버 실행 중 IPC로 처리하고, 서버 정지 상태에서는 recovery/maintenance fallback만 허용한다.
- **Strategy 스펙**: `ante strategy validate`는 StrategyValidator를 호출하고, `ante strategy submit <path>`는 검증 + 로드 테스트 + StrategyRegistry 등록을 수행한다. 등록 결과인 `strategy_id`가 `ante bot create --strategy` 입력이다.
- **Report Store 스펙**: `ante report submit/schema` → ReportStore, PerformanceFeedback 호출
- **Backtest 스펙**: `ante backtest run` → BacktestService.run_backtest() (subprocess)
- **Data Pipeline 스펙**: `ante data list/schema/storage/validate` → ParquetStore 호출. `ante data retention` 커맨드는 미구현 (RetentionPolicy는 프로그래매틱 사용만)
- **DataFeed 스펙**: `ante feed init/status/config/inject/run/start` → FeedConfig, FeedInjector, FeedOrchestrator 호출
