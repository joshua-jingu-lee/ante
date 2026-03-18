-- 시나리오: bot-management
-- 생성: generate_scenario.py (seed=123)
-- 생성일: 2026-03-18

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'active', '2026-02-01 09:00:00', 'SMA 5/20 크로스오버 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-01-17 09:00:00', '20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('mean-revert', '평균회귀', '1.2.0', 'strategies/mean_revert.py', 'active', '2026-02-01 09:00:00', '볼린저밴드 기반 평균회귀 전략', 'strategy-dev-02');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('broken-strategy', 'Broken Strategy', '0.1.0', 'strategies/broken.py', 'registered', '2026-03-04 09:00:00', '오류 테스트용 전략', 'seed');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-sma-01', 'SMA 크로스 봇', 'sma-cross', 'paper', '{"bot_id": "bot-sma-01", "strategy_id": "sma-cross", "name": "SMA 크로스 봇", "bot_type": "paper", "interval_seconds": 60, "symbols": ["005930"]}', 'created', '2026-03-11 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 추세 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-01", "strategy_id": "momentum-v2", "name": "모멘텀 추세 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "035420", "035720"]}', 'running', '2026-02-01 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-mean-01', '평균회귀 실전 봇', 'mean-revert', 'live', '{"bot_id": "bot-mean-01", "strategy_id": "mean-revert", "name": "평균회귀 실전 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "035420", "000660"]}', 'stopped', '2026-02-16 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-err-01', '오류 테스트 봇', 'broken-strategy', 'paper', '{"bot_id": "bot-err-01", "strategy_id": "broken-strategy", "name": "오류 테스트 봇", "bot_type": "paper", "interval_seconds": 60}', 'error', '2026-03-08 09:00:00');

