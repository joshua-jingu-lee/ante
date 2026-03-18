-- 시나리오: login-dashboard
-- 생성: generate_scenario.py (seed=789)
-- 생성일: 2026-03-18

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-01-17 09:00:00', '20일 고점 돌파 시 매수', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', '2026-02-01 09:00:00', 'RSI 과매도 반등 전략', 'strategy-dev-02');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-01", "strategy_id": "momentum-v2", "name": "모멘텀 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "000660", "035420"]}', 'running', '2026-01-22 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-01', 'RSI 봇', 'rsi-reversal', 'live', '{"bot_id": "bot-rsi-01", "strategy_id": "rsi-reversal", "name": "RSI 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["035720", "005380"]}', 'running', '2026-01-27 09:00:00');

-- ── 거래 내역 (116건) ────────────────────────
-- bot-momentum-01: 77건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0001', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 30, 208000, 'filled', 936, '2025-12-08 09:31:00', '2025-12-08 09:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0002', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 42, 147300, 'filled', 928, '2025-12-09 11:33:00', '2025-12-09 11:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0003', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 30, 203500, 'filled', 916, '2025-12-10 12:19:00', '2025-12-10 12:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0004', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 70100, 'filled', 936, '2025-12-11 10:29:00', '2025-12-11 10:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0005', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 30, 207500, 'filled', 934, '2025-12-15 09:13:00', '2025-12-15 09:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0006', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 42, 149700, 'filled', 943, '2025-12-16 14:06:00', '2025-12-16 14:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0007', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 89, 71300, 'filled', 952, '2025-12-16 14:33:00', '2025-12-16 14:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0008', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 42, 148100, 'filled', 933, '2025-12-17 10:04:00', '2025-12-17 10:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0009', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 30, 207500, 'filled', 934, '2025-12-19 11:12:00', '2025-12-19 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0010', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 69600, 'filled', 929, '2025-12-19 10:55:00', '2025-12-19 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0011', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 89, 68900, 'filled', 920, '2025-12-23 13:33:00', '2025-12-23 13:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0012', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 90, 68900, 'filled', 930, '2025-12-23 10:02:00', '2025-12-23 10:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0013', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 28, 216000, 'filled', 907, '2025-12-24 11:33:00', '2025-12-24 11:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0014', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 90, 66300, 'filled', 895, '2025-12-26 12:05:00', '2025-12-26 12:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0015', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 94, 66300, 'filled', 935, '2025-12-26 09:02:00', '2025-12-26 09:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0016', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 42, 150400, 'filled', 948, '2025-12-29 15:09:00', '2025-12-29 15:09:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0017', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 94, 65500, 'filled', 924, '2025-12-29 15:03:00', '2025-12-29 15:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0018', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 95, 65500, 'filled', 933, '2025-12-29 11:01:00', '2025-12-29 11:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0019', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 28, 216000, 'filled', 907, '2026-01-01 12:17:00', '2026-01-01 12:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0020', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 95, 65600, 'filled', 935, '2026-01-02 10:18:00', '2026-01-02 10:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0021', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 210500, 'filled', 916, '2026-01-02 10:08:00', '2026-01-02 10:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0022', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 94, 66200, 'filled', 933, '2026-01-05 09:51:00', '2026-01-05 09:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0023', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 29, 217000, 'filled', 944, '2026-01-06 13:06:00', '2026-01-06 13:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0024', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 41, 150500, 'filled', 926, '2026-01-06 09:11:00', '2026-01-06 09:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0025', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 214000, 'filled', 931, '2026-01-07 09:02:00', '2026-01-07 09:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0026', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 94, 66100, 'filled', 932, '2026-01-09 11:49:00', '2026-01-09 11:49:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0027', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 94, 66100, 'filled', 932, '2026-01-09 11:50:00', '2026-01-09 11:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0028', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 41, 140700, 'filled', 865, '2026-01-13 13:28:00', '2026-01-13 13:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0029', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 44, 140700, 'filled', 929, '2026-01-13 10:23:00', '2026-01-13 10:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0030', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 29, 225000, 'filled', 979, '2026-01-14 13:23:00', '2026-01-14 13:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0031', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 27, 225000, 'filled', 911, '2026-01-14 11:31:00', '2026-01-14 11:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0032', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 94, 69500, 'filled', 980, '2026-01-15 15:40:00', '2026-01-15 15:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0033', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 44, 139000, 'filled', 917, '2026-01-15 12:29:00', '2026-01-15 12:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0034', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 69500, 'filled', 928, '2026-01-15 11:27:00', '2026-01-15 11:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0035', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 43, 143400, 'filled', 925, '2026-01-16 09:03:00', '2026-01-16 09:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0036', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 27, 228000, 'filled', 923, '2026-01-19 12:06:00', '2026-01-19 12:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0037', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 89, 71500, 'filled', 955, '2026-01-20 13:18:00', '2026-01-20 13:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0038', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 43, 142700, 'filled', 920, '2026-01-20 15:34:00', '2026-01-20 15:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0039', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 86, 72400, 'filled', 934, '2026-01-21 10:42:00', '2026-01-21 10:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0040', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 44, 140800, 'filled', 929, '2026-01-23 11:52:00', '2026-01-23 11:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0041', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 27, 230500, 'filled', 934, '2026-01-26 10:14:00', '2026-01-26 10:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0042', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 86, 70100, 'filled', 904, '2026-01-27 14:23:00', '2026-01-27 14:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0043', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 70100, 'filled', 936, '2026-01-27 09:49:00', '2026-01-27 09:49:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0044', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 44, 148500, 'filled', 980, '2026-01-28 15:11:00', '2026-01-28 15:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0045', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 27, 231000, 'filled', 936, '2026-01-28 13:52:00', '2026-01-28 13:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0046', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 42, 148500, 'filled', 936, '2026-01-28 09:01:00', '2026-01-28 09:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0047', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 27, 230500, 'filled', 934, '2026-01-29 11:42:00', '2026-01-29 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0048', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 42, 139400, 'filled', 878, '2026-01-30 13:00:00', '2026-01-30 13:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0049', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 89, 69600, 'filled', 929, '2026-02-02 10:46:00', '2026-02-02 10:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0050', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 27, 222000, 'filled', 899, '2026-02-02 13:50:00', '2026-02-02 13:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0051', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 69600, 'filled', 929, '2026-02-02 11:16:00', '2026-02-02 11:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0052', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 28, 221000, 'filled', 928, '2026-02-03 11:56:00', '2026-02-03 11:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0053', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 89, 70300, 'filled', 939, '2026-02-04 13:55:00', '2026-02-04 13:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0054', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 44, 141500, 'filled', 934, '2026-02-04 10:20:00', '2026-02-04 10:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0055', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 87, 71300, 'filled', 930, '2026-02-06 09:37:00', '2026-02-06 09:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0056', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 28, 219000, 'filled', 920, '2026-02-10 12:30:00', '2026-02-10 12:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0057', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 44, 149900, 'filled', 989, '2026-02-10 14:31:00', '2026-02-10 14:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0058', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 41, 149900, 'filled', 922, '2026-02-10 10:52:00', '2026-02-10 10:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0059', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 87, 73800, 'filled', 963, '2026-02-11 13:52:00', '2026-02-11 13:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0060', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 214000, 'filled', 931, '2026-02-11 10:57:00', '2026-02-11 10:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0061', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 84, 73700, 'filled', 929, '2026-02-12 10:06:00', '2026-02-12 10:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0062', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 84, 73000, 'filled', 920, '2026-02-16 12:12:00', '2026-02-16 12:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0063', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 85, 73000, 'filled', 931, '2026-02-16 11:41:00', '2026-02-16 11:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0064', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 29, 204000, 'filled', 887, '2026-02-17 13:03:00', '2026-02-17 13:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0065', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 30, 204000, 'filled', 918, '2026-02-17 11:58:00', '2026-02-17 11:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0066', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 41, 164000, 'filled', 1009, '2026-02-18 15:35:00', '2026-02-18 15:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0067', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 85, 71400, 'filled', 910, '2026-02-19 12:56:00', '2026-02-19 12:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0068', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 87, 71400, 'filled', 932, '2026-02-19 11:06:00', '2026-02-19 11:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0069', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 37, 166900, 'filled', 926, '2026-02-20 11:35:00', '2026-02-20 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0070', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 30, 203500, 'filled', 916, '2026-02-23 12:00:00', '2026-02-23 12:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0071', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 87, 70700, 'filled', 923, '2026-02-24 13:22:00', '2026-02-24 13:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0072', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 37, 168300, 'filled', 934, '2026-02-24 10:33:00', '2026-02-24 10:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0073', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 209500, 'filled', 911, '2026-02-24 11:49:00', '2026-02-24 11:49:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0074', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 37, 167000, 'filled', 927, '2026-02-25 09:25:00', '2026-02-25 09:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0075', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 70000, 'filled', 934, '2026-02-26 11:17:00', '2026-02-26 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0076', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 29, 212000, 'filled', 922, '2026-02-27 14:30:00', '2026-02-27 14:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0077', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 212000, 'filled', 922, '2026-02-27 11:54:00', '2026-02-27 11:54:00');

-- bot-rsi-01: 39건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0001', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 17, 218500, 'filled', 557, '2025-12-09 11:13:00', '2025-12-09 11:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0002', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 75, 49350, 'filled', 555, '2025-12-10 11:00:00', '2025-12-10 11:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0003', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 17, 215000, 'filled', 548, '2025-12-15 10:50:00', '2025-12-15 10:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0004', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 17, 214500, 'filled', 547, '2025-12-16 11:23:00', '2025-12-16 11:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0005', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 17, 219500, 'filled', 560, '2025-12-22 14:59:00', '2025-12-22 14:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0006', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 75, 48000, 'filled', 540, '2025-12-23 10:22:00', '2025-12-23 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0007', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 78, 48000, 'filled', 562, '2025-12-23 09:46:00', '2025-12-23 09:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0008', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 17, 216000, 'filled', 551, '2025-12-25 11:34:00', '2025-12-25 11:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0009', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 78, 45400, 'filled', 531, '2026-01-01 12:19:00', '2026-01-01 12:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0010', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 17, 207000, 'filled', 528, '2026-01-01 10:55:00', '2026-01-01 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0011', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 208000, 'filled', 562, '2026-01-02 10:52:00', '2026-01-02 10:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0012', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 208000, 'filled', 562, '2026-01-05 15:03:00', '2026-01-05 15:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0013', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 208000, 'filled', 562, '2026-01-05 11:21:00', '2026-01-05 11:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0014', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 201500, 'filled', 544, '2026-01-07 12:35:00', '2026-01-07 12:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0015', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 199800, 'filled', 539, '2026-01-09 11:25:00', '2026-01-09 11:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0016', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 81, 45850, 'filled', 557, '2026-01-12 09:43:00', '2026-01-12 09:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0017', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 195800, 'filled', 529, '2026-01-16 13:25:00', '2026-01-16 13:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0018', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 19, 195800, 'filled', 558, '2026-01-16 09:02:00', '2026-01-16 09:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0019', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 81, 42650, 'filled', 518, '2026-01-21 13:28:00', '2026-01-21 13:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0020', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 87, 42650, 'filled', 557, '2026-01-21 09:47:00', '2026-01-21 09:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0021', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 19, 203000, 'filled', 579, '2026-01-26 12:34:00', '2026-01-26 12:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0022', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 203000, 'filled', 548, '2026-01-26 11:15:00', '2026-01-26 11:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0023', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 87, 43300, 'filled', 565, '2026-01-30 12:54:00', '2026-01-30 12:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0024', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 207500, 'filled', 560, '2026-01-30 14:16:00', '2026-01-30 14:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0025', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 205500, 'filled', 555, '2026-02-02 11:59:00', '2026-02-02 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0026', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 205500, 'filled', 555, '2026-02-03 14:45:00', '2026-02-03 14:45:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0027', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 90, 41500, 'filled', 560, '2026-02-04 11:27:00', '2026-02-04 11:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0028', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 204000, 'filled', 551, '2026-02-05 09:26:00', '2026-02-05 09:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0029', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 202500, 'filled', 547, '2026-02-11 15:23:00', '2026-02-11 15:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0030', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 19, 196200, 'filled', 559, '2026-02-12 11:47:00', '2026-02-12 11:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0031', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 90, 42550, 'filled', 574, '2026-02-16 15:58:00', '2026-02-16 15:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0032', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 19, 198000, 'filled', 564, '2026-02-16 11:51:00', '2026-02-16 11:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0033', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 86, 43150, 'filled', 557, '2026-02-17 11:25:00', '2026-02-17 11:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0034', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 199800, 'filled', 539, '2026-02-20 09:55:00', '2026-02-20 09:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0035', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 201500, 'filled', 544, '2026-02-23 12:00:00', '2026-02-23 12:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0036', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 201500, 'filled', 544, '2026-02-23 09:46:00', '2026-02-23 09:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0037', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 191300, 'filled', 517, '2026-02-26 15:18:00', '2026-02-26 15:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0038', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 19, 191300, 'filled', 545, '2026-02-26 11:13:00', '2026-02-26 11:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0039', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 86, 43600, 'filled', 562, '2026-02-27 14:18:00', '2026-02-27 14:18:00');

-- ── 포지션 이력 (116건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 30, 208000, 0.0, '2025-12-08 09:31:00', '2025-12-08 09:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 42, 147300, 0.0, '2025-12-09 11:33:00', '2025-12-09 11:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 30, 203500, -149958, '2025-12-10 12:19:00', '2025-12-10 12:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 70100, 0.0, '2025-12-11 10:29:00', '2025-12-11 10:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 30, 207500, 0.0, '2025-12-15 09:13:00', '2025-12-15 09:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 42, 149700, 85396, '2025-12-16 14:06:00', '2025-12-16 14:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 89, 71300, 91253, '2025-12-16 14:33:00', '2025-12-16 14:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 42, 148100, 0.0, '2025-12-17 10:04:00', '2025-12-17 10:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 30, 207500, -15252, '2025-12-19 11:12:00', '2025-12-19 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 69600, 0.0, '2025-12-19 10:55:00', '2025-12-19 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 89, 68900, -77324, '2025-12-23 13:33:00', '2025-12-23 13:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 90, 68900, 0.0, '2025-12-23 10:02:00', '2025-12-23 10:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 28, 216000, 0.0, '2025-12-24 11:33:00', '2025-12-24 11:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 90, 66300, -248619, '2025-12-26 12:05:00', '2025-12-26 12:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 94, 66300, 0.0, '2025-12-26 09:02:00', '2025-12-26 09:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 42, 150400, 81123, '2025-12-29 15:09:00', '2025-12-29 15:09:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 94, 65500, -90285, '2025-12-29 15:03:00', '2025-12-29 15:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 95, 65500, 0.0, '2025-12-29 11:01:00', '2025-12-29 11:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 28, 216000, -14817, '2026-01-01 12:17:00', '2026-01-01 12:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 95, 65600, -5769, '2026-01-02 10:18:00', '2026-01-02 10:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 210500, 0.0, '2026-01-02 10:08:00', '2026-01-02 10:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 94, 66200, 0.0, '2026-01-05 09:51:00', '2026-01-05 09:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 29, 217000, 173082, '2026-01-06 13:06:00', '2026-01-06 13:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 41, 150500, 0.0, '2026-01-06 09:11:00', '2026-01-06 09:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 214000, 0.0, '2026-01-07 09:02:00', '2026-01-07 09:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 94, 66100, -24623, '2026-01-09 11:49:00', '2026-01-09 11:49:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 94, 66100, 0.0, '2026-01-09 11:50:00', '2026-01-09 11:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 41, 140700, -415933, '2026-01-13 13:28:00', '2026-01-13 13:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 44, 140700, 0.0, '2026-01-13 10:23:00', '2026-01-13 10:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 29, 225000, 303013, '2026-01-14 13:23:00', '2026-01-14 13:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 27, 225000, 0.0, '2026-01-14 11:31:00', '2026-01-14 11:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 94, 69500, 303594, '2026-01-15 15:40:00', '2026-01-15 15:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 44, 139000, -89784, '2026-01-15 12:29:00', '2026-01-15 12:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 69500, 0.0, '2026-01-15 11:27:00', '2026-01-15 11:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 43, 143400, 0.0, '2026-01-16 09:03:00', '2026-01-16 09:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 27, 228000, 65918, '2026-01-19 12:06:00', '2026-01-19 12:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 89, 71500, 162409, '2026-01-20 13:18:00', '2026-01-20 13:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 43, 142700, -45133, '2026-01-20 15:34:00', '2026-01-20 15:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 86, 72400, 0.0, '2026-01-21 10:42:00', '2026-01-21 10:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 44, 140800, 0.0, '2026-01-23 11:52:00', '2026-01-23 11:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 27, 230500, 0.0, '2026-01-26 10:14:00', '2026-01-26 10:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 86, 70100, -212570, '2026-01-27 14:23:00', '2026-01-27 14:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 70100, 0.0, '2026-01-27 09:49:00', '2026-01-27 09:49:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 44, 148500, 322792, '2026-01-28 15:11:00', '2026-01-28 15:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 27, 231000, -1781, '2026-01-28 13:52:00', '2026-01-28 13:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 42, 148500, 0.0, '2026-01-28 09:01:00', '2026-01-28 09:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 27, 230500, 0.0, '2026-01-29 11:42:00', '2026-01-29 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 42, 139400, -396544, '2026-01-30 13:00:00', '2026-01-30 13:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 89, 69600, -59676, '2026-02-02 10:46:00', '2026-02-02 10:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 27, 222000, -244185, '2026-02-02 13:50:00', '2026-02-02 13:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 69600, 0.0, '2026-02-02 11:16:00', '2026-02-02 11:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 28, 221000, 0.0, '2026-02-03 11:56:00', '2026-02-03 11:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 89, 70300, 46971, '2026-02-04 13:55:00', '2026-02-04 13:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 44, 141500, 0.0, '2026-02-04 10:20:00', '2026-02-04 10:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 87, 71300, 0.0, '2026-02-06 09:37:00', '2026-02-06 09:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 28, 219000, -71024, '2026-02-10 12:30:00', '2026-02-10 12:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 44, 149900, 353441, '2026-02-10 14:31:00', '2026-02-10 14:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 41, 149900, 0.0, '2026-02-10 10:52:00', '2026-02-10 10:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 87, 73800, 201770, '2026-02-11 13:52:00', '2026-02-11 13:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 214000, 0.0, '2026-02-11 10:57:00', '2026-02-11 10:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 84, 73700, 0.0, '2026-02-12 10:06:00', '2026-02-12 10:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 84, 73000, -73824, '2026-02-16 12:12:00', '2026-02-16 12:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 85, 73000, 0.0, '2026-02-16 11:41:00', '2026-02-16 11:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 29, 204000, -304494, '2026-02-17 13:03:00', '2026-02-17 13:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 30, 204000, 0.0, '2026-02-17 11:58:00', '2026-02-17 11:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 41, 164000, 561626, '2026-02-18 15:35:00', '2026-02-18 15:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 85, 71400, -150869, '2026-02-19 12:56:00', '2026-02-19 12:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 87, 71400, 0.0, '2026-02-19 11:06:00', '2026-02-19 11:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 37, 166900, 0.0, '2026-02-20 11:35:00', '2026-02-20 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 30, 203500, -29958, '2026-02-23 12:00:00', '2026-02-23 12:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 87, 70700, -75970, '2026-02-24 13:22:00', '2026-02-24 13:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 37, 168300, 36544, '2026-02-24 10:33:00', '2026-02-24 10:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 209500, 0.0, '2026-02-24 11:49:00', '2026-02-24 11:49:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 37, 167000, 0.0, '2026-02-25 09:25:00', '2026-02-25 09:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 70000, 0.0, '2026-02-26 11:17:00', '2026-02-26 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 29, 212000, 57438, '2026-02-27 14:30:00', '2026-02-27 14:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 212000, 0.0, '2026-02-27 11:54:00', '2026-02-27 11:54:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 17, 218500, 0.0, '2025-12-09 11:13:00', '2025-12-09 11:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 75, 49350, 0.0, '2025-12-10 11:00:00', '2025-12-10 11:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 17, 215000, -68454, '2025-12-15 10:50:00', '2025-12-15 10:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 17, 214500, 0.0, '2025-12-16 11:23:00', '2025-12-16 11:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 17, 219500, 75858, '2025-12-22 14:59:00', '2025-12-22 14:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 75, 48000, -110070, '2025-12-23 10:22:00', '2025-12-23 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 78, 48000, 0.0, '2025-12-23 09:46:00', '2025-12-23 09:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 17, 216000, 0.0, '2025-12-25 11:34:00', '2025-12-25 11:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 78, 45400, -211476, '2026-01-01 12:19:00', '2026-01-01 12:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 17, 207000, -161622, '2026-01-01 10:55:00', '2026-01-01 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 208000, 0.0, '2026-01-02 10:52:00', '2026-01-02 10:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 208000, -9173, '2026-01-05 15:03:00', '2026-01-05 15:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 208000, 0.0, '2026-01-05 11:21:00', '2026-01-05 11:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 201500, -125886, '2026-01-07 12:35:00', '2026-01-07 12:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 199800, 0.0, '2026-01-09 11:25:00', '2026-01-09 11:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 81, 45850, 0.0, '2026-01-12 09:43:00', '2026-01-12 09:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 195800, -80635, '2026-01-16 13:25:00', '2026-01-16 13:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 19, 195800, 0.0, '2026-01-16 09:02:00', '2026-01-16 09:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 81, 42650, -267664, '2026-01-21 13:28:00', '2026-01-21 13:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 87, 42650, 0.0, '2026-01-21 09:47:00', '2026-01-21 09:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 19, 203000, 127350, '2026-01-26 12:34:00', '2026-01-26 12:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 203000, 0.0, '2026-01-26 11:15:00', '2026-01-26 11:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 87, 43300, 47321, '2026-01-30 12:54:00', '2026-01-30 12:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 207500, 71850, '2026-01-30 14:16:00', '2026-01-30 14:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 205500, 0.0, '2026-02-02 11:59:00', '2026-02-02 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 205500, -9063, '2026-02-03 14:45:00', '2026-02-03 14:45:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 90, 41500, 0.0, '2026-02-04 11:27:00', '2026-02-04 11:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 204000, 0.0, '2026-02-05 09:26:00', '2026-02-05 09:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 202500, -35931, '2026-02-11 15:23:00', '2026-02-11 15:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 19, 196200, 0.0, '2026-02-12 11:47:00', '2026-02-12 11:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 90, 42550, 85118, '2026-02-16 15:58:00', '2026-02-16 15:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 19, 198000, 24983, '2026-02-16 11:51:00', '2026-02-16 11:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 86, 43150, 0.0, '2026-02-17 11:25:00', '2026-02-17 11:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 199800, 0.0, '2026-02-20 09:55:00', '2026-02-20 09:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 201500, 21714, '2026-02-23 12:00:00', '2026-02-23 12:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 201500, 0.0, '2026-02-23 09:46:00', '2026-02-23 09:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 191300, -192037, '2026-02-26 15:18:00', '2026-02-26 15:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 19, 191300, 0.0, '2026-02-26 11:13:00', '2026-02-26 11:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 86, 43600, 29514, '2026-02-27 14:18:00', '2026-02-27 14:18:00');

-- ── 최종 포지션 (5건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '000660', 37, 167000, 0.0, '2026-02-27 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 89, 70000, 0.0, '2026-02-27 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 29, 212000, 0.0, '2026-02-27 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '005380', 19, 191300, 0.0, '2026-02-27 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '035720', 0, 0.0, -427257, '2026-02-27 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 25000000, 0, 0.0, 247623939, 229077778);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-01', 15000000, 6931232, 0.0, 73775115, 69341047);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 100000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 40000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 60000000);

-- ── 자금 변동 이력 (118건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 25000000, '초기 할당', '2025-12-08 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6240936, 'NAVER 30주 매수', '2025-12-08 09:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'allocate', 15000000, '초기 할당', '2025-12-09 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3715057, '현대차 17주 매수', '2025-12-09 11:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6187528, 'SK하이닉스 42주 매수', '2025-12-09 11:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3701805, '카카오 75주 매수', '2025-12-10 11:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6104084, 'NAVER 30주 매도', '2025-12-10 12:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6239836, '삼성전자 89주 매수', '2025-12-11 10:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6225934, 'NAVER 30주 매수', '2025-12-15 09:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3654452, '현대차 17주 매도', '2025-12-15 10:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3647047, '현대차 17주 매수', '2025-12-16 11:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6286457, 'SK하이닉스 42주 매도', '2025-12-16 14:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6344748, '삼성전자 89주 매도', '2025-12-16 14:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6221133, 'SK하이닉스 42주 매수', '2025-12-17 10:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6195329, '삼성전자 89주 매수', '2025-12-19 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6224066, 'NAVER 30주 매도', '2025-12-19 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3730940, '현대차 17주 매도', '2025-12-22 14:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3744562, '카카오 78주 매수', '2025-12-23 09:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6201930, '삼성전자 90주 매수', '2025-12-23 10:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3599460, '카카오 75주 매도', '2025-12-23 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6131180, '삼성전자 89주 매도', '2025-12-23 13:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6048907, 'NAVER 28주 매수', '2025-12-24 11:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3672551, '현대차 17주 매수', '2025-12-25 11:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6233135, '삼성전자 94주 매수', '2025-12-26 09:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5966105, '삼성전자 90주 매도', '2025-12-26 12:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6223433, '삼성전자 95주 매수', '2025-12-29 11:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6156076, '삼성전자 94주 매도', '2025-12-29 15:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6315852, 'SK하이닉스 42주 매도', '2025-12-29 15:09:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3518472, '현대차 17주 매도', '2026-01-01 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6047093, 'NAVER 28주 매도', '2026-01-01 12:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3540669, '카카오 78주 매도', '2026-01-01 12:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6105416, 'NAVER 29주 매수', '2026-01-02 10:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6231065, '삼성전자 95주 매도', '2026-01-02 10:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3744562, '현대차 18주 매수', '2026-01-02 10:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6223733, '삼성전자 94주 매수', '2026-01-05 09:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3744562, '현대차 18주 매수', '2026-01-05 11:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3743438, '현대차 18주 매도', '2026-01-05 15:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6171426, 'SK하이닉스 41주 매수', '2026-01-06 09:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6292056, 'NAVER 29주 매도', '2026-01-06 13:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6206931, 'NAVER 29주 매수', '2026-01-07 09:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3626456, '현대차 18주 매도', '2026-01-07 12:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3596939, '현대차 18주 매수', '2026-01-09 11:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6212468, '삼성전자 94주 매도', '2026-01-09 11:49:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6214332, '삼성전자 94주 매수', '2026-01-09 11:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3714407, '카카오 81주 매수', '2026-01-12 09:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6191729, 'SK하이닉스 44주 매수', '2026-01-13 10:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5767835, 'SK하이닉스 41주 매도', '2026-01-13 13:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6075911, 'NAVER 27주 매수', '2026-01-14 11:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6524021, 'NAVER 29주 매도', '2026-01-14 13:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6186428, '삼성전자 89주 매수', '2026-01-15 11:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6115083, 'SK하이닉스 44주 매도', '2026-01-15 12:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6532020, '삼성전자 94주 매도', '2026-01-15 15:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3720758, '현대차 19주 매수', '2026-01-16 09:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6167125, 'SK하이닉스 43주 매수', '2026-01-16 09:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3523871, '현대차 18주 매도', '2026-01-16 13:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6155077, 'NAVER 27주 매도', '2026-01-19 12:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6362545, '삼성전자 89주 매도', '2026-01-20 13:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6135180, 'SK하이닉스 43주 매도', '2026-01-20 15:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3711107, '카카오 87주 매수', '2026-01-21 09:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6227334, '삼성전자 86주 매수', '2026-01-21 10:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3454132, '카카오 81주 매도', '2026-01-21 13:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6196129, 'SK하이닉스 44주 매수', '2026-01-23 11:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6224434, 'NAVER 27주 매수', '2026-01-26 10:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3654548, '현대차 18주 매수', '2026-01-26 11:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3856421, '현대차 19주 매도', '2026-01-26 12:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6239836, '삼성전자 89주 매수', '2026-01-27 09:49:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6027696, '삼성전자 86주 매도', '2026-01-27 14:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6237936, 'SK하이닉스 42주 매수', '2026-01-28 09:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6236064, 'NAVER 27주 매도', '2026-01-28 13:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6533020, 'SK하이닉스 44주 매도', '2026-01-28 15:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6224434, 'NAVER 27주 매수', '2026-01-29 11:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3766535, '카카오 87주 매도', '2026-01-30 12:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5853922, 'SK하이닉스 42주 매도', '2026-01-30 13:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3734440, '현대차 18주 매도', '2026-01-30 14:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6193471, '삼성전자 89주 매도', '2026-02-02 10:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6195329, '삼성전자 89주 매수', '2026-02-02 11:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3699555, '현대차 18주 매수', '2026-02-02 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5993101, 'NAVER 27주 매도', '2026-02-02 13:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6188928, 'NAVER 28주 매수', '2026-02-03 11:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3698445, '현대차 18주 매도', '2026-02-03 14:45:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6226934, 'SK하이닉스 44주 매수', '2026-02-04 10:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3735560, '카카오 90주 매수', '2026-02-04 11:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6255761, '삼성전자 89주 매도', '2026-02-04 13:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3672551, '현대차 18주 매수', '2026-02-05 09:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6204030, '삼성전자 87주 매수', '2026-02-06 09:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6146822, 'SK하이닉스 41주 매수', '2026-02-10 10:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6131080, 'NAVER 28주 매도', '2026-02-10 12:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6594611, 'SK하이닉스 44주 매도', '2026-02-10 14:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6206931, 'NAVER 29주 매수', '2026-02-11 10:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6419637, '삼성전자 87주 매도', '2026-02-11 13:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3644453, '현대차 18주 매도', '2026-02-11 15:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6191729, '삼성전자 84주 매수', '2026-02-12 10:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3728359, '현대차 19주 매수', '2026-02-12 11:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6205931, '삼성전자 85주 매수', '2026-02-16 11:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3761436, '현대차 19주 매도', '2026-02-16 11:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6131080, '삼성전자 84주 매도', '2026-02-16 12:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3828926, '카카오 90주 매도', '2026-02-16 15:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3711457, '카카오 86주 매수', '2026-02-17 11:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6120918, 'NAVER 30주 매수', '2026-02-17 11:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5915113, 'NAVER 29주 매도', '2026-02-17 13:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6722991, 'SK하이닉스 41주 매도', '2026-02-18 15:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6212732, '삼성전자 87주 매수', '2026-02-19 11:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6068090, '삼성전자 85주 매도', '2026-02-19 12:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3596939, '현대차 18주 매수', '2026-02-20 09:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6176226, 'SK하이닉스 37주 매수', '2026-02-20 11:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3627544, '현대차 18주 매수', '2026-02-23 09:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6104084, 'NAVER 30주 매도', '2026-02-23 12:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3626456, '현대차 18주 매도', '2026-02-23 12:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6226166, 'SK하이닉스 37주 매도', '2026-02-24 10:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6076411, 'NAVER 29주 매수', '2026-02-24 11:49:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6149977, '삼성전자 87주 매도', '2026-02-24 13:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6179927, 'SK하이닉스 37주 매수', '2026-02-25 09:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3635245, '현대차 19주 매수', '2026-02-26 11:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6230934, '삼성전자 89주 매수', '2026-02-26 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3442883, '현대차 18주 매도', '2026-02-26 15:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6148922, 'NAVER 29주 매수', '2026-02-27 11:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3749038, '카카오 86주 매도', '2026-02-27 14:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6147078, 'NAVER 29주 매도', '2026-02-27 14:30:00');

-- ── 멤버 ────────────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write", "data:read", "backtest:run", "report:write"]', 'datetime(''now'', ''-60 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write", "data:read", "backtest:run"]', 'datetime(''now'', ''-45 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('treasury-agent', 'agent', 'default', 'treasury', '자금 관리', '🐳', 'active', '["approval:create", "data:read"]', 'datetime(''now'', ''-30 days'')');

-- ── 승인 대기 ──────────────────────────────────
INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES (
    'approval-login-01', 'strategy_adopt', 'pending',
    'strategy-dev-01',
    '모멘텀 돌파 전략 v2 채택 요청',
    '백테스트 결과 양호하여 채택 요청합니다.',
    '{"strategy_id": "momentum-v2"}',
    datetime('now', '-1 hours'),
    datetime('now', '+3 days')
);

INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES (
    'approval-login-02', 'budget_change', 'pending',
    'treasury-agent',
    'bot-momentum-01 예산 증액 요청',
    '운용 성과 양호하여 예산 증액 요청합니다.',
    '{"bot_id": "bot-momentum-01", "amount": 25000000}',
    datetime('now', '-2 hours'),
    datetime('now', '+3 days')
);
