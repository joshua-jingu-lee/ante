-- 시나리오: strategy-browse
-- 생성: generate_scenario.py (seed=42)
-- 생성일: 2026-03-18

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross-01', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'registered', '2026-01-17 09:00:00', 'SMA 5/20 크로스오버 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-02-01 09:00:00', '20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal-01', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', '2026-02-16 09:00:00', 'RSI 과매도 구간 반등 매수 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('mean-revert-01', '평균회귀', '1.2.0', 'strategies/mean_revert.py', 'inactive', '2026-01-17 09:00:00', '볼린저밴드 기반 평균회귀 전략', 'strategy-dev-02');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-browse', '모멘텀 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-browse", "strategy_id": "momentum-v2", "name": "모멘텀 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "000660", "035420"]}', 'running', '2026-02-01 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-browse', 'RSI 봇', 'rsi-reversal-01', 'paper', '{"bot_id": "bot-rsi-browse", "strategy_id": "rsi-reversal-01", "name": "RSI 봇", "bot_type": "paper", "interval_seconds": 60, "symbols": ["035720", "005380"]}', 'running', '2026-02-21 09:00:00');

-- ── 거래 내역 (150건) ────────────────────────
-- bot-momentum-browse: 77건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0001', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71900, 'filled', 561, '2025-12-18 11:17:00', '2025-12-18 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0002', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 160500, 'filled', 554, '2025-12-19 11:47:00', '2025-12-19 11:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0003', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 163600, 'filled', 564, '2025-12-22 10:05:00', '2025-12-22 10:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0004', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 22, 163600, 'filled', 540, '2025-12-22 11:12:00', '2025-12-22 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0005', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 17, 214000, 'filled', 546, '2025-12-23 11:17:00', '2025-12-23 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0006', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 73100, 'filled', 570, '2025-12-25 10:24:00', '2025-12-25 10:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0007', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 22, 159300, 'filled', 526, '2025-12-29 14:18:00', '2025-12-29 14:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0008', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 17, 210000, 'filled', 536, '2025-12-30 14:12:00', '2025-12-30 14:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0009', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71500, 'filled', 558, '2025-12-30 11:14:00', '2025-12-30 11:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0010', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 18, 207000, 'filled', 559, '2026-01-02 09:23:00', '2026-01-02 09:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0011', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 70200, 'filled', 548, '2026-01-05 15:41:00', '2026-01-05 15:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0012', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 53, 70200, 'filled', 558, '2026-01-05 11:46:00', '2026-01-05 11:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0013', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 18, 203500, 'filled', 549, '2026-01-06 15:44:00', '2026-01-06 15:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0014', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 18, 203500, 'filled', 549, '2026-01-06 09:14:00', '2026-01-06 09:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0015', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 155000, 'filled', 558, '2026-01-07 09:58:00', '2026-01-07 09:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0016', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 53, 71100, 'filled', 565, '2026-01-12 12:47:00', '2026-01-12 12:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0017', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 18, 211000, 'filled', 570, '2026-01-12 14:25:00', '2026-01-12 14:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0018', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 159400, 'filled', 574, '2026-01-12 11:32:00', '2026-01-12 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0019', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71100, 'filled', 555, '2026-01-12 09:09:00', '2026-01-12 09:09:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0020', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 17, 217000, 'filled', 553, '2026-01-14 11:29:00', '2026-01-14 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0021', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 70300, 'filled', 548, '2026-01-16 14:48:00', '2026-01-16 14:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0022', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 160800, 'filled', 555, '2026-01-16 09:18:00', '2026-01-16 09:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0023', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 17, 222500, 'filled', 567, '2026-01-20 10:55:00', '2026-01-20 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0024', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 70800, 'filled', 552, '2026-01-20 09:23:00', '2026-01-20 09:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0025', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 157700, 'filled', 544, '2026-01-22 10:07:00', '2026-01-22 10:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0026', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 159900, 'filled', 552, '2026-01-23 09:56:00', '2026-01-23 09:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0027', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 156000, 'filled', 538, '2026-01-26 14:49:00', '2026-01-26 14:49:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0028', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 229000, 'filled', 550, '2026-01-26 11:10:00', '2026-01-26 11:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0029', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 72400, 'filled', 565, '2026-01-27 11:59:00', '2026-01-27 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0030', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 51, 72400, 'filled', 554, '2026-01-27 11:19:00', '2026-01-27 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0031', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 155500, 'filled', 560, '2026-01-28 09:15:00', '2026-01-28 09:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0032', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 226500, 'filled', 544, '2026-01-29 11:00:00', '2026-01-29 11:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0033', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 226500, 'filled', 544, '2026-01-29 09:04:00', '2026-01-29 09:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0034', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 233000, 'filled', 559, '2026-01-30 15:31:00', '2026-01-30 15:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0035', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 233000, 'filled', 559, '2026-01-30 11:59:00', '2026-01-30 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0036', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 149400, 'filled', 538, '2026-02-02 13:12:00', '2026-02-02 13:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0037', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 25, 149400, 'filled', 560, '2026-02-02 10:26:00', '2026-02-02 10:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0038', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 51, 71600, 'filled', 548, '2026-02-03 10:03:00', '2026-02-03 10:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0039', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71600, 'filled', 558, '2026-02-03 09:15:00', '2026-02-03 09:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0040', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 229500, 'filled', 551, '2026-02-05 14:06:00', '2026-02-05 14:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0041', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 73600, 'filled', 574, '2026-02-05 14:53:00', '2026-02-05 14:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0042', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 50, 73600, 'filled', 552, '2026-02-05 09:10:00', '2026-02-05 09:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0043', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 25, 149400, 'filled', 560, '2026-02-06 10:10:00', '2026-02-06 10:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0044', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-02-06 10:59:00', '2026-02-06 10:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0045', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 153700, 'filled', 553, '2026-02-09 09:12:00', '2026-02-09 09:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0046', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 50, 72400, 'filled', 543, '2026-02-10 15:20:00', '2026-02-10 15:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0047', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 51, 72400, 'filled', 554, '2026-02-10 11:58:00', '2026-02-10 11:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0048', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 225000, 'filled', 540, '2026-02-12 10:56:00', '2026-02-12 10:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0049', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 225000, 'filled', 540, '2026-02-12 11:05:00', '2026-02-12 11:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0050', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 152000, 'filled', 547, '2026-02-13 11:42:00', '2026-02-13 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0051', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 152000, 'filled', 547, '2026-02-13 10:25:00', '2026-02-13 10:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0052', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 230500, 'filled', 553, '2026-02-17 10:04:00', '2026-02-17 10:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0053', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 230500, 'filled', 553, '2026-02-17 09:59:00', '2026-02-17 09:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0054', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 51, 76000, 'filled', 581, '2026-02-18 13:53:00', '2026-02-18 13:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0055', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 158100, 'filled', 569, '2026-02-18 12:39:00', '2026-02-18 12:39:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0056', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 152500, 'filled', 549, '2026-02-19 11:06:00', '2026-02-19 11:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0057', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 49, 75900, 'filled', 558, '2026-02-20 11:35:00', '2026-02-20 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0058', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 228000, 'filled', 547, '2026-02-23 15:40:00', '2026-02-23 15:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0059', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 49, 76400, 'filled', 562, '2026-02-23 12:57:00', '2026-02-23 12:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0060', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 156600, 'filled', 564, '2026-02-24 12:02:00', '2026-02-24 12:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0061', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 49, 76500, 'filled', 562, '2026-02-24 11:16:00', '2026-02-24 11:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0062', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-02-25 11:00:00', '2026-02-25 11:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0063', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 154600, 'filled', 557, '2026-02-26 10:37:00', '2026-02-26 10:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0064', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 157800, 'filled', 568, '2026-02-27 10:57:00', '2026-02-27 10:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0065', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 157800, 'filled', 544, '2026-02-27 11:06:00', '2026-02-27 11:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0066', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 227000, 'filled', 545, '2026-03-02 11:55:00', '2026-03-02 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0067', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 227000, 'filled', 545, '2026-03-02 10:01:00', '2026-03-02 10:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0068', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 49, 80300, 'filled', 590, '2026-03-03 15:55:00', '2026-03-03 15:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0069', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 223000, 'filled', 535, '2026-03-04 10:54:00', '2026-03-04 10:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0070', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 47, 78900, 'filled', 556, '2026-03-04 10:22:00', '2026-03-04 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0071', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 166800, 'filled', 575, '2026-03-05 10:42:00', '2026-03-05 10:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0072', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-03-05 10:55:00', '2026-03-05 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0073', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 47, 79600, 'filled', 561, '2026-03-06 14:25:00', '2026-03-06 14:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0074', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 22, 165300, 'filled', 545, '2026-03-06 09:07:00', '2026-03-06 09:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0075', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 22, 165200, 'filled', 545, '2026-03-09 12:02:00', '2026-03-09 12:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0076', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 22, 165200, 'filled', 545, '2026-03-09 10:46:00', '2026-03-09 10:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mome-0077', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 48, 78100, 'filled', 562, '2026-03-11 09:33:00', '2026-03-11 09:33:00');