-- ── 거래 내역 (84건) ────────────────────────
-- bot-momentum-01: 60건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0001', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72400, 'filled', 554, '2025-12-18 10:17:00', '2025-12-18 10:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0002', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 72500, 'filled', 555, '2025-12-19 10:24:00', '2025-12-19 10:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0003', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 213000, 'filled', 543, '2025-12-19 10:54:00', '2025-12-19 10:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0004', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 218500, 'filled', 557, '2025-12-22 14:21:00', '2025-12-22 14:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0005', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72800, 'filled', 557, '2025-12-22 09:57:00', '2025-12-22 09:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0006', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 69, 53800, 'filled', 557, '2025-12-23 09:00:00', '2025-12-23 09:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0007', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 72000, 'filled', 551, '2025-12-25 10:18:00', '2025-12-25 10:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0008', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 69, 53100, 'filled', 550, '2025-12-25 14:30:00', '2025-12-25 14:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0009', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 72000, 'filled', 562, '2025-12-25 10:21:00', '2025-12-25 10:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0010', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 73, 51100, 'filled', 560, '2025-12-26 09:25:00', '2025-12-26 09:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0011', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 215000, 'filled', 548, '2025-12-29 11:42:00', '2025-12-29 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0012', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 73, 51400, 'filled', 563, '2025-12-31 12:21:00', '2025-12-31 12:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0013', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 72, 51400, 'filled', 555, '2025-12-31 11:29:00', '2025-12-31 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0014', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 72, 50300, 'filled', 543, '2026-01-01 12:00:00', '2026-01-01 12:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0015', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 212000, 'filled', 541, '2026-01-02 10:40:00', '2026-01-02 10:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0016', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 76, 49000, 'filled', 559, '2026-01-02 11:46:00', '2026-01-02 11:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0017', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 74200, 'filled', 579, '2026-01-05 14:28:00', '2026-01-05 14:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0018', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 219000, 'filled', 558, '2026-01-05 09:00:00', '2026-01-05 09:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0019', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 76, 48000, 'filled', 547, '2026-01-06 12:43:00', '2026-01-06 12:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0020', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 78, 48000, 'filled', 562, '2026-01-06 11:26:00', '2026-01-06 11:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0021', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 217500, 'filled', 555, '2026-01-07 15:05:00', '2026-01-07 15:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0022', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 74600, 'filled', 560, '2026-01-07 11:24:00', '2026-01-07 11:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0023', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 78, 48600, 'filled', 569, '2026-01-08 12:16:00', '2026-01-08 12:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0024', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 74700, 'filled', 560, '2026-01-09 13:22:00', '2026-01-09 13:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0025', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 80, 46600, 'filled', 559, '2026-01-09 09:56:00', '2026-01-09 09:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0026', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 75200, 'filled', 553, '2026-01-12 10:42:00', '2026-01-12 10:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0027', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 223500, 'filled', 536, '2026-01-13 09:58:00', '2026-01-13 09:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0028', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 80, 48100, 'filled', 577, '2026-01-15 15:10:00', '2026-01-15 15:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0029', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 74700, 'filled', 549, '2026-01-15 13:27:00', '2026-01-15 13:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0030', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 74700, 'filled', 560, '2026-01-15 10:42:00', '2026-01-15 10:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0031', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 228000, 'filled', 547, '2026-01-19 10:10:00', '2026-01-19 10:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0032', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 76000, 'filled', 570, '2026-01-19 14:32:00', '2026-01-19 14:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0033', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-01-19 11:06:00', '2026-01-19 11:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0034', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 76, 48900, 'filled', 557, '2026-01-20 09:17:00', '2026-01-20 09:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0035', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 234500, 'filled', 563, '2026-01-22 11:32:00', '2026-01-22 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0036', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 76, 49800, 'filled', 568, '2026-01-22 10:12:00', '2026-01-22 10:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0037', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 75700, 'filled', 556, '2026-01-22 09:38:00', '2026-01-22 09:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0038', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 15, 235000, 'filled', 529, '2026-01-23 11:08:00', '2026-01-23 11:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0039', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 15, 226500, 'filled', 510, '2026-01-27 14:55:00', '2026-01-27 14:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0040', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 79, 47350, 'filled', 561, '2026-01-27 09:53:00', '2026-01-27 09:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0041', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 77000, 'filled', 566, '2026-01-29 15:37:00', '2026-01-29 15:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0042', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 48, 77000, 'filled', 554, '2026-01-29 10:55:00', '2026-01-29 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0043', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 79, 45950, 'filled', 545, '2026-02-02 11:52:00', '2026-02-02 11:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0044', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-02-02 10:24:00', '2026-02-02 10:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0045', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 48, 79300, 'filled', 571, '2026-02-03 14:24:00', '2026-02-03 14:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0046', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 82, 45200, 'filled', 556, '2026-02-03 09:58:00', '2026-02-03 09:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0047', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 47, 79400, 'filled', 560, '2026-02-04 09:37:00', '2026-02-04 09:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0048', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 231000, 'filled', 554, '2026-02-06 14:22:00', '2026-02-06 14:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0049', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 231000, 'filled', 554, '2026-02-06 11:36:00', '2026-02-06 11:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0050', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 47, 79400, 'filled', 560, '2026-02-09 10:27:00', '2026-02-09 10:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0051', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 47, 79400, 'filled', 560, '2026-02-09 10:34:00', '2026-02-09 10:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0052', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 82, 45100, 'filled', 555, '2026-02-10 11:38:00', '2026-02-10 11:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0053', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 228500, 'filled', 548, '2026-02-12 12:46:00', '2026-02-12 12:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0054', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 228500, 'filled', 548, '2026-02-12 10:18:00', '2026-02-12 10:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0055', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 47, 80800, 'filled', 570, '2026-02-13 14:00:00', '2026-02-13 14:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0056', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 46, 80800, 'filled', 558, '2026-02-13 09:02:00', '2026-02-13 09:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0057', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 223000, 'filled', 535, '2026-02-16 14:53:00', '2026-02-16 14:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0058', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 46, 79300, 'filled', 547, '2026-02-16 13:55:00', '2026-02-16 13:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0059', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 89, 42000, 'filled', 561, '2026-02-17 09:06:00', '2026-02-17 09:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0060', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 221000, 'filled', 530, '2026-02-18 09:33:00', '2026-02-18 09:33:00');

