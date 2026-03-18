-- 시나리오: bot-management
-- 봇 생성/시작/중지/삭제 및 상세 정보 플로우

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'active', datetime('now', '-14 days'),
        'SMA 5/20 크로스오버 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', datetime('now', '-30 days'),
        '20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('mean-revert', '평균회귀', '1.2.0', 'strategies/mean_revert.py', 'active', datetime('now', '-21 days'),
        '볼린저밴드 기반 평균회귀 전략', 'strategy-dev-02');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('broken-strategy', 'Broken Strategy', '0.1.0', 'strategies/broken.py', 'registered', datetime('now', '-7 days'),
        '오류 테스트용 전략', 'seed');

-- ── 봇 A: created (paper) ───────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-sma-01', 'SMA 크로스 봇', 'sma-cross', 'paper',
        '{"bot_id":"bot-sma-01","strategy_id":"sma-cross","name":"SMA 크로스 봇","bot_type":"paper","interval_seconds":60,"symbols":["005930"]}',
        'created', datetime('now', '-3 days'));

-- ── 봇 B: running (live) ───────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 추세 봇', 'momentum-v2', 'live',
        '{"bot_id":"bot-momentum-01","strategy_id":"momentum-v2","name":"모멘텀 추세 봇","bot_type":"live","interval_seconds":60}',
        'running', datetime('now', '-10 days'));

-- ── 봇 C: stopped (live) ───────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-mean-01', '평균회귀 실전 봇', 'mean-revert', 'live',
        '{"bot_id":"bot-mean-01","strategy_id":"mean-revert","name":"평균회귀 실전 봇","bot_type":"live","interval_seconds":120}',
        'stopped', datetime('now', '-14 days'));

-- ── 봇 D: error (paper) ────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-err-01', '오류 테스트 봇', 'broken-strategy', 'paper',
        '{"bot_id":"bot-err-01","strategy_id":"broken-strategy","name":"오류 테스트 봇","bot_type":"paper","interval_seconds":60,"symbols":[]}',
        'error', datetime('now', '-5 days'));

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-sma-01', 1000000.0, 1000000.0, 0.0, 0.0, 0.0);

INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 15000000.0, 8500000.0, 1500000.0, 5000000.0, 0.0);

INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-mean-01', 3000000.0, 1500000.0, 0.0, 1500000.0, 0.0);

INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-err-01', 500000.0, 500000.0, 0.0, 0.0, 0.0);

-- ── 포지션: 봇 B (running) ─────────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 50, 72300.0, 0.0, datetime('now', '-1 hours'));

INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 15, 210000.0, 0.0, datetime('now', '-2 hours'));

INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035720', 0, 0.0, 45000.0, datetime('now', '-3 days'));

-- ── 포지션: 봇 C (stopped, 3종목) ──────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '005930', 20, 73000.0, 0.0, datetime('now', '-2 days'));

INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '035420', 5, 215000.0, 0.0, datetime('now', '-3 days'));

INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '000660', 10, 155000.0, 0.0, datetime('now', '-4 days'));

-- ── 실행 로그: 봇 B (성공 9, 실패 1) ───────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-01', 'bot.step.success', datetime('now', '-9 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-02', 'bot.step.success', datetime('now', '-8 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-03', 'bot.step.success', datetime('now', '-7 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-04', 'bot.step.success', datetime('now', '-6 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-05', 'bot.step.success', datetime('now', '-5 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-06', 'bot.step.success', datetime('now', '-4 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-07', 'bot.step.success', datetime('now', '-3 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-08', 'bot.step.success', datetime('now', '-2 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-09', 'bot.step.success', datetime('now', '-1 hours'), '{"bot_id":"bot-momentum-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bm-10', 'bot.step.error', datetime('now', '-30 minutes'), '{"bot_id":"bot-momentum-01","message":"브로커 연결 실패: timeout"}');

-- ── 실행 로그: 봇 C (성공 5, 중지 1) ───────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bc-01', 'bot.step.success', datetime('now', '-5 days'), '{"bot_id":"bot-mean-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bc-02', 'bot.step.success', datetime('now', '-4 days'), '{"bot_id":"bot-mean-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bc-03', 'bot.step.success', datetime('now', '-3 days'), '{"bot_id":"bot-mean-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bc-04', 'bot.step.success', datetime('now', '-2 days'), '{"bot_id":"bot-mean-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bc-05', 'bot.step.success', datetime('now', '-1 days'), '{"bot_id":"bot-mean-01","message":"매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bc-06', 'bot.stopped', datetime('now', '-12 hours'), '{"bot_id":"bot-mean-01","message":"Bot 중지됨 — 사용자 요청"}');

-- ── 실행 로그: 봇 D (실패 2) ────────────────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bd-01', 'bot.step.error', datetime('now', '-4 days'), '{"bot_id":"bot-err-01","message":"전략 로드 실패: ModuleNotFoundError"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload) VALUES ('ev-bd-02', 'bot.step.error', datetime('now', '-3 days'), '{"bot_id":"bot-err-01","message":"전략 초기화 실패: invalid config"}');

-- ── 자금 ────────────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 100000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 19500000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 80500000.0);

-- ── 에이전트 멤버 ───────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write","data:read"]', datetime('now', '-60 days'));
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write","data:read"]', datetime('now', '-45 days'));
