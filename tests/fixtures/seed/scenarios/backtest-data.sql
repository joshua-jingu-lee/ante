-- 시나리오: backtest-data
-- 백테스트 데이터 관리 페이지 플로우
-- 참고: 실제 Parquet 파일은 seeder의 write_sample_parquet으로 생성.
--       이 SQL은 데이터 카탈로그 메타데이터만 제공한다.

-- ── 전략 (백테스트 참조용) ──────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', datetime('now', '-30 days'),
        '20일 고점 돌파 시 매수', 'strategy-dev-01');

-- ── 리포트 (백테스트 결과) ──────────────────────────
INSERT INTO reports (report_id, strategy_name, strategy_version, strategy_path, status, submitted_at, submitted_by,
                     backtest_period, total_return_pct, total_trades, sharpe_ratio, max_drawdown_pct, win_rate,
                     summary, rationale)
VALUES ('report-bt-01', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'submitted',
        datetime('now', '-3 days'), 'strategy-dev-01',
        '2024-01-01 ~ 2025-12-31', 35.2, 142, 1.45, 12.3, 0.62,
        '2년간 35.2% 수익, 샤프 1.45', '모멘텀 팩터의 지속적 유효성 확인');

INSERT INTO reports (report_id, strategy_name, strategy_version, strategy_path, status, submitted_at, submitted_by,
                     backtest_period, total_return_pct, total_trades, sharpe_ratio, max_drawdown_pct, win_rate,
                     summary, rationale)
VALUES ('report-bt-02', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'reviewed',
        datetime('now', '-7 days'), 'strategy-dev-02',
        '2023-01-01 ~ 2025-12-31', 18.5, 89, 0.92, 18.7, 0.54,
        '3년간 18.5% 수익, MDD 18.7%', '단순하지만 안정적');

-- ── 자금 (최소) ─────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 50000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 0.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 50000000.0);

-- ── 에이전트 멤버 ───────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write","data:read","backtest:run","report:write"]', datetime('now', '-60 days'));
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write","data:read","backtest:run"]', datetime('now', '-45 days'));