-- bot-mean-01: 24건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0001', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 154400, 'filled', 93, '2025-12-18 11:55:00', '2025-12-18 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0002', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 72400, 'filled', 109, '2025-12-19 10:46:00', '2025-12-19 10:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0003', 'bot-mean-01', 'mean-revert', '035420', 'buy', 3, 215500, 'filled', 97, '2025-12-22 09:29:00', '2025-12-22 09:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0004', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 153000, 'filled', 92, '2025-12-24 11:20:00', '2025-12-24 11:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0005', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 153000, 'filled', 92, '2025-12-24 09:19:00', '2025-12-24 09:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0006', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 70600, 'filled', 106, '2025-12-25 11:29:00', '2025-12-25 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0007', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 70600, 'filled', 106, '2025-12-25 09:28:00', '2025-12-25 09:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0008', 'bot-mean-01', 'mean-revert', '035420', 'sell', 3, 216000, 'filled', 97, '2025-12-29 12:53:00', '2025-12-29 12:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0009', 'bot-mean-01', 'mean-revert', '035420', 'buy', 3, 216000, 'filled', 97, '2025-12-29 11:29:00', '2025-12-29 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0010', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 161900, 'filled', 97, '2026-01-05 12:59:00', '2026-01-05 12:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0011', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 73300, 'filled', 110, '2026-01-05 14:36:00', '2026-01-05 14:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0012', 'bot-mean-01', 'mean-revert', '035420', 'sell', 3, 214500, 'filled', 97, '2026-01-05 14:32:00', '2026-01-05 14:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0013', 'bot-mean-01', 'mean-revert', '035420', 'buy', 3, 215000, 'filled', 97, '2026-01-06 09:35:00', '2026-01-06 09:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0014', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 73500, 'filled', 110, '2026-01-07 11:04:00', '2026-01-07 11:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0015', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 165700, 'filled', 99, '2026-01-08 11:18:00', '2026-01-08 11:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0016', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 165200, 'filled', 99, '2026-01-12 12:27:00', '2026-01-12 12:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0017', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 165200, 'filled', 99, '2026-01-12 10:27:00', '2026-01-12 10:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0018', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 74400, 'filled', 112, '2026-01-13 13:35:00', '2026-01-13 13:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0019', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 74400, 'filled', 112, '2026-01-14 10:16:00', '2026-01-14 10:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0020', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 157400, 'filled', 94, '2026-01-15 11:32:00', '2026-01-15 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0021', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 73000, 'filled', 109, '2026-01-19 12:14:00', '2026-01-19 12:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0022', 'bot-mean-01', 'mean-revert', '035420', 'sell', 3, 216000, 'filled', 97, '2026-01-21 13:07:00', '2026-01-21 13:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0023', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 156100, 'filled', 94, '2026-01-27 10:03:00', '2026-01-27 10:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0024', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 69400, 'filled', 104, '2026-01-28 09:11:00', '2026-01-28 09:11:00');

