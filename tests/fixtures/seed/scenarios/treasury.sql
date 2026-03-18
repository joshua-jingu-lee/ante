-- 시나리오: treasury
-- 생성: generate_scenario.py (seed=456)
-- 생성일: 2026-03-18

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-01-17 09:00:00', '20일 고점 돌파 시 매수', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('macd-cross', 'MACD 크로스', '1.0.0', 'strategies/macd_cross.py', 'active', '2026-02-16 09:00:00', 'MACD 골든/데드크로스 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', '2026-02-01 09:00:00', 'RSI 과매도 반등 전략', 'strategy-dev-02');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-01", "strategy_id": "momentum-v2", "name": "모멘텀 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "035420"]}', 'running', '2026-01-27 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-macd-cross', 'MACD 봇', 'macd-cross', 'live', '{"bot_id": "bot-macd-cross", "strategy_id": "macd-cross", "name": "MACD 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "000660"]}', 'running', '2026-02-16 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-01', 'RSI 봇', 'rsi-reversal', 'live', '{"bot_id": "bot-rsi-01", "strategy_id": "rsi-reversal", "name": "RSI 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["035720", "005380"]}', 'stopped', '2026-02-06 09:00:00');

-- ── 거래 내역 (102건) ────────────────────────
-- bot-momentum-01: 54건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0001', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 53, 70400, 'filled', 560, '2025-12-22 11:46:00', '2025-12-22 11:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0002', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 19, 194500, 'filled', 554, '2025-12-24 09:30:00', '2025-12-24 09:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0003', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 53, 72600, 'filled', 577, '2025-12-30 12:04:00', '2025-12-30 12:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0004', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 19, 197600, 'filled', 563, '2025-12-30 10:23:00', '2025-12-30 10:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0005', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 199600, 'filled', 539, '2025-12-31 11:55:00', '2025-12-31 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0006', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 71400, 'filled', 557, '2026-01-01 09:28:00', '2026-01-01 09:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0007', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 201500, 'filled', 544, '2026-01-02 10:20:00', '2026-01-02 10:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0008', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 72000, 'filled', 562, '2026-01-05 14:44:00', '2026-01-05 14:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0009', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 72000, 'filled', 562, '2026-01-05 10:31:00', '2026-01-05 10:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0010', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 199300, 'filled', 538, '2026-01-06 11:02:00', '2026-01-06 11:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0011', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 71500, 'filled', 558, '2026-01-08 11:17:00', '2026-01-08 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0012', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 71500, 'filled', 558, '2026-01-08 11:48:00', '2026-01-08 11:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0013', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 202000, 'filled', 545, '2026-01-09 11:57:00', '2026-01-09 11:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0014', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 202000, 'filled', 545, '2026-01-09 10:33:00', '2026-01-09 10:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0015', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 203000, 'filled', 548, '2026-01-12 10:00:00', '2026-01-12 10:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0016', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 203000, 'filled', 548, '2026-01-12 11:54:00', '2026-01-12 11:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0017', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 206000, 'filled', 556, '2026-01-15 13:43:00', '2026-01-15 13:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0018', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 206000, 'filled', 556, '2026-01-15 09:35:00', '2026-01-15 09:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0019', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 69900, 'filled', 545, '2026-01-16 11:46:00', '2026-01-16 11:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0020', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 53, 69900, 'filled', 556, '2026-01-16 10:19:00', '2026-01-16 10:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0021', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 214500, 'filled', 579, '2026-01-20 14:18:00', '2026-01-20 14:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0022', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 214500, 'filled', 547, '2026-01-20 11:50:00', '2026-01-20 11:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0023', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 53, 72300, 'filled', 575, '2026-01-23 15:52:00', '2026-01-23 15:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0024', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72300, 'filled', 553, '2026-01-23 10:01:00', '2026-01-23 10:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0025', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 213500, 'filled', 544, '2026-01-26 11:29:00', '2026-01-26 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0026', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 210000, 'filled', 536, '2026-01-27 09:04:00', '2026-01-27 09:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0027', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 73100, 'filled', 559, '2026-01-28 13:20:00', '2026-01-28 13:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0028', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 209500, 'filled', 534, '2026-01-28 10:17:00', '2026-01-28 10:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0029', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 73100, 'filled', 559, '2026-01-28 09:43:00', '2026-01-28 09:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0030', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 72100, 'filled', 552, '2026-01-29 11:12:00', '2026-01-29 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0031', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 72100, 'filled', 562, '2026-01-29 11:03:00', '2026-01-29 11:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0032', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 207000, 'filled', 559, '2026-02-02 09:48:00', '2026-02-02 09:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0033', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 73700, 'filled', 575, '2026-02-06 13:55:00', '2026-02-06 13:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0034', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 210500, 'filled', 568, '2026-02-09 15:01:00', '2026-02-09 15:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0035', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 206000, 'filled', 556, '2026-02-10 09:24:00', '2026-02-10 09:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0036', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 75300, 'filled', 553, '2026-02-11 10:37:00', '2026-02-11 10:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0037', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 193900, 'filled', 524, '2026-02-16 13:38:00', '2026-02-16 13:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0038', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 19, 193900, 'filled', 553, '2026-02-16 10:17:00', '2026-02-16 10:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0039', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 76700, 'filled', 564, '2026-02-17 15:20:00', '2026-02-17 15:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0040', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 19, 186600, 'filled', 532, '2026-02-18 10:58:00', '2026-02-18 10:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0041', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 20, 186600, 'filled', 560, '2026-02-18 11:36:00', '2026-02-18 11:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0042', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 20, 179800, 'filled', 539, '2026-02-19 12:50:00', '2026-02-19 12:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0043', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 73700, 'filled', 553, '2026-02-19 09:08:00', '2026-02-19 09:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0044', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 21, 175800, 'filled', 554, '2026-02-20 11:31:00', '2026-02-20 11:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0045', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 73600, 'filled', 552, '2026-02-23 12:34:00', '2026-02-23 12:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0046', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 21, 173900, 'filled', 548, '2026-02-23 11:19:00', '2026-02-23 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0047', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 73600, 'filled', 552, '2026-02-23 11:26:00', '2026-02-23 11:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0048', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 21, 174900, 'filled', 551, '2026-02-24 11:36:00', '2026-02-24 11:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0049', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 72300, 'filled', 542, '2026-02-26 12:42:00', '2026-02-26 12:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0050', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 21, 170900, 'filled', 538, '2026-02-27 11:15:00', '2026-02-27 11:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0051', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 75800, 'filled', 557, '2026-03-03 11:35:00', '2026-03-03 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0052', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 77300, 'filled', 568, '2026-03-06 14:44:00', '2026-03-06 14:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0053', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 21, 170600, 'filled', 537, '2026-03-09 09:00:00', '2026-03-09 09:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0054', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 76100, 'filled', 559, '2026-03-10 09:51:00', '2026-03-10 09:51:00');