-- bot-rsi-browse: 38건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0001', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 220000, 'filled', 165, '2025-12-18 11:48:00', '2025-12-18 11:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0002', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 50500, 'filled', 182, '2025-12-24 11:56:00', '2025-12-24 11:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0003', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 218000, 'filled', 163, '2025-12-29 11:45:00', '2025-12-29 11:45:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0004', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 218000, 'filled', 163, '2025-12-29 10:04:00', '2025-12-29 10:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0005', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 54500, 'filled', 196, '2025-12-31 14:11:00', '2025-12-31 14:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0006', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 22, 55300, 'filled', 182, '2026-01-01 10:41:00', '2026-01-01 10:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0007', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 213000, 'filled', 160, '2026-01-06 14:03:00', '2026-01-06 14:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0008', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 213000, 'filled', 160, '2026-01-06 11:38:00', '2026-01-06 11:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0009', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 22, 50600, 'filled', 167, '2026-01-08 13:31:00', '2026-01-08 13:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0010', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 50600, 'filled', 182, '2026-01-08 09:48:00', '2026-01-08 09:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0011', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 50700, 'filled', 183, '2026-01-13 10:02:00', '2026-01-13 10:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0012', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 50700, 'filled', 183, '2026-01-13 10:43:00', '2026-01-13 10:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0013', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 215000, 'filled', 161, '2026-01-14 14:21:00', '2026-01-14 14:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0014', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 214500, 'filled', 161, '2026-01-15 10:25:00', '2026-01-15 10:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0015', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 214500, 'filled', 161, '2026-01-19 14:19:00', '2026-01-19 14:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0016', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 214500, 'filled', 161, '2026-01-19 11:26:00', '2026-01-19 11:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0017', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 49150, 'filled', 177, '2026-01-21 10:48:00', '2026-01-21 10:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0018', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 26, 46550, 'filled', 182, '2026-01-22 11:54:00', '2026-01-22 11:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0019', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 197000, 'filled', 148, '2026-01-27 15:35:00', '2026-01-27 15:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0020', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 6, 197000, 'filled', 177, '2026-01-27 11:04:00', '2026-01-27 11:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0021', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 26, 51000, 'filled', 199, '2026-02-02 14:22:00', '2026-02-02 14:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0022', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 51000, 'filled', 184, '2026-02-02 11:51:00', '2026-02-02 11:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0023', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 6, 212500, 'filled', 191, '2026-02-09 14:43:00', '2026-02-09 14:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0024', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 49600, 'filled', 179, '2026-02-09 12:27:00', '2026-02-09 12:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0025', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 25, 49600, 'filled', 186, '2026-02-09 10:48:00', '2026-02-09 10:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0026', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 211000, 'filled', 158, '2026-02-10 09:55:00', '2026-02-10 09:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0027', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 25, 48500, 'filled', 182, '2026-02-17 14:19:00', '2026-02-17 14:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0028', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 25, 48500, 'filled', 182, '2026-02-17 10:02:00', '2026-02-17 10:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0029', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 25, 46800, 'filled', 175, '2026-02-18 13:53:00', '2026-02-18 13:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0030', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 26, 46800, 'filled', 183, '2026-02-18 10:52:00', '2026-02-18 10:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0031', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 206500, 'filled', 155, '2026-02-19 10:11:00', '2026-02-19 10:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0032', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 213500, 'filled', 160, '2026-02-20 11:47:00', '2026-02-20 11:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0033', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 26, 44600, 'filled', 174, '2026-02-23 10:05:00', '2026-02-23 10:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0034', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 28, 44600, 'filled', 187, '2026-02-23 09:32:00', '2026-02-23 09:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0035', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 207500, 'filled', 156, '2026-03-03 14:09:00', '2026-03-03 14:09:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0036', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 6, 201500, 'filled', 181, '2026-03-09 09:44:00', '2026-03-09 09:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0037', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 28, 48700, 'filled', 205, '2026-03-10 11:58:00', '2026-03-10 11:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-rsi--0038', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 25, 48700, 'filled', 183, '2026-03-10 10:19:00', '2026-03-10 10:19:00');