-- ── 포지션 이력 (84건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72400, 0.0, '2025-12-18 10:17:00', '2025-12-18 10:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 72500, -3959, '2025-12-19 10:24:00', '2025-12-19 10:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 213000, 0.0, '2025-12-19 10:54:00', '2025-12-19 10:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 218500, 84400, '2025-12-22 14:21:00', '2025-12-22 14:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72800, 0.0, '2025-12-22 09:57:00', '2025-12-22 09:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 69, 53800, 0.0, '2025-12-23 09:00:00', '2025-12-23 09:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 72000, -49797, '2025-12-25 10:18:00', '2025-12-25 10:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 69, 53100, -57277, '2025-12-25 14:30:00', '2025-12-25 14:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 72000, 0.0, '2025-12-25 10:21:00', '2025-12-25 10:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 73, 51100, 0.0, '2025-12-26 09:25:00', '2025-12-26 09:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 215000, 0.0, '2025-12-29 11:42:00', '2025-12-29 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 73, 51400, 12707, '2025-12-31 12:21:00', '2025-12-31 12:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 72, 51400, 0.0, '2025-12-31 11:29:00', '2025-12-31 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 72, 50300, -88073, '2026-01-01 12:00:00', '2026-01-01 12:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 212000, -59830, '2026-01-02 10:40:00', '2026-01-02 10:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 76, 49000, 0.0, '2026-01-02 11:46:00', '2026-01-02 11:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 74200, 104947, '2026-01-05 14:28:00', '2026-01-05 14:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 219000, 0.0, '2026-01-05 09:00:00', '2026-01-05 09:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 76, 48000, -84937, '2026-01-06 12:43:00', '2026-01-06 12:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 78, 48000, 0.0, '2026-01-06 11:26:00', '2026-01-06 11:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 217500, -34559, '2026-01-07 15:05:00', '2026-01-07 15:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 74600, 0.0, '2026-01-07 11:24:00', '2026-01-07 11:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 78, 48600, 37512, '2026-01-08 12:16:00', '2026-01-08 12:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 74700, -4150, '2026-01-09 13:22:00', '2026-01-09 13:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 80, 46600, 0.0, '2026-01-09 09:56:00', '2026-01-09 09:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 75200, 0.0, '2026-01-12 10:42:00', '2026-01-12 10:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 223500, 0.0, '2026-01-13 09:58:00', '2026-01-13 09:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 80, 48100, 110573, '2026-01-15 15:10:00', '2026-01-15 15:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 74700, -33468, '2026-01-15 13:27:00', '2026-01-15 13:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 74700, 0.0, '2026-01-15 10:42:00', '2026-01-15 10:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 228000, 63063, '2026-01-19 10:10:00', '2026-01-19 10:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 76000, 55690, '2026-01-19 14:32:00', '2026-01-19 14:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 228000, 0.0, '2026-01-19 11:06:00', '2026-01-19 11:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 76, 48900, 0.0, '2026-01-20 09:17:00', '2026-01-20 09:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 234500, 94807, '2026-01-22 11:32:00', '2026-01-22 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 76, 49800, 59127, '2026-01-22 10:12:00', '2026-01-22 10:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 75700, 0.0, '2026-01-22 09:38:00', '2026-01-22 09:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 15, 235000, 0.0, '2026-01-23 11:08:00', '2026-01-23 11:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 15, 226500, -135824, '2026-01-27 14:55:00', '2026-01-27 14:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 79, 47350, 0.0, '2026-01-27 09:53:00', '2026-01-27 09:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 77000, 54456, '2026-01-29 15:37:00', '2026-01-29 15:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 48, 77000, 0.0, '2026-01-29 10:55:00', '2026-01-29 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 79, 45950, -119494, '2026-02-02 11:52:00', '2026-02-02 11:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 228000, 0.0, '2026-02-02 10:24:00', '2026-02-02 10:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 48, 79300, 101074, '2026-02-03 14:24:00', '2026-02-03 14:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 82, 45200, 0.0, '2026-02-03 09:58:00', '2026-02-03 09:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 47, 79400, 0.0, '2026-02-04 09:37:00', '2026-02-04 09:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 231000, 38945, '2026-02-06 14:22:00', '2026-02-06 14:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 231000, 0.0, '2026-02-06 11:36:00', '2026-02-06 11:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 47, 79400, -9143, '2026-02-09 10:27:00', '2026-02-09 10:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 47, 79400, 0.0, '2026-02-09 10:34:00', '2026-02-09 10:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 82, 45100, -17261, '2026-02-10 11:38:00', '2026-02-10 11:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 228500, -48957, '2026-02-12 12:46:00', '2026-02-12 12:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 228500, 0.0, '2026-02-12 10:18:00', '2026-02-12 10:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 47, 80800, 56496, '2026-02-13 14:00:00', '2026-02-13 14:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 46, 80800, 0.0, '2026-02-13 09:02:00', '2026-02-13 09:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 223000, -96741, '2026-02-16 14:53:00', '2026-02-16 14:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 46, 79300, -77937, '2026-02-16 13:55:00', '2026-02-16 13:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 89, 42000, 0.0, '2026-02-17 09:06:00', '2026-02-17 09:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 221000, 0.0, '2026-02-18 09:33:00', '2026-02-18 09:33:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 154400, 0.0, '2025-12-18 11:55:00', '2025-12-18 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 72400, 0.0, '2025-12-19 10:46:00', '2025-12-19 10:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'buy', 3, 215500, 0.0, '2025-12-22 09:29:00', '2025-12-22 09:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 153000, -7100, '2025-12-24 11:20:00', '2025-12-24 11:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 153000, 0.0, '2025-12-24 09:19:00', '2025-12-24 09:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 70600, -19730, '2025-12-25 11:29:00', '2025-12-25 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 70600, 0.0, '2025-12-25 09:28:00', '2025-12-25 09:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'sell', 3, 216000, -87, '2025-12-29 12:53:00', '2025-12-29 12:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'buy', 3, 216000, 0.0, '2025-12-29 11:29:00', '2025-12-29 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 161900, 34014, '2026-01-05 12:59:00', '2026-01-05 12:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 73300, 25204, '2026-01-05 14:36:00', '2026-01-05 14:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'sell', 3, 214500, -6077, '2026-01-05 14:32:00', '2026-01-05 14:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'buy', 3, 215000, 0.0, '2026-01-06 09:35:00', '2026-01-06 09:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 73500, 0.0, '2026-01-07 11:04:00', '2026-01-07 11:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 165700, 0.0, '2026-01-08 11:18:00', '2026-01-08 11:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 165200, -3619, '2026-01-12 12:27:00', '2026-01-12 12:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 165200, 0.0, '2026-01-12 10:27:00', '2026-01-12 10:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 74400, 7177, '2026-01-13 13:35:00', '2026-01-13 13:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 74400, 0.0, '2026-01-14 10:16:00', '2026-01-14 10:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 157400, -32742, '2026-01-15 11:32:00', '2026-01-15 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 73000, -15788, '2026-01-19 12:14:00', '2026-01-19 12:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'sell', 3, 216000, 1413, '2026-01-21 13:07:00', '2026-01-21 13:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 156100, 0.0, '2026-01-27 10:03:00', '2026-01-27 10:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 69400, 0.0, '2026-01-28 09:11:00', '2026-01-28 09:11:00');

-- ── 최종 포지션 (6건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035720', 89, 42000, 0.0, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 16, 221000, 0.0, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 0, 0.0, 194209, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '000660', 4, 156100, 0.0, '2026-01-28 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '005930', 10, 69400, 0.0, '2026-01-28 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '035420', 0, 0.0, -4751, '2026-01-28 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-sma-01', 1000000, 1000000, 0.0, 0.0, 0.0);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 15000000, 387229, 0.0, 114426611, 107087840);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-mean-01', 3000000, 344556, 0.0, 8721409, 7384365);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-err-01', 500000, 500000, 0.0, 0.0, 0.0);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 100000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 19500000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 80500000);

-- ── 자금 변동 이력 (88건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 15000000, '초기 할당', '2025-12-18 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'allocate', 3000000, '초기 할당', '2025-12-18 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3692954, '삼성전자 51주 매수', '2025-12-18 10:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -617693, 'SK하이닉스 4주 매수', '2025-12-18 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3696945, '삼성전자 51주 매도', '2025-12-19 10:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -724109, '삼성전자 10주 매수', '2025-12-19 10:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3621543, 'NAVER 17주 매수', '2025-12-19 10:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -646597, 'NAVER 3주 매수', '2025-12-22 09:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3713357, '삼성전자 51주 매수', '2025-12-22 09:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3713943, 'NAVER 17주 매도', '2025-12-22 14:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3712757, '카카오 69주 매수', '2025-12-23 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -612092, 'SK하이닉스 4주 매수', '2025-12-24 09:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 611908, 'SK하이닉스 4주 매도', '2025-12-24 11:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -706106, '삼성전자 10주 매수', '2025-12-25 09:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3671449, '삼성전자 51주 매도', '2025-12-25 10:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3744562, '삼성전자 52주 매수', '2025-12-25 10:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 705894, '삼성전자 10주 매도', '2025-12-25 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3663350, '카카오 69주 매도', '2025-12-25 14:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3730860, '카카오 73주 매수', '2025-12-26 09:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -648097, 'NAVER 3주 매수', '2025-12-29 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3655548, 'NAVER 17주 매수', '2025-12-29 11:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 647903, 'NAVER 3주 매도', '2025-12-29 12:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3701355, '카카오 72주 매수', '2025-12-31 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3751637, '카카오 73주 매도', '2025-12-31 12:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3621057, '카카오 72주 매도', '2026-01-01 12:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3603459, 'NAVER 17주 매도', '2026-01-02 10:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3724559, '카카오 76주 매수', '2026-01-02 11:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3723558, 'NAVER 17주 매수', '2026-01-05 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 647503, 'SK하이닉스 4주 매도', '2026-01-05 12:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3857821, '삼성전자 52주 매도', '2026-01-05 14:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 643403, 'NAVER 3주 매도', '2026-01-05 14:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 732890, '삼성전자 10주 매도', '2026-01-05 14:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -645097, 'NAVER 3주 매수', '2026-01-06 09:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3744562, '카카오 78주 매수', '2026-01-06 11:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3647453, '카카오 76주 매도', '2026-01-06 12:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -735110, '삼성전자 10주 매수', '2026-01-07 11:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3730560, '삼성전자 50주 매수', '2026-01-07 11:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3696945, 'NAVER 17주 매도', '2026-01-07 15:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -662899, 'SK하이닉스 4주 매수', '2026-01-08 11:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3790231, '카카오 78주 매도', '2026-01-08 12:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3728559, '카카오 80주 매수', '2026-01-09 09:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3734440, '삼성전자 50주 매도', '2026-01-09 13:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -660899, 'SK하이닉스 4주 매수', '2026-01-12 10:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3685353, '삼성전자 49주 매수', '2026-01-12 10:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 660701, 'SK하이닉스 4주 매도', '2026-01-12 12:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3576536, 'NAVER 16주 매수', '2026-01-13 09:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 743888, '삼성전자 10주 매도', '2026-01-13 13:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -744112, '삼성전자 10주 매수', '2026-01-14 10:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3735560, '삼성전자 50주 매수', '2026-01-15 10:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 629506, 'SK하이닉스 4주 매도', '2026-01-15 11:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3659751, '삼성전자 49주 매도', '2026-01-15 13:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3847423, '카카오 80주 매도', '2026-01-15 15:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3647453, 'NAVER 16주 매도', '2026-01-19 10:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3648547, 'NAVER 16주 매수', '2026-01-19 11:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 729891, '삼성전자 10주 매도', '2026-01-19 12:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3799430, '삼성전자 50주 매도', '2026-01-19 14:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-sma-01', 'allocate', 1000000, '초기 할당', '2026-01-20 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-err-01', 'allocate', 500000, '초기 할당', '2026-01-20 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3716957, '카카오 76주 매수', '2026-01-20 09:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 647903, 'NAVER 3주 매도', '2026-01-21 13:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3709856, '삼성전자 49주 매수', '2026-01-22 09:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3784232, '카카오 76주 매도', '2026-01-22 10:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3751437, 'NAVER 16주 매도', '2026-01-22 11:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3525529, 'NAVER 15주 매수', '2026-01-23 11:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3741211, '카카오 79주 매수', '2026-01-27 09:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -624494, 'SK하이닉스 4주 매수', '2026-01-27 10:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3396990, 'NAVER 15주 매도', '2026-01-27 14:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -694104, '삼성전자 10주 매수', '2026-01-28 09:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3696554, '삼성전자 48주 매수', '2026-01-29 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3772434, '삼성전자 49주 매도', '2026-01-29 15:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3648547, 'NAVER 16주 매수', '2026-02-02 10:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3629505, '카카오 79주 매도', '2026-02-02 11:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3706956, '카카오 82주 매수', '2026-02-03 09:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3805829, '삼성전자 48주 매도', '2026-02-03 14:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3732360, '삼성전자 47주 매수', '2026-02-04 09:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3696554, 'NAVER 16주 매수', '2026-02-06 11:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3695446, 'NAVER 16주 매도', '2026-02-06 14:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3731240, '삼성전자 47주 매도', '2026-02-09 10:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3732360, '삼성전자 47주 매수', '2026-02-09 10:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3697645, '카카오 82주 매도', '2026-02-10 11:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3656548, 'NAVER 16주 매수', '2026-02-12 10:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3655452, 'NAVER 16주 매도', '2026-02-12 12:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3717358, '삼성전자 46주 매수', '2026-02-13 09:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3797030, '삼성전자 47주 매도', '2026-02-13 14:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3647253, '삼성전자 46주 매도', '2026-02-16 13:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3567465, 'NAVER 16주 매도', '2026-02-16 14:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3738561, '카카오 89주 매수', '2026-02-17 09:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3536530, 'NAVER 16주 매수', '2026-02-18 09:33:00');

-- ── 이벤트 로그 (20건) ──────────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-001', 'bot.step.success', '2025-12-18 10:17:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-002', 'bot.step.success', '2025-12-23 09:00:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-003', 'bot.step.success', '2025-12-29 11:42:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-004', 'bot.step.success', '2026-01-02 11:46:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-005', 'bot.step.success', '2026-01-07 15:05:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-006', 'bot.step.success', '2026-01-12 10:42:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-007', 'bot.step.success', '2026-01-19 10:10:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-008', 'bot.step.success', '2026-01-22 10:12:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-009', 'bot.step.success', '2026-01-29 15:37:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-010', 'bot.step.success', '2026-02-03 09:58:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-011', 'bot.step.success', '2026-02-09 10:34:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-012', 'bot.step.success', '2026-02-13 09:02:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-001', 'bot.step.success', '2025-12-18 11:55:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-002', 'bot.step.success', '2025-12-25 11:29:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-003', 'bot.step.success', '2026-01-05 14:36:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-004', 'bot.step.success', '2026-01-12 12:27:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-005', 'bot.step.success', '2026-01-19 12:14:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-006', 'bot.stopped', '2026-03-17 15:00:00', '{"bot_id": "bot-mean-01", "message": "Bot 중지됨 — 사용자 요청"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-err--001', 'bot.step.error', '2026-03-15 10:00:00', '{"bot_id": "bot-err-01", "message": "전략 로드 실패: ModuleNotFoundError"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-err--002', 'bot.step.error', '2026-03-15 10:00:00', '{"bot_id": "bot-err-01", "message": "전략 초기화 실패: invalid config"}');

-- ── 멤버 ────────────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write", "data:read", "backtest:run", "report:write"]', 'datetime(''now'', ''-60 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write", "data:read", "backtest:run"]', 'datetime(''now'', ''-45 days'')');
