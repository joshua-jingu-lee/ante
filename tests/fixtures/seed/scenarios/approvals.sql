-- 시나리오: approvals
-- 결재함 플로우

-- ── 에이전트 멤버 (요청자) ──────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, last_active_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active',
        '["strategy:write","data:read","backtest:run","report:write"]',
        datetime('now', '-60 days'), '2026-03-13 09:30:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, last_active_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active',
        '["strategy:write","data:read","backtest:run"]',
        datetime('now', '-45 days'), '2026-03-12 17:45:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, last_active_at)
VALUES ('risk-monitor', 'agent', 'default', 'risk', '리스크 감시', '🦉', 'active',
        '["bot:read","data:read","approval:review"]',
        datetime('now', '-50 days'), '2026-03-13 09:15:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, last_active_at)
VALUES ('treasury-agent', 'agent', 'default', 'treasury', '자금 관리', '🐳', 'active',
        '["approval:create","data:read"]',
        datetime('now', '-40 days'), '2026-03-13 08:15:00');

-- ── 결재 요청 6건 ───────────────────────────────────
-- [대기] 전략 채택
INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES ('appr-01', 'strategy_adopt', 'pending', 'strategy-dev-01',
        '모멘텀 돌파 전략 v2 채택 요청',
        '백테스트 2년 수익률 35.2%, 샤프비율 1.45로 양호합니다. 실전 투입을 요청합니다.',
        '{"strategy_id":"momentum-v2","version":"2.1.0"}',
        '2026-03-13 09:30:00', '2026-03-16 09:30:00');

-- [대기] 예산 변경
INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES ('appr-02', 'budget_change', 'pending', 'treasury-agent',
        'bot-momentum-01 예산 1,000만원→2,500만원 증액 요청',
        '모멘텀 봇의 운용 성과가 양호하여 예산 증액을 요청합니다. 현재 수익률 +3.5%.',
        '{"bot_id":"bot-momentum-01","current":10000000,"requested":25000000}',
        '2026-03-13 08:15:00', '2026-03-16 08:15:00');

-- [대기] 봇 생성
INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES ('appr-03', 'bot_create', 'pending', 'strategy-dev-02',
        'RSI 역추세 전략 봇 신규 생성 요청',
        'RSI 역추세 전략 백테스트 완료. 모의투자 봇 생성을 요청합니다.',
        '{"strategy_id":"rsi-reversal","bot_type":"paper","budget":5000000}',
        '2026-03-12 17:45:00', '2026-03-15 17:45:00');

-- [승인] 전략 채택
INSERT INTO approvals (id, type, status, requester, title, body, params, reviews, created_at, resolved_at, resolved_by)
VALUES ('appr-04', 'strategy_adopt', 'approved', 'strategy-dev-01',
        'MACD 크로스 전략 v1 채택 요청',
        'MACD 골든/데드크로스 전략 백테스트 결과 양호합니다.',
        '{"strategy_id":"macd-cross","version":"1.0.0"}',
        '[{"reviewer":"owner","action":"approve","comment":"승인합니다.","timestamp":"2026-03-11 15:30:00"}]',
        '2026-03-11 10:00:00', '2026-03-11 15:30:00', 'owner');

-- [승인] 봇 중지
INSERT INTO approvals (id, type, status, requester, title, body, params, reviews, created_at, resolved_at, resolved_by)
VALUES ('appr-05', 'bot_stop', 'approved', 'risk-monitor',
        'bot-rsi-01 손실 누적 중지 요청',
        '최근 5일 연속 손실, 누적 손실률 -4.2%. 리스크 관리 차원에서 중지를 요청합니다.',
        '{"bot_id":"bot-rsi-01","reason":"consecutive_loss"}',
        '[{"reviewer":"owner","action":"approve","comment":"중지 승인. 전략 재검토 필요.","timestamp":"2026-03-10 11:15:00"}]',
        '2026-03-10 09:30:00', '2026-03-10 11:15:00', 'owner');

-- [거부] 규칙 변경
INSERT INTO approvals (id, type, status, requester, title, body, params, reviews, created_at, resolved_at, resolved_by, reject_reason)
VALUES ('appr-06', 'rule_change', 'rejected', 'strategy-dev-01',
        'bot-rsi-01 종목당 최대 비중 20%→35% 변경 요청',
        '모멘텀이 강한 종목에 집중 투자하기 위해 비중 한도 상향을 요청합니다.',
        '{"key":"risk.max_position_pct","current":"20","requested":"35"}',
        '[{"reviewer":"owner","action":"reject","comment":"리스크 한도 초과. 30% 이내로 재요청하세요.","timestamp":"2026-03-09 11:45:00"}]',
        '2026-03-09 09:00:00', '2026-03-09 11:45:00', 'owner',
        '리스크 한도 초과. 30% 이내로 재요청하세요.');

-- ── 감사 로그 (결재 관련) ───────────────────────────
INSERT INTO audit_log (member_id, action, resource, detail, created_at)
VALUES ('owner', 'approval.approve', 'appr-04', 'MACD 크로스 전략 v1 채택 승인', '2026-03-11 15:30:00');
INSERT INTO audit_log (member_id, action, resource, detail, created_at)
VALUES ('owner', 'approval.approve', 'appr-05', 'bot-rsi-01 중지 승인', '2026-03-10 11:15:00');
INSERT INTO audit_log (member_id, action, resource, detail, created_at)
VALUES ('owner', 'approval.reject', 'appr-06', '비중 변경 거부', '2026-03-09 11:45:00');

-- ── 자금 (최소) ─────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 50000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 10000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 40000000.0);

-- ── 전략/봇 (결재 참조용) ───────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', datetime('now', '-30 days'),
        '20일 고점 돌파 시 매수', 'strategy-dev-01');
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('macd-cross', 'MACD 크로스', '1.0.0', 'strategies/macd_cross.py', 'active', datetime('now', '-14 days'),
        'MACD 골든/데드크로스 전략', 'strategy-dev-01');
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'registered', datetime('now', '-10 days'),
        'RSI 과매도 반등 전략', 'strategy-dev-02');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 봇', 'momentum-v2', 'live',
        '{"bot_id":"bot-momentum-01","strategy_id":"momentum-v2","name":"모멘텀 봇","bot_type":"live","interval_seconds":60}',
        'running', datetime('now', '-20 days'));

INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 10000000.0, 7000000.0, 0.0, 3000000.0, 0.0);