-- bot-mean-old: 35건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0001', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 37, 53700, 'filled', 298, '2025-12-18 09:04:00', '2025-12-18 09:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0002', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 37, 53100, 'filled', 295, '2025-12-19 10:40:00', '2025-12-19 10:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0003', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 37, 52700, 'filled', 292, '2025-12-23 11:34:00', '2025-12-23 11:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0004', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 26, 74900, 'filled', 292, '2025-12-25 11:11:00', '2025-12-25 11:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0005', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 37, 52000, 'filled', 289, '2025-12-29 13:52:00', '2025-12-29 13:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0006', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 38, 52000, 'filled', 296, '2025-12-29 11:07:00', '2025-12-29 11:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0007', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 26, 74000, 'filled', 289, '2025-12-31 12:32:00', '2025-12-31 12:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0008', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 38, 51900, 'filled', 296, '2026-01-02 15:19:00', '2026-01-02 15:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0009', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 208000, 'filled', 281, '2026-01-02 10:22:00', '2026-01-02 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0010', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 38, 51900, 'filled', 296, '2026-01-06 09:06:00', '2026-01-06 09:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0011', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 208500, 'filled', 281, '2026-01-07 10:57:00', '2026-01-07 10:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0012', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 211000, 'filled', 285, '2026-01-08 10:09:00', '2026-01-08 10:09:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0013', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 38, 51700, 'filled', 295, '2026-01-13 11:14:00', '2026-01-13 11:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0014', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 221000, 'filled', 298, '2026-01-14 15:27:00', '2026-01-14 15:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0015', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 27, 72300, 'filled', 293, '2026-01-14 09:21:00', '2026-01-14 09:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0016', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 27, 74000, 'filled', 300, '2026-01-16 11:42:00', '2026-01-16 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0017', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 220000, 'filled', 297, '2026-01-16 10:16:00', '2026-01-16 10:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0018', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 211500, 'filled', 286, '2026-01-20 15:10:00', '2026-01-20 15:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0019', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 27, 74000, 'filled', 300, '2026-01-20 11:32:00', '2026-01-20 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0020', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 217000, 'filled', 293, '2026-01-21 10:12:00', '2026-01-21 10:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0021', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 27, 76200, 'filled', 309, '2026-01-26 10:44:00', '2026-01-26 10:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0022', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 217500, 'filled', 294, '2026-01-28 15:05:00', '2026-01-28 15:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0023', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 33, 60500, 'filled', 299, '2026-01-29 11:32:00', '2026-01-29 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0024', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 217000, 'filled', 293, '2026-01-30 10:21:00', '2026-01-30 10:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0025', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 33, 59000, 'filled', 292, '2026-02-03 12:05:00', '2026-02-03 12:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0026', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 25, 80000, 'filled', 300, '2026-02-03 09:30:00', '2026-02-03 09:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0027', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 203000, 'filled', 274, '2026-02-05 10:01:00', '2026-02-05 10:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0028', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 32, 60900, 'filled', 292, '2026-02-06 09:39:00', '2026-02-06 09:39:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0029', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 25, 82200, 'filled', 308, '2026-02-09 12:58:00', '2026-02-09 12:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0030', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 202500, 'filled', 273, '2026-02-10 09:20:00', '2026-02-10 09:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0031', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 32, 59400, 'filled', 285, '2026-02-12 11:27:00', '2026-02-12 11:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0032', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 202000, 'filled', 273, '2026-02-13 13:11:00', '2026-02-13 13:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0033', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 24, 81300, 'filled', 293, '2026-02-13 09:43:00', '2026-02-13 09:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0034', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 24, 80100, 'filled', 288, '2026-02-16 15:02:00', '2026-02-16 15:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('t-bot-mean-0035', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 33, 59200, 'filled', 293, '2026-02-16 10:06:00', '2026-02-16 10:06:00');

