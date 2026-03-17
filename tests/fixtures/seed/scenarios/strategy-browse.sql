-- 시나리오: strategy-browse
-- 전략 목록 조회 및 상세 플로우

-- ── 전략 4개 ────────────────────────────────────────
-- A: registered (봇 미할당)
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross-01', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'registered', datetime('now', '-7 days'),
        'SMA 5/20 크로스오버 전략', 'strategy-dev-01');

-- B: active (봇 할당, 거래 없음)
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal-01', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', datetime('now', '-5 days'),
        'RSI 과매도 구간 반등 매수 전략', 'strategy-dev-01');

-- C: active (봇 할당, 거래 있음, 수익)
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', datetime('now', '-14 days'),
        '20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도', 'strategy-dev-01');

-- D: inactive (봇 미할당, 손실)
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('mean-revert-01', '평균회귀', '1.2.0', 'strategies/mean_revert.py', 'inactive', datetime('now', '-30 days'),
        '볼린저밴드 기반 평균회귀 전략', 'strategy-dev-02');

-- ── 봇 (전략 B, C에 할당) ───────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-browse', 'RSI 봇', 'rsi-reversal-01', 'paper',
        '{"bot_id":"bot-rsi-browse","strategy_id":"rsi-reversal-01","name":"RSI 봇","bot_type":"paper","interval_seconds":60}',
        'running', datetime('now', '-3 days'));

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-browse', '모멘텀 봇', 'momentum-v2', 'live',
        '{"bot_id":"bot-momentum-browse","strategy_id":"momentum-v2","name":"모멘텀 봇","bot_type":"live","interval_seconds":60}',
        'running', datetime('now', '-10 days'));

-- ── 거래 내역 (전략 C) ─────────────────────────────
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-01', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 50, 72300, 'filled', datetime('now', '-7 days'), datetime('now', '-7 days'));

INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-02', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 10, 150000, 'filled', datetime('now', '-5 days'), datetime('now', '-5 days'));

INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-03', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 50, 74800, 'filled', datetime('now', '-2 days'), datetime('now', '-2 days'));

-- ── 거래 내역 (전략 D — 과거 기록) ──────────────────
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-d1', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 20, 210000, 'filled', datetime('now', '-45 days'), datetime('now', '-45 days'));
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-d2', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 20, 208600, 'filled', datetime('now', '-40 days'), datetime('now', '-40 days'));
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-d3', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 30, 55000, 'filled', datetime('now', '-38 days'), datetime('now', '-38 days'));
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-d4', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 30, 54200, 'filled', datetime('now', '-35 days'), datetime('now', '-35 days'));
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-d5', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 10, 71000, 'filled', datetime('now', '-33 days'), datetime('now', '-33 days'));
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, timestamp, created_at)
VALUES ('trade-sb-d6', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 10, 70500, 'filled', datetime('now', '-31 days'), datetime('now', '-31 days'));

-- ── 자금 ────────────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('total_cash', 50000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 20000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 30000000.0);

INSERT OR IGNORE INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-browse', 15000000.0, 8500000.0, 1500000.0, 5000000.0, 0.0);
INSERT OR IGNORE INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-browse', 5000000.0, 5000000.0, 0.0, 0.0, 0.0);

-- ── 에이전트 멤버 ───────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write","data:read","backtest:run","report:write"]', datetime('now', '-60 days'));
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write","data:read","backtest:run"]', datetime('now', '-45 days'));
