# CLI 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# 타 모듈 설계 시 참고

- **Web API 스펙**: CLI와 동일한 기능을 REST API로 노출, 내부 클라이언트 공유
- **Account 스펙**: `ante account create/delete/set-credentials`는 cold-path structural 커맨드이므로 서버 실행 중 차단한다. `account suspend/activate`와 `system halt/activate`는 IPC 런타임 커맨드다.
- **Bot 스펙**: `ante bot create/remove` → IPC를 통해 서버의 BotManager 호출 (런타임 커맨드). `start/stop/list/status` 등 나머지는 오프라인 커맨드
- **Strategy 스펙**: `ante strategy validate` → StrategyValidator 호출
- **Report Store 스펙**: `ante report submit/schema` → ReportStore, PerformanceFeedback 호출
- **Backtest 스펙**: `ante backtest run` → BacktestService.run_backtest() (subprocess)
- **Data Pipeline 스펙**: `ante data list/schema/storage/validate` → ParquetStore 호출. `ante data retention` 커맨드는 미구현 (RetentionPolicy는 프로그래매틱 사용만)
- **DataFeed 스펙**: `ante feed init/status/config/inject/run/start` → FeedConfig, FeedInjector, FeedOrchestrator 호출