-- ── 포지션 이력 (150건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71900, 0.0, '2025-12-18 11:17:00', '2025-12-18 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 160500, 0.0, '2025-12-19 11:47:00', '2025-12-19 11:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 163600, 62082, '2025-12-22 10:05:00', '2025-12-22 10:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 22, 163600, 0.0, '2025-12-22 11:12:00', '2025-12-22 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 17, 214000, 0.0, '2025-12-23 11:17:00', '2025-12-23 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 73100, 53087, '2025-12-25 10:24:00', '2025-12-25 10:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 22, 159300, -103187, '2025-12-29 14:18:00', '2025-12-29 14:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 17, 210000, -76747, '2025-12-30 14:12:00', '2025-12-30 14:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71500, 0.0, '2025-12-30 11:14:00', '2025-12-30 11:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 18, 207000, 0.0, '2026-01-02 09:23:00', '2026-01-02 09:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 70200, -76544, '2026-01-05 15:41:00', '2026-01-05 15:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 53, 70200, 0.0, '2026-01-05 11:46:00', '2026-01-05 11:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 18, 203500, -71974, '2026-01-06 15:44:00', '2026-01-06 15:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 18, 203500, 0.0, '2026-01-06 09:14:00', '2026-01-06 09:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 155000, 0.0, '2026-01-07 09:58:00', '2026-01-07 09:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 53, 71100, 38468, '2026-01-12 12:47:00', '2026-01-12 12:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 18, 211000, 125695, '2026-01-12 14:25:00', '2026-01-12 14:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 159400, 96227, '2026-01-12 11:32:00', '2026-01-12 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71100, 0.0, '2026-01-12 09:09:00', '2026-01-12 09:09:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 17, 217000, 0.0, '2026-01-14 11:29:00', '2026-01-14 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 70300, -50556, '2026-01-16 14:48:00', '2026-01-16 14:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 160800, 0.0, '2026-01-16 09:18:00', '2026-01-16 09:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 17, 222500, 84233, '2026-01-20 10:55:00', '2026-01-20 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 70800, 0.0, '2026-01-20 09:23:00', '2026-01-20 09:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 157700, -80186, '2026-01-22 10:07:00', '2026-01-22 10:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 159900, 0.0, '2026-01-23 09:56:00', '2026-01-23 09:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 156000, -98490, '2026-01-26 14:49:00', '2026-01-26 14:49:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 229000, 0.0, '2026-01-26 11:10:00', '2026-01-26 11:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 72400, 73976, '2026-01-27 11:59:00', '2026-01-27 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 51, 72400, 0.0, '2026-01-27 11:19:00', '2026-01-27 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 155500, 0.0, '2026-01-28 09:15:00', '2026-01-28 09:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 226500, -48879, '2026-01-29 11:00:00', '2026-01-29 11:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 226500, 0.0, '2026-01-29 09:04:00', '2026-01-29 09:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 233000, 94867, '2026-01-30 15:31:00', '2026-01-30 15:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 233000, 0.0, '2026-01-30 11:59:00', '2026-01-30 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 149400, -155185, '2026-02-02 13:12:00', '2026-02-02 13:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 25, 149400, 0.0, '2026-02-02 10:26:00', '2026-02-02 10:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 51, 71600, -49747, '2026-02-03 10:03:00', '2026-02-03 10:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71600, 0.0, '2026-02-03 09:15:00', '2026-02-03 09:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 229500, -64997, '2026-02-05 14:06:00', '2026-02-05 14:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 73600, 94623, '2026-02-05 14:53:00', '2026-02-05 14:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 50, 73600, 0.0, '2026-02-05 09:10:00', '2026-02-05 09:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 25, 149400, -9150, '2026-02-06 10:10:00', '2026-02-06 10:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 228000, 0.0, '2026-02-06 10:59:00', '2026-02-06 10:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 153700, 0.0, '2026-02-09 09:12:00', '2026-02-09 09:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 50, 72400, -68869, '2026-02-10 15:20:00', '2026-02-10 15:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 51, 72400, 0.0, '2026-02-10 11:58:00', '2026-02-10 11:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 225000, -56820, '2026-02-12 10:56:00', '2026-02-12 10:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 225000, 0.0, '2026-02-12 11:05:00', '2026-02-12 11:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 152000, -49737, '2026-02-13 11:42:00', '2026-02-13 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 152000, 0.0, '2026-02-13 10:25:00', '2026-02-13 10:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 230500, 78965, '2026-02-17 10:04:00', '2026-02-17 10:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 230500, 0.0, '2026-02-17 09:59:00', '2026-02-17 09:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 51, 76000, 174104, '2026-02-18 13:53:00', '2026-02-18 13:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 158100, 137104, '2026-02-18 12:39:00', '2026-02-18 12:39:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 152500, 0.0, '2026-02-19 11:06:00', '2026-02-19 11:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 49, 75900, 0.0, '2026-02-20 11:35:00', '2026-02-20 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 228000, -48937, '2026-02-23 15:40:00', '2026-02-23 15:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 49, 76400, 15328, '2026-02-23 12:57:00', '2026-02-23 12:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 156600, 89192, '2026-02-24 12:02:00', '2026-02-24 12:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 49, 76500, 0.0, '2026-02-24 11:16:00', '2026-02-24 11:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 228000, 0.0, '2026-02-25 11:00:00', '2026-02-25 11:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 154600, 0.0, '2026-02-26 10:37:00', '2026-02-26 10:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 157800, 67521, '2026-02-27 10:57:00', '2026-02-27 10:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 157800, 0.0, '2026-02-27 11:06:00', '2026-02-27 11:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 227000, -24899, '2026-03-02 11:55:00', '2026-03-02 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 227000, 0.0, '2026-03-02 10:01:00', '2026-03-02 10:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 49, 80300, 176560, '2026-03-03 15:55:00', '2026-03-03 15:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 223000, -72741, '2026-03-04 10:54:00', '2026-03-04 10:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 47, 78900, 0.0, '2026-03-04 10:22:00', '2026-03-04 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 166800, 197601, '2026-03-05 10:42:00', '2026-03-05 10:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 228000, 0.0, '2026-03-05 10:55:00', '2026-03-05 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 47, 79600, 23734, '2026-03-06 14:25:00', '2026-03-06 14:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 22, 165300, 0.0, '2026-03-06 09:07:00', '2026-03-06 09:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 22, 165200, -11104, '2026-03-09 12:02:00', '2026-03-09 12:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 22, 165200, 0.0, '2026-03-09 10:46:00', '2026-03-09 10:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 48, 78100, 0.0, '2026-03-11 09:33:00', '2026-03-11 09:33:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 220000, 0.0, '2025-12-18 11:48:00', '2025-12-18 11:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 50500, 0.0, '2025-12-24 11:56:00', '2025-12-24 11:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 218000, -12670, '2025-12-29 11:45:00', '2025-12-29 11:45:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 218000, 0.0, '2025-12-29 10:04:00', '2025-12-29 10:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 54500, 92796, '2025-12-31 14:11:00', '2025-12-31 14:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 22, 55300, 0.0, '2026-01-01 10:41:00', '2026-01-01 10:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 213000, -27610, '2026-01-06 14:03:00', '2026-01-06 14:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 213000, 0.0, '2026-01-06 11:38:00', '2026-01-06 11:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 22, 50600, -106127, '2026-01-08 13:31:00', '2026-01-08 13:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 50600, 0.0, '2026-01-08 09:48:00', '2026-01-08 09:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 50700, -582, '2026-01-13 10:02:00', '2026-01-13 10:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 50700, 0.0, '2026-01-13 10:43:00', '2026-01-13 10:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 215000, 7367, '2026-01-14 14:21:00', '2026-01-14 14:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 214500, 0.0, '2026-01-15 10:25:00', '2026-01-15 10:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 214500, -2628, '2026-01-19 14:19:00', '2026-01-19 14:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 214500, 0.0, '2026-01-19 11:26:00', '2026-01-19 11:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 49150, -40090, '2026-01-21 10:48:00', '2026-01-21 10:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 26, 46550, 0.0, '2026-01-22 11:54:00', '2026-01-22 11:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 197000, -89914, '2026-01-27 15:35:00', '2026-01-27 15:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 6, 197000, 0.0, '2026-01-27 11:04:00', '2026-01-27 11:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 26, 51000, 112451, '2026-02-02 14:22:00', '2026-02-02 14:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 51000, 0.0, '2026-02-02 11:51:00', '2026-02-02 11:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 6, 212500, 89877, '2026-02-09 14:43:00', '2026-02-09 14:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 49600, -36517, '2026-02-09 12:27:00', '2026-02-09 12:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 25, 49600, 0.0, '2026-02-09 10:48:00', '2026-02-09 10:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 211000, 0.0, '2026-02-10 09:55:00', '2026-02-10 09:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 25, 48500, -30471, '2026-02-17 14:19:00', '2026-02-17 14:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 25, 48500, 0.0, '2026-02-17 10:02:00', '2026-02-17 10:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 25, 46800, -45366, '2026-02-18 13:53:00', '2026-02-18 13:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 26, 46800, 0.0, '2026-02-18 10:52:00', '2026-02-18 10:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 206500, -25030, '2026-02-19 10:11:00', '2026-02-19 10:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 213500, 0.0, '2026-02-20 11:47:00', '2026-02-20 11:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 26, 44600, -60041, '2026-02-23 10:05:00', '2026-02-23 10:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 28, 44600, 0.0, '2026-02-23 09:32:00', '2026-02-23 09:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 207500, -32542, '2026-03-03 14:09:00', '2026-03-03 14:09:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 6, 201500, 0.0, '2026-03-09 09:44:00', '2026-03-09 09:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 28, 48700, 111459, '2026-03-10 11:58:00', '2026-03-10 11:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 25, 48700, 0.0, '2026-03-10 10:19:00', '2026-03-10 10:19:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 37, 53700, 0.0, '2025-12-18 09:04:00', '2025-12-18 09:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 37, 53100, -27014, '2025-12-19 10:40:00', '2025-12-19 10:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 37, 52700, 0.0, '2025-12-23 11:34:00', '2025-12-23 11:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 26, 74900, 0.0, '2025-12-25 11:11:00', '2025-12-25 11:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 37, 52000, -30614, '2025-12-29 13:52:00', '2025-12-29 13:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 38, 52000, 0.0, '2025-12-29 11:07:00', '2025-12-29 11:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 26, 74000, -28114, '2025-12-31 12:32:00', '2025-12-31 12:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 38, 51900, -8632, '2026-01-02 15:19:00', '2026-01-02 15:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 208000, 0.0, '2026-01-02 10:22:00', '2026-01-02 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 38, 51900, 0.0, '2026-01-06 09:06:00', '2026-01-06 09:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 208500, -97, '2026-01-07 10:57:00', '2026-01-07 10:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 211000, 0.0, '2026-01-08 10:09:00', '2026-01-08 10:09:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 38, 51700, -12414, '2026-01-13 11:14:00', '2026-01-13 11:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 221000, 85127, '2026-01-14 15:27:00', '2026-01-14 15:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 27, 72300, 0.0, '2026-01-14 09:21:00', '2026-01-14 09:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 27, 74000, 41005, '2026-01-16 11:42:00', '2026-01-16 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 220000, 0.0, '2026-01-16 10:16:00', '2026-01-16 10:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 211500, -81164, '2026-01-20 15:10:00', '2026-01-20 15:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 27, 74000, 0.0, '2026-01-20 11:32:00', '2026-01-20 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 217000, 0.0, '2026-01-21 10:12:00', '2026-01-21 10:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 27, 76200, 54359, '2026-01-26 10:44:00', '2026-01-26 10:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 217500, -296, '2026-01-28 15:05:00', '2026-01-28 15:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 33, 60500, 0.0, '2026-01-29 11:32:00', '2026-01-29 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 217000, 0.0, '2026-01-30 10:21:00', '2026-01-30 10:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 33, 59000, -54270, '2026-02-03 12:05:00', '2026-02-03 12:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 25, 80000, 0.0, '2026-02-03 09:30:00', '2026-02-03 09:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 203000, -130476, '2026-02-05 10:01:00', '2026-02-05 10:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 32, 60900, 0.0, '2026-02-06 09:39:00', '2026-02-06 09:39:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 25, 82200, 49966, '2026-02-09 12:58:00', '2026-02-09 12:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 202500, 0.0, '2026-02-10 09:20:00', '2026-02-10 09:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 32, 59400, -52657, '2026-02-12 11:27:00', '2026-02-12 11:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 202000, -8954, '2026-02-13 13:11:00', '2026-02-13 13:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 24, 81300, 0.0, '2026-02-13 09:43:00', '2026-02-13 09:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 24, 80100, -33510, '2026-02-16 15:02:00', '2026-02-16 15:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 33, 59200, 0.0, '2026-02-16 10:06:00', '2026-02-16 10:06:00');

-- ── 최종 포지션 (8건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-browse', '035420', 16, 228000, 0.0, '2026-03-11 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-browse', '000660', 22, 165200, 0.0, '2026-03-11 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-browse', '005930', 48, 78100, 0.0, '2026-03-11 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-browse', '005380', 6, 201500, 0.0, '2026-03-11 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-browse', '035720', 25, 48700, 0.0, '2026-03-11 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-old', '035720', 33, 59200, 0.0, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-old', '035420', 0, 0.0, -135860, '2026-02-18 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-old', '005930', 0, 0.0, 83706, '2026-02-18 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-browse', 15000000, 0, 0.0, 147348398, 136759718);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-browse', 5000000, 47860, 0.0, 23346702, 20821062);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 50000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 20000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 30000000);

-- ── 자금 변동 이력 (117건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'allocate', 15000000, '초기 할당', '2025-12-18 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'allocate', 5000000, '초기 할당', '2025-12-18 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3739361, '삼성전자 52주 매수', '2025-12-18 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1100165, '현대차 5주 매수', '2025-12-18 11:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3692054, 'SK하이닉스 23주 매수', '2025-12-19 11:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3762236, 'SK하이닉스 23주 매도', '2025-12-22 10:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3599740, 'SK하이닉스 22주 매수', '2025-12-22 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3638546, 'NAVER 17주 매수', '2025-12-23 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1212182, '카카오 24주 매수', '2025-12-24 11:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3800630, '삼성전자 52주 매도', '2025-12-25 10:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1090163, '현대차 5주 매수', '2025-12-29 10:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1089837, '현대차 5주 매도', '2025-12-29 11:45:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3504074, 'SK하이닉스 22주 매도', '2025-12-29 14:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3718558, '삼성전자 52주 매수', '2025-12-30 11:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3569464, 'NAVER 17주 매도', '2025-12-30 14:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1307804, '카카오 24주 매도', '2025-12-31 14:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1216782, '카카오 22주 매수', '2026-01-01 10:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3726559, 'NAVER 18주 매수', '2026-01-02 09:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3721158, '삼성전자 53주 매수', '2026-01-05 11:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3649852, '삼성전자 52주 매도', '2026-01-05 15:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3663549, 'NAVER 18주 매수', '2026-01-06 09:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1065160, '현대차 5주 매수', '2026-01-06 11:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1064840, '현대차 5주 매도', '2026-01-06 14:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3662451, 'NAVER 18주 매도', '2026-01-06 15:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3720558, 'SK하이닉스 24주 매수', '2026-01-07 09:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1214582, '카카오 24주 매수', '2026-01-08 09:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1113033, '카카오 22주 매도', '2026-01-08 13:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3697755, '삼성전자 52주 매수', '2026-01-12 09:09:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3825026, 'SK하이닉스 24주 매도', '2026-01-12 11:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3767735, '삼성전자 53주 매도', '2026-01-12 12:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3797430, 'NAVER 18주 매도', '2026-01-12 14:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1216617, '카카오 24주 매도', '2026-01-13 10:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1216983, '카카오 24주 매수', '2026-01-13 10:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3689553, 'NAVER 17주 매수', '2026-01-14 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1074839, '현대차 5주 매도', '2026-01-14 14:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1072661, '현대차 5주 매수', '2026-01-15 10:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3698955, 'SK하이닉스 23주 매수', '2026-01-16 09:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3655052, '삼성전자 52주 매도', '2026-01-16 14:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1072661, '현대차 5주 매수', '2026-01-19 11:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1072339, '현대차 5주 매도', '2026-01-19 14:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3682152, '삼성전자 52주 매수', '2026-01-20 09:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3781933, 'NAVER 17주 매도', '2026-01-20 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1179423, '카카오 24주 매도', '2026-01-21 10:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3626556, 'SK하이닉스 23주 매도', '2026-01-22 10:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1210482, '카카오 26주 매수', '2026-01-22 11:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3678252, 'SK하이닉스 23주 매수', '2026-01-23 09:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3664550, 'NAVER 16주 매수', '2026-01-26 11:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3587462, 'SK하이닉스 23주 매도', '2026-01-26 14:49:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1182177, '현대차 6주 매수', '2026-01-27 11:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3692954, '삼성전자 51주 매수', '2026-01-27 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3764235, '삼성전자 52주 매도', '2026-01-27 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 984852, '현대차 5주 매도', '2026-01-27 15:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3732560, 'SK하이닉스 24주 매수', '2026-01-28 09:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3624544, 'NAVER 16주 매수', '2026-01-29 09:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3623456, 'NAVER 16주 매도', '2026-01-29 11:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3728559, 'NAVER 16주 매수', '2026-01-30 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3727441, 'NAVER 16주 매도', '2026-01-30 15:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3735560, 'SK하이닉스 25주 매수', '2026-02-02 10:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1224184, '카카오 24주 매수', '2026-02-02 11:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3585062, 'SK하이닉스 24주 매도', '2026-02-02 13:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1325801, '카카오 26주 매도', '2026-02-02 14:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3723758, '삼성전자 52주 매수', '2026-02-03 09:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3651052, '삼성전자 51주 매도', '2026-02-03 10:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3680552, '삼성전자 50주 매수', '2026-02-05 09:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3671449, 'NAVER 16주 매도', '2026-02-05 14:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3826626, '삼성전자 52주 매도', '2026-02-05 14:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3734440, 'SK하이닉스 25주 매도', '2026-02-06 10:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3648547, 'NAVER 16주 매수', '2026-02-06 10:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3689353, 'SK하이닉스 24주 매수', '2026-02-09 09:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1240186, '카카오 25주 매수', '2026-02-09 10:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1190221, '카카오 24주 매도', '2026-02-09 12:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1274809, '현대차 6주 매도', '2026-02-09 14:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1055158, '현대차 5주 매수', '2026-02-10 09:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3692954, '삼성전자 51주 매수', '2026-02-10 11:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3619457, '삼성전자 50주 매도', '2026-02-10 15:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3599460, 'NAVER 16주 매도', '2026-02-12 10:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3600540, 'NAVER 16주 매수', '2026-02-12 11:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3648547, 'SK하이닉스 24주 매수', '2026-02-13 10:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3647453, 'SK하이닉스 24주 매도', '2026-02-13 11:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3688553, 'NAVER 16주 매수', '2026-02-17 09:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1212682, '카카오 25주 매수', '2026-02-17 10:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3687447, 'NAVER 16주 매도', '2026-02-17 10:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1212318, '카카오 25주 매도', '2026-02-17 14:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1216983, '카카오 26주 매수', '2026-02-18 10:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3793831, 'SK하이닉스 24주 매도', '2026-02-18 12:39:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3875419, '삼성전자 51주 매도', '2026-02-18 13:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1169825, '카카오 25주 매도', '2026-02-18 13:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1032345, '현대차 5주 매도', '2026-02-19 10:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3660549, 'SK하이닉스 24주 매수', '2026-02-19 11:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3719658, '삼성전자 49주 매수', '2026-02-20 11:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1067660, '현대차 5주 매수', '2026-02-20 11:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1248987, '카카오 28주 매수', '2026-02-23 09:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1159426, '카카오 26주 매도', '2026-02-23 10:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3743038, '삼성전자 49주 매도', '2026-02-23 12:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3647453, 'NAVER 16주 매도', '2026-02-23 15:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3749062, '삼성전자 49주 매수', '2026-02-24 11:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3757836, 'SK하이닉스 24주 매도', '2026-02-24 12:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3648547, 'NAVER 16주 매수', '2026-02-25 11:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3710957, 'SK하이닉스 24주 매수', '2026-02-26 10:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3786632, 'SK하이닉스 24주 매도', '2026-02-27 10:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3629944, 'SK하이닉스 23주 매수', '2026-02-27 11:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3632545, 'NAVER 16주 매수', '2026-03-02 10:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3631455, 'NAVER 16주 매도', '2026-03-02 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1037344, '현대차 5주 매도', '2026-03-03 14:09:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3934110, '삼성전자 49주 매도', '2026-03-03 15:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3708856, '삼성전자 47주 매수', '2026-03-04 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3567465, 'NAVER 16주 매도', '2026-03-04 10:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3835825, 'SK하이닉스 23주 매도', '2026-03-05 10:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3648547, 'NAVER 16주 매수', '2026-03-05 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3637145, 'SK하이닉스 22주 매수', '2026-03-06 09:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3740639, '삼성전자 47주 매도', '2026-03-06 14:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1209181, '현대차 6주 매수', '2026-03-09 09:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3634945, 'SK하이닉스 22주 매수', '2026-03-09 10:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3633855, 'SK하이닉스 22주 매도', '2026-03-09 12:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1217683, '카카오 25주 매수', '2026-03-10 10:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1363395, '카카오 28주 매도', '2026-03-10 11:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3749362, '삼성전자 48주 매수', '2026-03-11 09:33:00');

-- ── 이벤트 로그 (24건) ──────────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-001', 'bot.step.success', '2025-12-18 11:17:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-002', 'bot.step.success', '2025-12-25 10:24:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-003', 'bot.step.success', '2026-01-05 15:41:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-004', 'bot.step.success', '2026-01-12 12:47:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-005', 'bot.step.success', '2026-01-16 14:48:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-006', 'bot.step.success', '2026-01-23 09:56:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-007', 'bot.step.success', '2026-01-28 09:15:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-008', 'bot.step.success', '2026-02-02 13:12:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-009', 'bot.step.success', '2026-02-05 14:53:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-010', 'bot.step.success', '2026-02-10 15:20:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-011', 'bot.step.success', '2026-02-13 10:25:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-012', 'bot.step.success', '2026-02-19 11:06:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-013', 'bot.step.success', '2026-02-24 11:16:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-014', 'bot.step.success', '2026-03-02 11:55:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-015', 'bot.step.success', '2026-03-05 10:42:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-016', 'bot.step.success', '2026-03-09 10:46:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--001', 'bot.step.success', '2025-12-18 11:48:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--002', 'bot.step.success', '2026-01-01 10:41:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--003', 'bot.step.success', '2026-01-13 10:02:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--004', 'bot.step.success', '2026-01-19 11:26:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--005', 'bot.step.success', '2026-02-02 14:22:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--006', 'bot.step.success', '2026-02-10 09:55:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--007', 'bot.step.success', '2026-02-19 10:11:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--008', 'bot.step.success', '2026-03-09 09:44:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');

-- ── 멤버 ────────────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write", "data:read", "backtest:run", "report:write"]', 'datetime(''now'', ''-60 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write", "data:read", "backtest:run"]', 'datetime(''now'', ''-45 days'')');
