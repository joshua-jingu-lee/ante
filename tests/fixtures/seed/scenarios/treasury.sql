-- 시나리오: treasury
-- 자금 관리 페이지 플로우

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', datetime('now', '-30 days'),
        '20일 고점 돌파 시 매수', 'strategy-dev-01');
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('macd-cross', 'MACD 크로스', '1.0.0', 'strategies/macd_cross.py', 'active', datetime('now', '-14 days'),
        'MACD 골든/데드크로스 전략', 'strategy-dev-01');
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', datetime('now', '-21 days'),
        'RSI 과매도 반등 전략', 'strategy-dev-02');

-- ── 봇 3개 ──────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 봇', 'momentum-v2', 'live',
        '{"bot_id":"bot-momentum-01","strategy_id":"momentum-v2","name":"모멘텀 봇","bot_type":"live","interval_seconds":60}',
        'stopped', datetime('now', '-20 days'));

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-macd-cross', 'MACD 봇', 'macd-cross', 'live',
        '{"bot_id":"bot-macd-cross","strategy_id":"macd-cross","name":"MACD 봇","bot_type":"live","interval_seconds":60}',
        'running', datetime('now', '-12 days'));

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-01', 'RSI 봇', 'rsi-reversal', 'live',
        '{"bot_id":"bot-rsi-01","strategy_id":"rsi-reversal","name":"RSI 봇","bot_type":"live","interval_seconds":60}',
        'stopped', datetime('now', '-18 days'));

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 15000000.0, 8500000.0, 1500000.0, 5000000.0, 0.0);

INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-macd-cross', 10000000.0, 6200000.0, 800000.0, 3000000.0, 0.0);

INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-01', 10000000.0, 7300000.0, 700000.0, 2000000.0, 0.0);

-- ── Treasury 상태 ───────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 42000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 35000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 7000000.0);

-- ── 포지션 (봇별 보유종목) ──────────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 50, 72300.0, 0.0, datetime('now', '-1 days'));
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 15, 210000.0, 0.0, datetime('now', '-2 days'));

INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-macd-cross', '005930', 30, 73500.0, 0.0, datetime('now', '-1 days'));
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-macd-cross', '000660', 5, 155000.0, 0.0, datetime('now', '-3 days'));

INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '035720', 40, 52500.0, 0.0, datetime('now', '-2 days'));
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '005380', 8, 215000.0, 0.0, datetime('now', '-4 days'));

-- ── 자금 변동 이력 (24건 중 최신 8건) ───────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 15000000.0, '초기 할당', '2026-03-10 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3500000.0, '카카오 매수', '2026-03-10 10:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 800000.0, '카카오 매도', '2026-03-10 16:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'allocate', 12000000.0, '초기 할당', '2026-03-11 09:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'return', -2000000.0, '예산 축소', '2026-03-11 14:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'allocate', 10000000.0, '초기 할당', '2026-03-12 10:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -1200000.0, '삼성전자 매수', '2026-03-12 15:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 5000000.0, '추가 할당', '2026-03-13 09:00:00');

-- 과거 이력 16건 (페이지네이션 테스트용)
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-momentum-01', 'trade', -1500000.0, '삼성전자 매수', '2026-03-09 10:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-momentum-01', 'trade', -2000000.0, 'NAVER 매수', '2026-03-08 11:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-rsi-01', 'trade', -1000000.0, '카카오 매수', '2026-03-07 09:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-rsi-01', 'trade', -1000000.0, '현대차 매수', '2026-03-06 10:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-macd-cross', 'trade', -800000.0, 'SK하이닉스 매수', '2026-03-05 14:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-macd-cross', 'trade', -1000000.0, '삼성전자 매수', '2026-03-04 10:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-momentum-01', 'trade', 500000.0, '삼성전자 매도', '2026-03-03 15:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-rsi-01', 'trade', 350000.0, '카카오 매도', '2026-03-02 14:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-momentum-01', 'trade', -700000.0, 'NAVER 매수', '2026-03-01 11:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-macd-cross', 'trade', 200000.0, 'SK하이닉스 매도', '2026-02-28 15:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-rsi-01', 'trade', -500000.0, '현대차 추가 매수', '2026-02-27 10:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-momentum-01', 'trade', -800000.0, '카카오 매수', '2026-02-26 09:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-macd-cross', 'trade', -600000.0, '삼성전자 추가 매수', '2026-02-25 11:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-rsi-01', 'trade', 150000.0, '현대차 매도', '2026-02-24 14:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-momentum-01', 'allocate', 3000000.0, '예산 증액', '2026-02-23 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at) VALUES ('bot-macd-cross', 'allocate', 2000000.0, '예산 증액', '2026-02-22 09:00:00');

-- ── 에이전트 멤버 ───────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write"]', datetime('now', '-60 days'));
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write"]', datetime('now', '-45 days'));