-- bot-macd-cross: 23건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0001', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 158200, 'filled', 356, '2025-12-22 10:50:00', '2025-12-22 10:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0002', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 35, 70300, 'filled', 369, '2025-12-29 11:12:00', '2025-12-29 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0003', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 163000, 'filled', 367, '2025-12-31 14:51:00', '2025-12-31 14:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0004', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 14, 168300, 'filled', 353, '2026-01-02 11:51:00', '2026-01-02 11:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0005', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 14, 163500, 'filled', 343, '2026-01-05 10:43:00', '2026-01-05 10:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0006', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 163500, 'filled', 368, '2026-01-05 10:43:00', '2026-01-05 10:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0007', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 35, 72200, 'filled', 379, '2026-01-06 13:39:00', '2026-01-06 13:39:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0008', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 34, 72200, 'filled', 368, '2026-01-06 11:02:00', '2026-01-06 11:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0009', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 171700, 'filled', 386, '2026-01-13 14:15:00', '2026-01-13 14:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0010', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 34, 75400, 'filled', 385, '2026-01-13 10:23:00', '2026-01-13 10:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0011', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 14, 173700, 'filled', 365, '2026-01-14 10:48:00', '2026-01-14 10:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0012', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 32, 76800, 'filled', 369, '2026-01-15 11:19:00', '2026-01-15 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0013', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 14, 162500, 'filled', 341, '2026-01-22 14:02:00', '2026-01-22 14:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0014', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 32, 78500, 'filled', 377, '2026-01-23 15:14:00', '2026-01-23 15:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0015', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 31, 78500, 'filled', 365, '2026-01-23 11:28:00', '2026-01-23 11:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0016', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 164900, 'filled', 371, '2026-01-28 10:15:00', '2026-01-28 10:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0017', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 31, 78600, 'filled', 365, '2026-02-05 14:40:00', '2026-02-05 14:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0018', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 161200, 'filled', 363, '2026-02-05 15:23:00', '2026-02-05 15:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0019', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 31, 78600, 'filled', 365, '2026-02-05 11:41:00', '2026-02-05 11:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0020', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 162800, 'filled', 366, '2026-02-11 11:25:00', '2026-02-11 11:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0021', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 31, 80400, 'filled', 374, '2026-02-12 15:31:00', '2026-02-12 15:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0022', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 31, 80400, 'filled', 374, '2026-02-12 11:32:00', '2026-02-12 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-macd-0023', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 31, 80600, 'filled', 375, '2026-02-16 13:57:00', '2026-02-16 13:57:00');

