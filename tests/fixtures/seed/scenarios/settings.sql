-- 시나리오: settings
-- 설정 페이지 플로우

-- ── 동적 설정 (10개) ────────────────────────────────
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('risk.max_mdd_pct', '15.0', 'risk', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('risk.max_position_pct', '30.0', 'risk', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('rule.daily_loss_limit', '5.0', 'rule', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('rule.max_exposure_percent', '20.0', 'rule', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('rule.max_unrealized_loss', '10.0', 'rule', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('rule.max_trades_per_hour', '10', 'rule', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('rule.allowed_hours', '09:00-15:30', 'rule', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('bot.default_interval_sec', '60', 'bot', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('broker.commission_rate', '0.015', 'broker', datetime('now', '-7 days'));
INSERT INTO dynamic_config (key, value, category, updated_at) VALUES ('broker.sell_tax_rate', '0.23', 'broker', datetime('now', '-7 days'));

-- ── 설정 변경 이력 ──────────────────────────────────
INSERT INTO dynamic_config_history (key, old_value, new_value, changed_by, changed_at)
VALUES ('risk.max_mdd_pct', '20.0', '15.0', 'owner', datetime('now', '-7 days'));
INSERT INTO dynamic_config_history (key, old_value, new_value, changed_by, changed_at)
VALUES ('rule.max_trades_per_hour', '5', '10', 'owner', datetime('now', '-14 days'));

-- ── 자금 (최소) ─────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('total_cash', 50000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 0.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 50000000.0);
