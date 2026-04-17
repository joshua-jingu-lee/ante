# Backtest Engine 모듈 세부 설계 - 미결 사항

> 인덱스: [README.md](README.md) | 호환 문서: [backtest.md](backtest.md)

# 미결 사항

- [x] BacktestCompleteEvent 발행 — `BacktestService.run()` 완료 시 `_publish_complete_event()`로 발행. `ReportDraftGenerator`가 구독하여 DRAFT 리포트 자동 생성 ([#493](https://github.com/joshua-jingu-lee/ante/issues/493))
- [x] 백테스트 실행 이력 테이블 (`backtest_runs`) — `BacktestRunStore` (`src/ante/backtest/run_store.py`)로 구현 완료. save/get/list_by_strategy 지원 ([#493](https://github.com/joshua-jingu-lee/ante/issues/493))
- [x] BacktestResult에 실행 설정(config) 포함 — BacktestConfig/DatasetInfo를 BacktestResult에 추가. 본문 "BacktestResult — 결과 데이터" 섹션 및 "BacktestService" 섹션에 반영 완료. 구현은 별도 이슈로 진행.

**`backtest_runs` 스키마 (안):**

```sql
CREATE TABLE backtest_runs (
    run_id          TEXT PRIMARY KEY,
    strategy_name   TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    params_json     TEXT DEFAULT '{}',
    total_return_pct REAL,
    sharpe_ratio    REAL,
    max_drawdown_pct REAL,
    total_trades    INTEGER,
    win_rate        REAL,
    result_path     TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_backtest_runs_strategy ON backtest_runs(strategy_name);
```

> 고급 기능(파라미터 최적화, 벡터화, 멀티 심볼, 워크-포워드 등)은 [Phase 2 아이디어](../../temp/phase2-ideas.md)로 이관.