-- bot-rsi-01: 25건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0001', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 208000, 'filled', 374, '2025-12-19 11:55:00', '2025-12-19 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0002', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 51, 48550, 'filled', 371, '2025-12-22 10:56:00', '2025-12-22 10:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0003', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 204000, 'filled', 367, '2025-12-25 11:56:00', '2025-12-25 11:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0004', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 204000, 'filled', 367, '2025-12-25 09:27:00', '2025-12-25 09:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0005', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 51, 46200, 'filled', 353, '2025-12-31 13:30:00', '2025-12-31 13:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0006', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 54, 46200, 'filled', 374, '2025-12-31 10:22:00', '2025-12-31 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0007', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 212000, 'filled', 382, '2026-01-05 11:39:00', '2026-01-05 11:39:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0008', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 11, 212000, 'filled', 350, '2026-01-05 11:12:00', '2026-01-05 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0009', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 54, 48150, 'filled', 390, '2026-01-08 15:58:00', '2026-01-08 15:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0010', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 52, 48050, 'filled', 375, '2026-01-09 09:02:00', '2026-01-09 09:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0011', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 11, 211000, 'filled', 348, '2026-01-12 12:00:00', '2026-01-12 12:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0012', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 52, 47250, 'filled', 369, '2026-01-12 14:37:00', '2026-01-12 14:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0013', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 53, 46700, 'filled', 371, '2026-01-15 09:16:00', '2026-01-15 09:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0014', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 53, 48050, 'filled', 382, '2026-01-19 12:11:00', '2026-01-19 12:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0015', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 11, 214500, 'filled', 354, '2026-01-19 09:30:00', '2026-01-19 09:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0016', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 52, 47550, 'filled', 371, '2026-01-21 10:08:00', '2026-01-21 10:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0017', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 11, 204500, 'filled', 337, '2026-01-26 10:20:00', '2026-01-26 10:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0018', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 206500, 'filled', 372, '2026-01-28 11:28:00', '2026-01-28 11:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0019', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 202000, 'filled', 364, '2026-01-30 14:06:00', '2026-01-30 14:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0020', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 202000, 'filled', 364, '2026-01-30 09:49:00', '2026-01-30 09:49:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0021', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 52, 45550, 'filled', 355, '2026-02-04 14:32:00', '2026-02-04 14:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0022', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 54, 45550, 'filled', 369, '2026-02-04 09:31:00', '2026-02-04 09:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0023', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 194000, 'filled', 349, '2026-02-09 14:17:00', '2026-02-09 14:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0024', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 54, 45500, 'filled', 369, '2026-02-09 12:10:00', '2026-02-09 12:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0025', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 56, 44000, 'filled', 370, '2026-02-17 09:46:00', '2026-02-17 09:46:00');

-- ── 포지션 이력 (102건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 53, 70400, 0.0, '2025-12-22 11:46:00', '2025-12-22 11:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 19, 194500, 0.0, '2025-12-24 09:30:00', '2025-12-24 09:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 53, 72600, 107173, '2025-12-30 12:04:00', '2025-12-30 12:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 19, 197600, 49702, '2025-12-30 10:23:00', '2025-12-30 10:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 199600, 0.0, '2025-12-31 11:55:00', '2025-12-31 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 71400, 0.0, '2026-01-01 09:28:00', '2026-01-01 09:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 201500, 25314, '2026-01-02 10:20:00', '2026-01-02 10:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 72000, 22027, '2026-01-05 14:44:00', '2026-01-05 14:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 72000, 0.0, '2026-01-05 10:31:00', '2026-01-05 10:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 199300, 0.0, '2026-01-06 11:02:00', '2026-01-06 11:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 71500, -35109, '2026-01-08 11:17:00', '2026-01-08 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 71500, 0.0, '2026-01-08 11:48:00', '2026-01-08 11:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 202000, 39692, '2026-01-09 11:57:00', '2026-01-09 11:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 202000, 0.0, '2026-01-09 10:33:00', '2026-01-09 10:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 203000, 9048, '2026-01-12 10:00:00', '2026-01-12 10:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 203000, 0.0, '2026-01-12 11:54:00', '2026-01-12 11:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 206000, 44916, '2026-01-15 13:43:00', '2026-01-15 13:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 206000, 0.0, '2026-01-15 09:35:00', '2026-01-15 09:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 69900, -92105, '2026-01-16 11:46:00', '2026-01-16 11:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 53, 69900, 0.0, '2026-01-16 10:19:00', '2026-01-16 10:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 214500, 143541, '2026-01-20 14:18:00', '2026-01-20 14:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 214500, 0.0, '2026-01-20 11:50:00', '2026-01-20 11:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 53, 72300, 117812, '2026-01-23 15:52:00', '2026-01-23 15:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72300, 0.0, '2026-01-23 10:01:00', '2026-01-23 10:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 213500, -25892, '2026-01-26 11:29:00', '2026-01-26 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 210000, 0.0, '2026-01-27 09:04:00', '2026-01-27 09:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 73100, 31666, '2026-01-28 13:20:00', '2026-01-28 13:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 209500, -17225, '2026-01-28 10:17:00', '2026-01-28 10:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 73100, 0.0, '2026-01-28 09:43:00', '2026-01-28 09:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 72100, -60009, '2026-01-29 11:12:00', '2026-01-29 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 72100, 0.0, '2026-01-29 11:03:00', '2026-01-29 11:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 207000, 0.0, '2026-02-02 09:48:00', '2026-02-02 09:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 73700, 73810, '2026-02-06 13:55:00', '2026-02-06 13:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 210500, 53717, '2026-02-09 15:01:00', '2026-02-09 15:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 206000, 0.0, '2026-02-10 09:24:00', '2026-02-10 09:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 75300, 0.0, '2026-02-11 10:37:00', '2026-02-11 10:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 193900, -226351, '2026-02-16 13:38:00', '2026-02-16 13:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 19, 193900, 0.0, '2026-02-16 10:17:00', '2026-02-16 10:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 76700, 59392, '2026-02-17 15:20:00', '2026-02-17 15:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 19, 186600, -147386, '2026-02-18 10:58:00', '2026-02-18 10:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 20, 186600, 0.0, '2026-02-18 11:36:00', '2026-02-18 11:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 20, 179800, -144810, '2026-02-19 12:50:00', '2026-02-19 12:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 73700, 0.0, '2026-02-19 09:08:00', '2026-02-19 09:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 21, 175800, 0.0, '2026-02-20 11:31:00', '2026-02-20 11:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 73600, -14016, '2026-02-23 12:34:00', '2026-02-23 12:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 21, 173900, -48847, '2026-02-23 11:19:00', '2026-02-23 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 73600, 0.0, '2026-02-23 11:26:00', '2026-02-23 11:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 21, 174900, 0.0, '2026-02-24 11:36:00', '2026-02-24 11:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 72300, -73856, '2026-02-26 12:42:00', '2026-02-26 12:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 21, 170900, -92792, '2026-02-27 11:15:00', '2026-02-27 11:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 75800, 0.0, '2026-03-03 11:35:00', '2026-03-03 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 77300, 64220, '2026-03-06 14:44:00', '2026-03-06 14:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 21, 170600, 0.0, '2026-03-09 09:00:00', '2026-03-09 09:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 76100, 0.0, '2026-03-10 09:51:00', '2026-03-10 09:51:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 158200, 0.0, '2025-12-22 10:50:00', '2025-12-22 10:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 35, 70300, 0.0, '2025-12-29 11:12:00', '2025-12-29 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 163000, 66009, '2025-12-31 14:51:00', '2025-12-31 14:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 14, 168300, 0.0, '2026-01-02 11:51:00', '2026-01-02 11:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 14, 163500, -72808, '2026-01-05 10:43:00', '2026-01-05 10:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 163500, 0.0, '2026-01-05 10:43:00', '2026-01-05 10:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 35, 72200, 60309, '2026-01-06 13:39:00', '2026-01-06 13:39:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 34, 72200, 0.0, '2026-01-06 11:02:00', '2026-01-06 11:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 171700, 116690, '2026-01-13 14:15:00', '2026-01-13 14:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 34, 75400, 102519, '2026-01-13 10:23:00', '2026-01-13 10:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 14, 173700, 0.0, '2026-01-14 10:48:00', '2026-01-14 10:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 32, 76800, 0.0, '2026-01-15 11:19:00', '2026-01-15 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 14, 162500, -162373, '2026-01-22 14:02:00', '2026-01-22 14:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 32, 78500, 48245, '2026-01-23 15:14:00', '2026-01-23 15:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 31, 78500, 0.0, '2026-01-23 11:28:00', '2026-01-23 11:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 164900, 0.0, '2026-01-28 10:15:00', '2026-01-28 10:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 31, 78600, -2869, '2026-02-05 14:40:00', '2026-02-05 14:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 161200, -61424, '2026-02-05 15:23:00', '2026-02-05 15:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 31, 78600, 0.0, '2026-02-05 11:41:00', '2026-02-05 11:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 162800, 0.0, '2026-02-11 11:25:00', '2026-02-11 11:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 31, 80400, 49693, '2026-02-12 15:31:00', '2026-02-12 15:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 31, 80400, 0.0, '2026-02-12 11:32:00', '2026-02-12 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 31, 80600, 78, '2026-02-16 13:57:00', '2026-02-16 13:57:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 208000, 0.0, '2025-12-19 11:55:00', '2025-12-19 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 51, 48550, 0.0, '2025-12-22 10:56:00', '2025-12-22 10:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 204000, -53997, '2025-12-25 11:56:00', '2025-12-25 11:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 204000, 0.0, '2025-12-25 09:27:00', '2025-12-25 09:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 51, 46200, -125622, '2025-12-31 13:30:00', '2025-12-31 13:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 54, 46200, 0.0, '2025-12-31 10:22:00', '2025-12-31 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 212000, 89767, '2026-01-05 11:39:00', '2026-01-05 11:39:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 11, 212000, 0.0, '2026-01-05 11:12:00', '2026-01-05 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 54, 48150, 98930, '2026-01-08 15:58:00', '2026-01-08 15:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 52, 48050, 0.0, '2026-01-09 09:02:00', '2026-01-09 09:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 11, 211000, -16686, '2026-01-12 12:00:00', '2026-01-12 12:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 52, 47250, -47620, '2026-01-12 14:37:00', '2026-01-12 14:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 53, 46700, 0.0, '2026-01-15 09:16:00', '2026-01-15 09:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 53, 48050, 65311, '2026-01-19 12:11:00', '2026-01-19 12:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 11, 214500, 0.0, '2026-01-19 09:30:00', '2026-01-19 09:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 52, 47550, 0.0, '2026-01-21 10:08:00', '2026-01-21 10:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 11, 204500, -115511, '2026-01-26 10:20:00', '2026-01-26 10:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 206500, 0.0, '2026-01-28 11:28:00', '2026-01-28 11:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 202000, -59939, '2026-01-30 14:06:00', '2026-01-30 14:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 202000, 0.0, '2026-01-30 09:49:00', '2026-01-30 09:49:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 52, 45550, -109803, '2026-02-04 14:32:00', '2026-02-04 14:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 54, 45550, 0.0, '2026-02-04 09:31:00', '2026-02-04 09:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 194000, -101703, '2026-02-09 14:17:00', '2026-02-09 14:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 54, 45500, -8720, '2026-02-09 12:10:00', '2026-02-09 12:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 56, 44000, 0.0, '2026-02-17 09:46:00', '2026-02-17 09:46:00');

-- ── 최종 포지션 (6건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 21, 170600, 0.0, '2026-03-11 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 49, 76100, 0.0, '2026-03-11 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-macd-cross', '000660', 15, 162800, 0.0, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-macd-cross', '005930', 0, 0.0, 257975, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '035720', 56, 44000, 0.0, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '005380', 0, 0.0, -258069, '2026-02-18 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 15000000, 225158, 0.0, 103176174, 95712832);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-macd-cross', 10000000, 5255680, 0.0, 29268789, 26966469);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-01', 10000000, 4681625, 0.0, 31883132, 29028757);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 42000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 35000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 7000000);

-- ── 자금 변동 이력 (105건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'allocate', 10000000, '초기 할당', '2025-12-19 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2496374, '현대차 12주 매수', '2025-12-19 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 15000000, '초기 할당', '2025-12-22 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'allocate', 10000000, '초기 할당', '2025-12-22 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2373356, 'SK하이닉스 15주 매수', '2025-12-22 10:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2476421, '카카오 51주 매수', '2025-12-22 10:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3731760, '삼성전자 53주 매수', '2025-12-22 11:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3696054, 'NAVER 19주 매수', '2025-12-24 09:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2448367, '현대차 12주 매수', '2025-12-25 09:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2447633, '현대차 12주 매도', '2025-12-25 11:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2460869, '삼성전자 35주 매수', '2025-12-29 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3753837, 'NAVER 19주 매도', '2025-12-30 10:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3847223, '삼성전자 53주 매도', '2025-12-30 12:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2495174, '카카오 54주 매수', '2025-12-31 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3593339, 'NAVER 18주 매수', '2025-12-31 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2355847, '카카오 51주 매도', '2025-12-31 13:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2444633, 'SK하이닉스 15주 매도', '2025-12-31 14:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3713357, '삼성전자 52주 매수', '2026-01-01 09:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3626456, 'NAVER 18주 매도', '2026-01-02 10:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2356553, 'SK하이닉스 14주 매수', '2026-01-02 11:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3744562, '삼성전자 52주 매수', '2026-01-05 10:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2288657, 'SK하이닉스 14주 매도', '2026-01-05 10:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2452868, 'SK하이닉스 15주 매수', '2026-01-05 10:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2332350, '현대차 11주 매수', '2026-01-05 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2543618, '현대차 12주 매도', '2026-01-05 11:39:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3743438, '삼성전자 52주 매도', '2026-01-05 14:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3587938, 'NAVER 18주 매수', '2026-01-06 11:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2455168, '삼성전자 34주 매수', '2026-01-06 11:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2526621, '삼성전자 35주 매도', '2026-01-06 13:39:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3717442, '삼성전자 52주 매도', '2026-01-08 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3718558, '삼성전자 52주 매수', '2026-01-08 11:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2599710, '카카오 54주 매도', '2026-01-08 15:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2498975, '카카오 52주 매수', '2026-01-09 09:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3636545, 'NAVER 18주 매수', '2026-01-09 10:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3635455, 'NAVER 18주 매도', '2026-01-09 11:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3653452, 'NAVER 18주 매도', '2026-01-12 10:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3654548, 'NAVER 18주 매수', '2026-01-12 11:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2320652, '현대차 11주 매도', '2026-01-12 12:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2456631, '카카오 52주 매도', '2026-01-12 14:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2563215, '삼성전자 34주 매도', '2026-01-13 10:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2575114, 'SK하이닉스 15주 매도', '2026-01-13 14:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2432165, 'SK하이닉스 14주 매수', '2026-01-14 10:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2475471, '카카오 53주 매수', '2026-01-15 09:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3708556, 'NAVER 18주 매수', '2026-01-15 09:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2457969, '삼성전자 32주 매수', '2026-01-15 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3707444, 'NAVER 18주 매도', '2026-01-15 13:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3705256, '삼성전자 53주 매수', '2026-01-16 10:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3634255, '삼성전자 52주 매도', '2026-01-16 11:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2359854, '현대차 11주 매수', '2026-01-19 09:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2546268, '카카오 53주 매도', '2026-01-19 12:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3647047, 'NAVER 17주 매수', '2026-01-20 11:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3860421, 'NAVER 18주 매도', '2026-01-20 14:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2472971, '카카오 52주 매수', '2026-01-21 10:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2274659, 'SK하이닉스 14주 매도', '2026-01-22 14:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3687853, '삼성전자 51주 매수', '2026-01-23 10:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2433865, '삼성전자 31주 매수', '2026-01-23 11:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2511623, '삼성전자 32주 매도', '2026-01-23 15:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3831325, '삼성전자 53주 매도', '2026-01-23 15:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2249163, '현대차 11주 매도', '2026-01-26 10:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3628956, 'NAVER 17주 매도', '2026-01-26 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3570536, 'NAVER 17주 매수', '2026-01-27 09:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3728659, '삼성전자 51주 매수', '2026-01-28 09:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2473871, 'SK하이닉스 15주 매수', '2026-01-28 10:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3560966, 'NAVER 17주 매도', '2026-01-28 10:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2478372, '현대차 12주 매수', '2026-01-28 11:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3727541, '삼성전자 51주 매도', '2026-01-28 13:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3749762, '삼성전자 52주 매수', '2026-01-29 11:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3676548, '삼성전자 51주 매도', '2026-01-29 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2424364, '현대차 12주 매수', '2026-01-30 09:49:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2423636, '현대차 12주 매도', '2026-01-30 14:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3726559, 'NAVER 18주 매수', '2026-02-02 09:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2460069, '카카오 54주 매수', '2026-02-04 09:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2368245, '카카오 52주 매도', '2026-02-04 14:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2436965, '삼성전자 31주 매수', '2026-02-05 11:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2436235, '삼성전자 31주 매도', '2026-02-05 14:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2417637, 'SK하이닉스 15주 매도', '2026-02-05 15:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3831825, '삼성전자 52주 매도', '2026-02-06 13:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2456631, '카카오 54주 매도', '2026-02-09 12:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2327651, '현대차 12주 매도', '2026-02-09 14:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3788432, 'NAVER 18주 매도', '2026-02-09 15:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3708556, 'NAVER 18주 매수', '2026-02-10 09:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3690253, '삼성전자 49주 매수', '2026-02-11 10:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2442366, 'SK하이닉스 15주 매수', '2026-02-11 11:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2492774, '삼성전자 31주 매수', '2026-02-12 11:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2492026, '삼성전자 31주 매도', '2026-02-12 15:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3684653, 'NAVER 19주 매수', '2026-02-16 10:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3489676, 'NAVER 18주 매도', '2026-02-16 13:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2498225, '삼성전자 31주 매도', '2026-02-16 13:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2464370, '카카오 56주 매수', '2026-02-17 09:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3757736, '삼성전자 49주 매도', '2026-02-17 15:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3544868, 'NAVER 19주 매도', '2026-02-18 10:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3732560, 'NAVER 20주 매수', '2026-02-18 11:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3685553, '삼성전자 50주 매수', '2026-02-19 09:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3595461, 'NAVER 20주 매도', '2026-02-19 12:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3692354, 'NAVER 21주 매수', '2026-02-20 11:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3651352, 'NAVER 21주 매도', '2026-02-23 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3680552, '삼성전자 50주 매수', '2026-02-23 11:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3679448, '삼성전자 50주 매도', '2026-02-23 12:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3673451, 'NAVER 21주 매수', '2026-02-24 11:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3614458, '삼성전자 50주 매도', '2026-02-26 12:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3588362, 'NAVER 21주 매도', '2026-02-27 11:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3714757, '삼성전자 49주 매수', '2026-03-03 11:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3787132, '삼성전자 49주 매도', '2026-03-06 14:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3583137, 'NAVER 21주 매수', '2026-03-09 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3729459, '삼성전자 49주 매수', '2026-03-10 09:51:00');

-- ── 이벤트 로그 (22건) ──────────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-001', 'bot.step.success', '2025-12-22 11:46:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-002', 'bot.step.success', '2026-01-01 09:28:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-003', 'bot.step.success', '2026-01-08 11:17:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-004', 'bot.step.success', '2026-01-12 11:54:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-005', 'bot.step.success', '2026-01-20 14:18:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-006', 'bot.step.success', '2026-01-27 09:04:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-007', 'bot.step.success', '2026-01-29 11:03:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-008', 'bot.step.success', '2026-02-11 10:37:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-009', 'bot.step.success', '2026-02-18 11:36:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-010', 'bot.step.success', '2026-02-23 11:19:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-011', 'bot.step.success', '2026-03-03 11:35:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-001', 'bot.step.success', '2025-12-22 10:50:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-002', 'bot.step.success', '2026-01-05 10:43:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-003', 'bot.step.success', '2026-01-14 10:48:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-004', 'bot.step.success', '2026-01-28 10:15:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-005', 'bot.step.success', '2026-02-12 15:31:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--001', 'bot.step.success', '2025-12-19 11:55:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--002', 'bot.step.success', '2025-12-31 10:22:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--003', 'bot.step.success', '2026-01-12 12:00:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--004', 'bot.step.success', '2026-01-21 10:08:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--005', 'bot.step.success', '2026-02-04 14:32:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--006', 'bot.stopped', '2026-03-17 15:00:00', '{"bot_id": "bot-rsi-01", "message": "Bot 중지됨 — 사용자 요청"}');

-- ── 멤버 ────────────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write", "data:read", "backtest:run", "report:write"]', 'datetime(''now'', ''-60 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write", "data:read", "backtest:run"]', 'datetime(''now'', ''-45 days'')');
