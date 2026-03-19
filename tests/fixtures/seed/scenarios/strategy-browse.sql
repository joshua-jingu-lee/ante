-- 시나리오: strategy-browse
-- 생성: generate_scenario.py (seed=42)
-- 생성일: 2026-03-19

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross-01', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'registered', '2026-01-18 09:00:00', 'SMA 5/20 크로스오버 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-02-02 09:00:00', '20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal-01', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', '2026-02-17 09:00:00', 'RSI 과매도 구간 반등 매수 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('mean-revert-01', '평균회귀', '1.2.0', 'strategies/mean_revert.py', 'inactive', '2026-01-18 09:00:00', '볼린저밴드 기반 평균회귀 전략', 'strategy-dev-02');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-browse', '모멘텀 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-browse", "strategy_id": "momentum-v2", "name": "모멘텀 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "000660", "035420"]}', 'running', '2026-02-02 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-browse', 'RSI 봇', 'rsi-reversal-01', 'paper', '{"bot_id": "bot-rsi-browse", "strategy_id": "rsi-reversal-01", "name": "RSI 봇", "bot_type": "paper", "interval_seconds": 60, "symbols": ["035720", "005380"]}', 'running', '2026-02-22 09:00:00');

-- ── 거래 내역 (153건) ────────────────────────
-- bot-momentum-browse: 82건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a803ad04-c6f6-5bb7-ad82-f87b689c887b', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71900, 'filled', 561, '2025-12-19 11:17:00', '2025-12-19 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9a70bca9-4a10-535e-8c7d-9fd0ea28dbda', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 160500, 'filled', 554, '2025-12-22 11:27:00', '2025-12-22 11:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8c2d74e8-4c48-58cc-9a8d-b5a6d2c12b7a', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 71600, 'filled', 558, '2025-12-23 14:01:00', '2025-12-23 14:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('36d2b8bc-974f-5278-89b8-9356d0ec0d17', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 163600, 'filled', 564, '2025-12-23 15:41:00', '2025-12-23 15:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aec44eda-8fa0-5801-b470-447ffa3c2525', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 22, 163600, 'filled', 540, '2025-12-23 09:28:00', '2025-12-23 09:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b8796a3-6f78-52d3-ba3a-6768daa84396', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 17, 219500, 'filled', 560, '2025-12-25 10:09:00', '2025-12-25 10:09:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8530525e-fc21-544e-8392-44ad4601b6f0', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 51, 73100, 'filled', 559, '2025-12-26 10:38:00', '2025-12-26 10:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c8092f4a-10f2-5ffc-b498-0455485ab26f', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 17, 216000, 'filled', 551, '2025-12-29 10:35:00', '2025-12-29 10:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e170ad1f-6441-5158-a3cc-9dce4df82cd6', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 17, 216000, 'filled', 551, '2025-12-29 11:12:00', '2025-12-29 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7712478d-610a-56a8-b076-02aae5914c47', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 22, 159300, 'filled', 526, '2025-12-30 10:54:00', '2025-12-30 10:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('437d1658-1b76-5b14-84fd-24f68e8fb8bc', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 51, 73700, 'filled', 564, '2025-12-30 10:24:00', '2025-12-30 10:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('88a305dd-e794-55da-a122-c8cc138f537d', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 159300, 'filled', 550, '2025-12-30 09:23:00', '2025-12-30 09:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39727373-84d4-5790-a65c-9c4e51cdce92', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71500, 'filled', 558, '2025-12-31 11:40:00', '2025-12-31 11:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8f9a70a5-7b4a-54ce-9a3a-e71fcfd786d6', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 17, 211000, 'filled', 538, '2026-01-01 15:44:00', '2026-01-01 15:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5fe362c5-8aef-514c-a16d-4d8a0264828f', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 17, 211000, 'filled', 538, '2026-01-01 09:14:00', '2026-01-01 09:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9d6aaec5-5aed-587e-b0e5-03a0eeea3f1f', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 153000, 'filled', 528, '2026-01-05 11:41:00', '2026-01-05 11:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ca4230d1-7bae-5f70-99bf-07d857325955', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 153000, 'filled', 551, '2026-01-05 09:16:00', '2026-01-05 09:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('72aafdd0-fac0-5556-8bf5-601ff0071c9f', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 70200, 'filled', 548, '2026-01-06 13:57:00', '2026-01-06 13:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('402e0815-2f8e-5c03-a226-581ae13487a4', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 53, 70200, 'filled', 558, '2026-01-06 09:08:00', '2026-01-06 09:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1fe78282-3b83-550f-b663-953e320e48ca', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 152500, 'filled', 549, '2026-01-07 15:27:00', '2026-01-07 15:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fa56a5b8-7613-5264-91c4-a4adc7aa4108', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 53, 69600, 'filled', 553, '2026-01-07 13:24:00', '2026-01-07 13:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('db35cb38-51f3-58a1-91cd-83d232dcab70', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 152500, 'filled', 549, '2026-01-07 11:16:00', '2026-01-07 11:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0db2a51d-b3cd-5db9-872e-96ec6eff9e7b', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 53, 70300, 'filled', 559, '2026-01-08 11:56:00', '2026-01-08 11:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0b37ad4c-a089-555b-98f8-325348e201d2', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 17, 206000, 'filled', 525, '2026-01-12 12:32:00', '2026-01-12 12:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7f2a9d2f-b3e9-5f4d-8273-cecaef5309c6', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 18, 206000, 'filled', 556, '2026-01-12 11:19:00', '2026-01-12 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aa21ce21-6b87-5d9f-bf91-22378d60e952', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 53, 71100, 'filled', 565, '2026-01-13 11:34:00', '2026-01-13 11:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('cf92a519-a695-5272-ab5a-90291df40adc', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71700, 'filled', 559, '2026-01-14 09:07:00', '2026-01-14 09:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c82c52cd-6283-592d-9a51-40d8a9006e39', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 18, 216500, 'filled', 585, '2026-01-16 13:52:00', '2026-01-16 13:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9070683e-d9cd-5f36-a905-316f42c4b521', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 17, 216500, 'filled', 552, '2026-01-16 09:42:00', '2026-01-16 09:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7cdc81cd-4271-542e-a935-d945081f1058', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 70300, 'filled', 548, '2026-01-19 11:59:00', '2026-01-19 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a0f6caf5-0ab3-5571-94e0-09c2ea80afc9', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 17, 221000, 'filled', 564, '2026-01-19 15:44:00', '2026-01-19 15:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('48da81a7-1ab2-52b0-9145-3570d489962b', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 221000, 'filled', 530, '2026-01-19 10:42:00', '2026-01-19 10:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8127f3dc-46fb-569a-a327-2fbddee1cd09', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 162700, 'filled', 586, '2026-01-20 10:15:00', '2026-01-20 10:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39e396ed-2fbe-5f8b-9498-e40423041638', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 162700, 'filled', 561, '2026-01-20 09:37:00', '2026-01-20 09:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9ace70f0-e70c-554d-968e-d5124d56bc05', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 70800, 'filled', 552, '2026-01-21 09:04:00', '2026-01-21 09:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('57fb0c35-2604-57a4-ba01-fc3458ed9411', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 71800, 'filled', 560, '2026-01-22 15:31:00', '2026-01-22 15:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('f264590a-e9b8-585f-b842-6b6f7773b8f4', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71800, 'filled', 560, '2026-01-22 11:59:00', '2026-01-22 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b0d8b6a9-67b2-5d75-bff5-6f6a837d3349', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 159900, 'filled', 552, '2026-01-26 13:29:00', '2026-01-26 13:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('68477f5c-b3bf-52a5-b275-89d290c27047', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 71700, 'filled', 559, '2026-01-26 10:43:00', '2026-01-26 10:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8aa0d94e-2f79-5170-a26c-2be55b9993ce', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 52, 71700, 'filled', 559, '2026-01-26 09:25:00', '2026-01-26 09:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6194eeb4-8f00-515d-8af3-4043c440923c', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 229000, 'filled', 550, '2026-01-27 11:12:00', '2026-01-27 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4a8d8622-dcfc-5e0d-be3d-7aef2b8cb184', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 156000, 'filled', 562, '2026-01-27 10:11:00', '2026-01-27 10:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099625e2-1608-5e9f-a66f-9654a4e81798', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 221500, 'filled', 532, '2026-01-29 11:34:00', '2026-01-29 11:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('393b488a-2a76-5981-a46f-34829415b07b', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 149200, 'filled', 537, '2026-02-02 13:57:00', '2026-02-02 13:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8e49e161-d1f5-5372-b438-494c3f5fcfe5', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 25, 149200, 'filled', 560, '2026-02-02 09:24:00', '2026-02-02 09:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2c40ac3c-76f6-5567-9b6a-0a77d0cd2e89', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 52, 72700, 'filled', 567, '2026-02-03 15:50:00', '2026-02-03 15:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e1458b94-f14f-51ce-9896-b27e8aa4d3f6', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 51, 72700, 'filled', 556, '2026-02-03 09:12:00', '2026-02-03 09:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2e6e1dbd-0b22-5ca4-b5ae-194b150512b3', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 225500, 'filled', 541, '2026-02-04 15:20:00', '2026-02-04 15:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6487d438-6b7e-56ce-a1fc-7ebf717618ce', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 225500, 'filled', 541, '2026-02-04 11:58:00', '2026-02-04 11:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1e33fbad-957c-54dd-adb8-92a8bbaddb2d', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 51, 73000, 'filled', 558, '2026-02-05 11:04:00', '2026-02-05 11:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0f14fe74-8e3b-5011-8b3b-8513d4d7519f', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 51, 73000, 'filled', 558, '2026-02-05 10:07:00', '2026-02-05 10:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b401315-60ce-5cf6-9779-0fb3db8c6033', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 25, 149400, 'filled', 560, '2026-02-09 12:59:00', '2026-02-09 12:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b779fd40-0484-5c5d-a53a-82733f4eb064', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 228000, 'filled', 547, '2026-02-09 15:45:00', '2026-02-09 15:45:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('53192086-1933-54b0-8514-f0ce05553347', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-02-09 10:08:00', '2026-02-09 10:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('980a0d7b-226c-5045-bdfb-31722675a9a5', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 153700, 'filled', 553, '2026-02-10 09:29:00', '2026-02-10 09:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b96a9387-a880-5b5e-9c4b-4982bbe4ecf3', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 51, 72400, 'filled', 554, '2026-02-11 14:16:00', '2026-02-11 14:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a0c4ef04-e7e0-5238-8cb1-08f4ce69494c', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 51, 72400, 'filled', 554, '2026-02-11 09:23:00', '2026-02-11 09:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d433343f-6837-55c9-b629-7e1c6f7de0c9', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 227000, 'filled', 545, '2026-02-12 15:33:00', '2026-02-12 15:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9db948e2-c621-534c-89e2-7a928fb1a0b4', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 227000, 'filled', 545, '2026-02-12 11:06:00', '2026-02-12 11:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d10d9f3b-658e-5907-9a5f-775c073e5f56', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 51, 74000, 'filled', 566, '2026-02-13 14:09:00', '2026-02-13 14:09:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('49bf3b48-0cb4-567c-b6b5-90e6c2461b43', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 225000, 'filled', 540, '2026-02-13 14:13:00', '2026-02-13 14:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2ed32da0-b938-5629-bb4e-814dde1d763d', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 50, 74000, 'filled', 555, '2026-02-13 11:40:00', '2026-02-13 11:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('89f63f4a-4fc6-5e1b-93aa-d269b48cd2d8', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 229000, 'filled', 550, '2026-02-16 09:40:00', '2026-02-16 09:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('24233958-8e2a-50c3-ad32-57e116ac69e6', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 153600, 'filled', 553, '2026-02-17 15:16:00', '2026-02-17 15:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('26c47405-cef8-54bd-9d83-822d51d1494b', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 50, 74700, 'filled', 560, '2026-02-17 13:35:00', '2026-02-17 13:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('722668f2-ba18-5aee-8690-52fb586010e1', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 50, 74700, 'filled', 560, '2026-02-17 09:56:00', '2026-02-17 09:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('15fc72b9-6d5e-5fd7-a117-b471d9529649', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 23, 160000, 'filled', 552, '2026-02-18 11:35:00', '2026-02-18 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c70d8789-9c28-5233-b792-85ad57e5d52a', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 23, 152500, 'filled', 526, '2026-02-20 10:22:00', '2026-02-20 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('3166d2b1-451a-5f2e-b95f-1837e4e72724', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 50, 75900, 'filled', 569, '2026-02-23 11:59:00', '2026-02-23 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b9b69623-00a2-5760-8aa1-377df4d02d6b', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 228000, 'filled', 547, '2026-02-24 11:56:00', '2026-02-24 11:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('32b026be-6534-5213-b379-b949a1b1a079', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 49, 76400, 'filled', 562, '2026-02-24 11:59:00', '2026-02-24 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c5c8e7a5-8d22-5fe3-8705-4d1dddb0041e', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 24, 154600, 'filled', 557, '2026-02-27 10:55:00', '2026-02-27 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('045be7ba-68e6-59f0-a717-85b32e5f185d', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 49, 80300, 'filled', 590, '2026-03-02 13:22:00', '2026-03-02 13:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('81771c09-93b5-5cfc-8614-1d153d150617', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 46, 80300, 'filled', 554, '2026-03-02 09:01:00', '2026-03-02 09:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('27d8614b-537b-5b42-8e6c-04b09b7d7ab4', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 16, 227000, 'filled', 545, '2026-03-03 10:22:00', '2026-03-03 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0a5ff33b-129c-5893-85a6-df2195c00feb', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 46, 78400, 'filled', 541, '2026-03-06 15:50:00', '2026-03-06 15:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d1739928-2c07-56d1-b551-fd2313990991', 'bot-momentum-browse', 'momentum-v2', '035420', 'sell', 16, 228000, 'filled', 547, '2026-03-06 14:32:00', '2026-03-06 14:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('69f966d0-1d48-52bb-ba59-48536ae1afc2', 'bot-momentum-browse', 'momentum-v2', '005930', 'buy', 47, 78400, 'filled', 553, '2026-03-06 10:02:00', '2026-03-06 10:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('32db653c-0772-505f-8856-9f91a7b5dc3d', 'bot-momentum-browse', 'momentum-v2', '005930', 'sell', 47, 79600, 'filled', 561, '2026-03-09 15:47:00', '2026-03-09 15:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a777158d-233c-5df5-abf7-f281d64d94ef', 'bot-momentum-browse', 'momentum-v2', '000660', 'sell', 24, 165200, 'filled', 595, '2026-03-10 15:58:00', '2026-03-10 15:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('f4eab4b4-b4dc-5816-8c16-e22bea697375', 'bot-momentum-browse', 'momentum-v2', '000660', 'buy', 22, 165200, 'filled', 545, '2026-03-10 11:54:00', '2026-03-10 11:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5140db8b-f15e-5905-b8c5-5371a1938635', 'bot-momentum-browse', 'momentum-v2', '035420', 'buy', 17, 220500, 'filled', 562, '2026-03-12 10:44:00', '2026-03-12 10:44:00');

-- bot-rsi-browse: 36건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2679e84b-6e80-5b50-a4d0-ea2a197cddba', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 220000, 'filled', 165, '2025-12-19 11:48:00', '2025-12-19 11:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b64cb88b-ab1d-5f82-ab9e-dc83d5bedc8c', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 50500, 'filled', 182, '2025-12-25 11:56:00', '2025-12-25 11:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('444fe038-94b4-5338-ac66-ff042534c22c', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 218000, 'filled', 163, '2025-12-30 11:45:00', '2025-12-30 11:45:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('beaeafc6-196b-58e2-8c34-3bf058322e46', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 218000, 'filled', 163, '2025-12-30 10:04:00', '2025-12-30 10:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0e43875a-0de3-5c0d-a613-9fd5b2ed4f28', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 54500, 'filled', 196, '2026-01-01 14:11:00', '2026-01-01 14:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('58d28e64-222b-5524-8892-349856edd1b9', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 22, 55300, 'filled', 182, '2026-01-02 10:41:00', '2026-01-02 10:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('3bedaafd-0316-5989-a80b-916e0bb6aa29', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 213000, 'filled', 160, '2026-01-07 14:03:00', '2026-01-07 14:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8decd3e6-0502-5a64-b4d9-57345670df22', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 213000, 'filled', 160, '2026-01-07 11:38:00', '2026-01-07 11:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0c6cfadb-b883-5b0e-9a5e-5e33865e7890', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 22, 50600, 'filled', 167, '2026-01-09 13:31:00', '2026-01-09 13:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('36f717fd-d784-5946-be3a-82d6fcb15f4a', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 50600, 'filled', 182, '2026-01-09 09:48:00', '2026-01-09 09:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('41f14c7a-f1ec-58bb-8bec-0182da8a00ef', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 50700, 'filled', 183, '2026-01-14 10:02:00', '2026-01-14 10:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('27b03a11-5634-5f51-9c84-cc295433d9cb', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 50700, 'filled', 183, '2026-01-14 10:43:00', '2026-01-14 10:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fdc3ee81-c634-5fe6-8944-00273d128918', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 215000, 'filled', 161, '2026-01-15 14:21:00', '2026-01-15 14:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('bdf9cc9e-611c-515c-8a3e-2f8a1c1c490a', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 214500, 'filled', 161, '2026-01-16 10:25:00', '2026-01-16 10:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('cdb1c239-adbb-5b1c-b1ec-c7180045c773', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 214500, 'filled', 161, '2026-01-20 14:19:00', '2026-01-20 14:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('33c88a09-1678-519c-a003-7c287c70ec5a', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 214500, 'filled', 161, '2026-01-20 11:26:00', '2026-01-20 11:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('01737cfd-6dda-5034-bef4-f8dc01a850c5', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 49150, 'filled', 177, '2026-01-22 10:48:00', '2026-01-22 10:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('bf8305c0-1399-59a5-a77f-37aac79d1770', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 26, 46550, 'filled', 182, '2026-01-23 11:54:00', '2026-01-23 11:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1bb9417c-1435-552d-ab8b-3cf756234dc0', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 197000, 'filled', 148, '2026-01-28 15:35:00', '2026-01-28 15:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('71e61f8e-eedc-5846-a1ba-d59ba1436049', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 6, 197000, 'filled', 177, '2026-01-28 11:04:00', '2026-01-28 11:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4b5660d1-a0b8-56db-a7b7-6defe84f1932', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 26, 51000, 'filled', 199, '2026-02-03 14:22:00', '2026-02-03 14:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('765e6e50-c0e3-5cce-b5c5-f68c9980f6a5', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 24, 51000, 'filled', 184, '2026-02-03 11:51:00', '2026-02-03 11:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9ee33bcd-5668-5af0-9d9c-962937fed774', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 6, 209500, 'filled', 189, '2026-02-09 12:08:00', '2026-02-09 12:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099b2cd4-5d35-54db-8cc4-e16d8379d722', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 209500, 'filled', 157, '2026-02-09 10:27:00', '2026-02-09 10:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b336bb5c-8487-5a66-8b69-626a10b9daf9', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 24, 50300, 'filled', 181, '2026-02-12 10:55:00', '2026-02-12 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fc3348e9-9449-57ad-a749-326bcfe59ea3', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 211000, 'filled', 158, '2026-02-12 13:42:00', '2026-02-12 13:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('023b3304-59af-582f-b129-7726cbdb4919', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 211000, 'filled', 158, '2026-02-12 10:52:00', '2026-02-12 10:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('039c67fc-38a2-59c3-a296-5b5dc3731790', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 25, 49500, 'filled', 186, '2026-02-16 11:19:00', '2026-02-16 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('92df45ef-c007-53dd-86fc-603b6aac0a48', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 208500, 'filled', 156, '2026-02-19 13:53:00', '2026-02-19 13:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('11784d04-55d2-5565-8a24-0fce59291a1d', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 208500, 'filled', 156, '2026-02-19 10:52:00', '2026-02-19 10:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('3051a925-1a19-5ed1-a314-7ada57a912bb', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 25, 45800, 'filled', 172, '2026-02-20 10:11:00', '2026-02-20 10:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ed2bba5c-1526-5b92-be94-1a58e606b058', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'buy', 27, 46050, 'filled', 187, '2026-02-23 11:47:00', '2026-02-23 11:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7c739527-d673-5bf5-b645-e2837f75886c', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 211500, 'filled', 159, '2026-02-24 10:05:00', '2026-02-24 10:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d13a33fe-6d97-54be-9954-fe8f0225054c', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'buy', 5, 211500, 'filled', 159, '2026-02-24 09:32:00', '2026-02-24 09:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('33e193e9-79ff-5b4a-99d2-1386ce136a57', 'bot-rsi-browse', 'rsi-reversal-01', '005380', 'sell', 5, 203500, 'filled', 153, '2026-03-09 13:01:00', '2026-03-09 13:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('25dd2db4-3307-5de8-8542-83c89a04fdb7', 'bot-rsi-browse', 'rsi-reversal-01', '035720', 'sell', 27, 48700, 'filled', 197, '2026-03-11 15:14:00', '2026-03-11 15:14:00');

-- bot-mean-old: 35건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4a6352b0-97ff-5e11-aeb4-de733adee207', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 37, 53700, 'filled', 298, '2025-12-19 09:04:00', '2025-12-19 09:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2b5ac4a2-dd44-50b1-adaf-8dd200127517', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 37, 53100, 'filled', 295, '2025-12-22 10:40:00', '2025-12-22 10:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('43e3780d-fd07-5dc7-8558-1e98bdee8232', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 37, 52700, 'filled', 292, '2025-12-24 11:34:00', '2025-12-24 11:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fc703e83-cc93-5a06-b136-1eb9f72735be', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 26, 74900, 'filled', 292, '2025-12-26 11:11:00', '2025-12-26 11:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('324424ce-0db9-5587-8061-86cf9572e1a8', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 37, 52000, 'filled', 289, '2025-12-30 13:52:00', '2025-12-30 13:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b2942de1-cdd3-5381-b66c-e6a620bf215c', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 38, 52000, 'filled', 296, '2025-12-30 11:07:00', '2025-12-30 11:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2f9b56ef-d6a9-5809-986c-38b106d002e8', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 26, 74000, 'filled', 289, '2026-01-01 12:32:00', '2026-01-01 12:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ba25c3cb-8f4c-5dd2-9438-f76326095cc7', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 38, 51900, 'filled', 296, '2026-01-05 15:19:00', '2026-01-05 15:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('79a62d40-e264-5237-99dc-76e4bbe32d56', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 208000, 'filled', 281, '2026-01-05 10:22:00', '2026-01-05 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('031b9172-340e-53c7-b7df-05cb7a0f73d7', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 38, 51900, 'filled', 296, '2026-01-07 09:06:00', '2026-01-07 09:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7cbe6dce-6e5c-5797-b498-635097fe07bf', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 38, 53000, 'filled', 302, '2026-01-08 10:57:00', '2026-01-08 10:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2b7a2422-f3ff-5815-909b-de6e45c2e7a8', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 37, 53100, 'filled', 295, '2026-01-09 09:33:00', '2026-01-09 09:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b8e3b25a-86c9-55be-836b-f15092ce26f4', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 215000, 'filled', 290, '2026-01-12 15:04:00', '2026-01-12 15:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0bfa8cb9-085b-52b8-8c1f-927bbcc044f1', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 37, 52800, 'filled', 293, '2026-01-12 14:51:00', '2026-01-12 14:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('379e4df8-363e-5f0a-ad40-cbd4af065f5c', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 37, 52800, 'filled', 293, '2026-01-12 10:07:00', '2026-01-12 10:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('52bfee7a-ca84-553f-a2ee-96fa094186da', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 27, 73800, 'filled', 299, '2026-01-13 10:13:00', '2026-01-13 10:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e444474f-59e3-54cc-b121-2a710aa461ea', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 27, 72300, 'filled', 293, '2026-01-15 14:58:00', '2026-01-15 14:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a58102a1-d531-58a4-9559-6a6313250adc', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 220000, 'filled', 297, '2026-01-19 10:15:00', '2026-01-19 10:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099e304e-14af-502c-8da6-7befa03c19f1', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 37, 59600, 'filled', 331, '2026-01-21 11:18:00', '2026-01-21 11:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('17f42fd7-290b-5760-be97-6d3f79e831ba', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 33, 59600, 'filled', 295, '2026-01-21 10:17:00', '2026-01-21 10:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39de01f4-c200-5a3f-8f4a-e20af9a62928', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 217000, 'filled', 293, '2026-01-26 11:35:00', '2026-01-26 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5feba753-a8ce-5a98-a037-bf7601b0dfb0', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 217000, 'filled', 293, '2026-01-26 09:59:00', '2026-01-26 09:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6423a060-e617-5705-8320-5e9f64d3b059', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 33, 59300, 'filled', 294, '2026-01-29 14:32:00', '2026-01-29 14:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('31758323-bbd6-5d4d-b012-5a4c506455ca', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 25, 77100, 'filled', 289, '2026-01-29 11:44:00', '2026-01-29 11:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9c5a3877-4685-50ef-bf93-8224687e5d36', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 213000, 'filled', 288, '2026-02-03 12:05:00', '2026-02-03 12:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c9aaa46f-6057-5683-9d61-d7a4e287700b', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 213000, 'filled', 288, '2026-02-03 09:30:00', '2026-02-03 09:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('52115983-09ed-56c6-9a4d-534fd4aa6b0b', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 25, 81000, 'filled', 304, '2026-02-05 10:01:00', '2026-02-05 10:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0cc510dc-0700-5efe-bbc8-fd6d316dbc78', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 32, 61900, 'filled', 297, '2026-02-06 09:39:00', '2026-02-06 09:39:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('586fbfc1-78af-5436-9a21-21cdd2cae0d5', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 204500, 'filled', 276, '2026-02-10 10:12:00', '2026-02-10 10:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a30ccd6f-38af-5ff0-89dd-643dea4fbd67', 'bot-mean-old', 'mean-revert-01', '035420', 'buy', 9, 204500, 'filled', 276, '2026-02-10 09:20:00', '2026-02-10 09:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('03f4294b-28df-508f-be7c-51f866b7882d', 'bot-mean-old', 'mean-revert-01', '035720', 'sell', 32, 59300, 'filled', 285, '2026-02-12 11:27:00', '2026-02-12 11:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('80285f82-cf59-59a2-8ab5-7280b7ef34e0', 'bot-mean-old', 'mean-revert-01', '035420', 'sell', 9, 202500, 'filled', 273, '2026-02-13 13:11:00', '2026-02-13 13:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ff3406c3-02e1-5eb6-8bb7-ec7ed4ec636b', 'bot-mean-old', 'mean-revert-01', '005930', 'buy', 24, 82100, 'filled', 296, '2026-02-13 09:43:00', '2026-02-13 09:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7689b904-6973-5caf-9663-7c899355f5bd', 'bot-mean-old', 'mean-revert-01', '005930', 'sell', 24, 81300, 'filled', 293, '2026-02-16 15:02:00', '2026-02-16 15:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2f05d19d-e401-5bf8-880c-92649829824e', 'bot-mean-old', 'mean-revert-01', '035720', 'buy', 34, 58800, 'filled', 300, '2026-02-16 10:06:00', '2026-02-16 10:06:00');

-- ── 포지션 이력 (153건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71900, 0.0, '2025-12-19 11:17:00', '2025-12-19 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 160500, 0.0, '2025-12-22 11:27:00', '2025-12-22 11:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 71600, -24721, '2025-12-23 14:01:00', '2025-12-23 14:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 163600, 62082, '2025-12-23 15:41:00', '2025-12-23 15:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 22, 163600, 0.0, '2025-12-23 09:28:00', '2025-12-23 09:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 17, 219500, 0.0, '2025-12-25 10:09:00', '2025-12-25 10:09:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 51, 73100, 0.0, '2025-12-26 10:38:00', '2025-12-26 10:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 17, 216000, -68497, '2025-12-29 10:35:00', '2025-12-29 10:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 17, 216000, 0.0, '2025-12-29 11:12:00', '2025-12-29 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 22, 159300, -103187, '2025-12-30 10:54:00', '2025-12-30 10:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 51, 73700, 21391, '2025-12-30 10:24:00', '2025-12-30 10:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 159300, 0.0, '2025-12-30 09:23:00', '2025-12-30 09:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71500, 0.0, '2025-12-31 11:40:00', '2025-12-31 11:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 17, 211000, -93788, '2026-01-01 15:44:00', '2026-01-01 15:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 17, 211000, 0.0, '2026-01-01 09:14:00', '2026-01-01 09:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 153000, -153522, '2026-01-05 11:41:00', '2026-01-05 11:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 153000, 0.0, '2026-01-05 09:16:00', '2026-01-05 09:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 70200, -76544, '2026-01-06 13:57:00', '2026-01-06 13:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 53, 70200, 0.0, '2026-01-06 09:08:00', '2026-01-06 09:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 152500, -20967, '2026-01-07 15:27:00', '2026-01-07 15:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 53, 69600, -40837, '2026-01-07 13:24:00', '2026-01-07 13:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 152500, 0.0, '2026-01-07 11:16:00', '2026-01-07 11:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 53, 70300, 0.0, '2026-01-08 11:56:00', '2026-01-08 11:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 17, 206000, -93580, '2026-01-12 12:32:00', '2026-01-12 12:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 18, 206000, 0.0, '2026-01-12 11:19:00', '2026-01-12 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 53, 71100, 33168, '2026-01-13 11:34:00', '2026-01-13 11:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71700, 0.0, '2026-01-14 09:07:00', '2026-01-14 09:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 18, 216500, 179452, '2026-01-16 13:52:00', '2026-01-16 13:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 17, 216500, 0.0, '2026-01-16 09:42:00', '2026-01-16 09:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 70300, -81756, '2026-01-19 11:59:00', '2026-01-19 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 17, 221000, 67295, '2026-01-19 15:44:00', '2026-01-19 15:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 221000, 0.0, '2026-01-19 10:42:00', '2026-01-19 10:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 162700, 235233, '2026-01-20 10:15:00', '2026-01-20 10:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 162700, 0.0, '2026-01-20 09:37:00', '2026-01-20 09:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 70800, 0.0, '2026-01-21 09:04:00', '2026-01-21 09:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 71800, 42853, '2026-01-22 15:31:00', '2026-01-22 15:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71800, 0.0, '2026-01-22 11:59:00', '2026-01-22 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 159900, -73411, '2026-01-26 13:29:00', '2026-01-26 13:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 71700, -14334, '2026-01-26 10:43:00', '2026-01-26 10:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 52, 71700, 0.0, '2026-01-26 09:25:00', '2026-01-26 09:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 229000, 119023, '2026-01-27 11:12:00', '2026-01-27 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 156000, 0.0, '2026-01-27 10:11:00', '2026-01-27 10:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 221500, 0.0, '2026-01-29 11:34:00', '2026-01-29 11:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 149200, -171973, '2026-02-02 13:57:00', '2026-02-02 13:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 25, 149200, 0.0, '2026-02-02 09:24:00', '2026-02-02 09:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 52, 72700, 42738, '2026-02-03 15:50:00', '2026-02-03 15:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 51, 72700, 0.0, '2026-02-03 09:12:00', '2026-02-03 09:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 225500, 55161, '2026-02-04 15:20:00', '2026-02-04 15:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 225500, 0.0, '2026-02-04 11:58:00', '2026-02-04 11:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 51, 73000, 6179, '2026-02-05 11:04:00', '2026-02-05 11:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 51, 73000, 0.0, '2026-02-05 10:07:00', '2026-02-05 10:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 25, 149400, -4150, '2026-02-09 12:59:00', '2026-02-09 12:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 228000, 31063, '2026-02-09 15:45:00', '2026-02-09 15:45:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 228000, 0.0, '2026-02-09 10:08:00', '2026-02-09 10:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 153700, 0.0, '2026-02-10 09:29:00', '2026-02-10 09:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 51, 72400, -39647, '2026-02-11 14:16:00', '2026-02-11 14:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 51, 72400, 0.0, '2026-02-11 09:23:00', '2026-02-11 09:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 227000, -24899, '2026-02-12 15:33:00', '2026-02-12 15:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 227000, 0.0, '2026-02-12 11:06:00', '2026-02-12 11:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 51, 74000, 72354, '2026-02-13 14:09:00', '2026-02-13 14:09:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 225000, -40820, '2026-02-13 14:13:00', '2026-02-13 14:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 50, 74000, 0.0, '2026-02-13 11:40:00', '2026-02-13 11:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 229000, 0.0, '2026-02-16 09:40:00', '2026-02-16 09:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 153600, -11432, '2026-02-17 15:16:00', '2026-02-17 15:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 50, 74700, 25850, '2026-02-17 13:35:00', '2026-02-17 13:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 50, 74700, 0.0, '2026-02-17 09:56:00', '2026-02-17 09:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 23, 160000, 0.0, '2026-02-18 11:35:00', '2026-02-18 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 23, 152500, -181093, '2026-02-20 10:22:00', '2026-02-20 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 50, 75900, 50703, '2026-02-23 11:59:00', '2026-02-23 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 228000, -24937, '2026-02-24 11:56:00', '2026-02-24 11:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 49, 76400, 0.0, '2026-02-24 11:59:00', '2026-02-24 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 24, 154600, 0.0, '2026-02-27 10:55:00', '2026-02-27 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 49, 80300, 181460, '2026-03-02 13:22:00', '2026-03-02 13:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 46, 80300, 0.0, '2026-03-02 09:01:00', '2026-03-02 09:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 16, 227000, 0.0, '2026-03-03 10:22:00', '2026-03-03 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 46, 78400, -96236, '2026-03-06 15:50:00', '2026-03-06 15:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'sell', 16, 228000, 7063, '2026-03-06 14:32:00', '2026-03-06 14:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'buy', 47, 78400, 0.0, '2026-03-06 10:02:00', '2026-03-06 10:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '005930', 'sell', 47, 79600, 47234, '2026-03-09 15:47:00', '2026-03-09 15:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'sell', 24, 165200, 244686, '2026-03-10 15:58:00', '2026-03-10 15:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '000660', 'buy', 22, 165200, 0.0, '2026-03-10 11:54:00', '2026-03-10 11:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-browse', '035420', 'buy', 17, 220500, 0.0, '2026-03-12 10:44:00', '2026-03-12 10:44:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 220000, 0.0, '2025-12-19 11:48:00', '2025-12-19 11:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 50500, 0.0, '2025-12-25 11:56:00', '2025-12-25 11:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 218000, -12670, '2025-12-30 11:45:00', '2025-12-30 11:45:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 218000, 0.0, '2025-12-30 10:04:00', '2025-12-30 10:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 54500, 92796, '2026-01-01 14:11:00', '2026-01-01 14:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 22, 55300, 0.0, '2026-01-02 10:41:00', '2026-01-02 10:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 213000, -27610, '2026-01-07 14:03:00', '2026-01-07 14:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 213000, 0.0, '2026-01-07 11:38:00', '2026-01-07 11:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 22, 50600, -106127, '2026-01-09 13:31:00', '2026-01-09 13:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 50600, 0.0, '2026-01-09 09:48:00', '2026-01-09 09:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 50700, -582, '2026-01-14 10:02:00', '2026-01-14 10:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 50700, 0.0, '2026-01-14 10:43:00', '2026-01-14 10:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 215000, 7367, '2026-01-15 14:21:00', '2026-01-15 14:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 214500, 0.0, '2026-01-16 10:25:00', '2026-01-16 10:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 214500, -2628, '2026-01-20 14:19:00', '2026-01-20 14:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 214500, 0.0, '2026-01-20 11:26:00', '2026-01-20 11:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 49150, -40090, '2026-01-22 10:48:00', '2026-01-22 10:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 26, 46550, 0.0, '2026-01-23 11:54:00', '2026-01-23 11:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 197000, -89914, '2026-01-28 15:35:00', '2026-01-28 15:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 6, 197000, 0.0, '2026-01-28 11:04:00', '2026-01-28 11:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 26, 51000, 112451, '2026-02-03 14:22:00', '2026-02-03 14:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 24, 51000, 0.0, '2026-02-03 11:51:00', '2026-02-03 11:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 6, 209500, 71920, '2026-02-09 12:08:00', '2026-02-09 12:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 209500, 0.0, '2026-02-09 10:27:00', '2026-02-09 10:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 24, 50300, -19758, '2026-02-12 10:55:00', '2026-02-12 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 211000, 4916, '2026-02-12 13:42:00', '2026-02-12 13:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 211000, 0.0, '2026-02-12 10:52:00', '2026-02-12 10:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 25, 49500, 0.0, '2026-02-16 11:19:00', '2026-02-16 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 208500, -15054, '2026-02-19 13:53:00', '2026-02-19 13:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 208500, 0.0, '2026-02-19 10:52:00', '2026-02-19 10:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 25, 45800, -95306, '2026-02-20 10:11:00', '2026-02-20 10:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'buy', 27, 46050, 0.0, '2026-02-23 11:47:00', '2026-02-23 11:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 211500, 12409, '2026-02-24 10:05:00', '2026-02-24 10:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'buy', 5, 211500, 0.0, '2026-02-24 09:32:00', '2026-02-24 09:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '005380', 'sell', 5, 203500, -42493, '2026-03-09 13:01:00', '2026-03-09 13:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-browse', '035720', 'sell', 27, 48700, 68329, '2026-03-11 15:14:00', '2026-03-11 15:14:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 37, 53700, 0.0, '2025-12-19 09:04:00', '2025-12-19 09:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 37, 53100, -27014, '2025-12-22 10:40:00', '2025-12-22 10:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 37, 52700, 0.0, '2025-12-24 11:34:00', '2025-12-24 11:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 26, 74900, 0.0, '2025-12-26 11:11:00', '2025-12-26 11:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 37, 52000, -30614, '2025-12-30 13:52:00', '2025-12-30 13:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 38, 52000, 0.0, '2025-12-30 11:07:00', '2025-12-30 11:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 26, 74000, -28114, '2026-01-01 12:32:00', '2026-01-01 12:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 38, 51900, -8632, '2026-01-05 15:19:00', '2026-01-05 15:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 208000, 0.0, '2026-01-05 10:22:00', '2026-01-05 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 38, 51900, 0.0, '2026-01-07 09:06:00', '2026-01-07 09:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 38, 53000, 36866, '2026-01-08 10:57:00', '2026-01-08 10:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 37, 53100, 0.0, '2026-01-09 09:33:00', '2026-01-09 09:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 215000, 58260, '2026-01-12 15:04:00', '2026-01-12 15:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 37, 52800, -15886, '2026-01-12 14:51:00', '2026-01-12 14:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 37, 52800, 0.0, '2026-01-12 10:07:00', '2026-01-12 10:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 27, 73800, 0.0, '2026-01-13 10:13:00', '2026-01-13 10:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 27, 72300, -45283, '2026-01-15 14:58:00', '2026-01-15 14:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 220000, 0.0, '2026-01-19 10:15:00', '2026-01-19 10:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 37, 59600, 246197, '2026-01-21 11:18:00', '2026-01-21 11:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 33, 59600, 0.0, '2026-01-21 10:17:00', '2026-01-21 10:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 217000, -31785, '2026-01-26 11:35:00', '2026-01-26 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 217000, 0.0, '2026-01-26 09:59:00', '2026-01-26 09:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 33, 59300, -14695, '2026-01-29 14:32:00', '2026-01-29 14:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 25, 77100, 0.0, '2026-01-29 11:44:00', '2026-01-29 11:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 213000, -40697, '2026-02-03 12:05:00', '2026-02-03 12:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 213000, 0.0, '2026-02-03 09:30:00', '2026-02-03 09:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 25, 81000, 92538, '2026-02-05 10:01:00', '2026-02-05 10:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 32, 61900, 0.0, '2026-02-06 09:39:00', '2026-02-06 09:39:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 204500, -81009, '2026-02-10 10:12:00', '2026-02-10 10:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'buy', 9, 204500, 0.0, '2026-02-10 09:20:00', '2026-02-10 09:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'sell', 32, 59300, -87849, '2026-02-12 11:27:00', '2026-02-12 11:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035420', 'sell', 9, 202500, -22465, '2026-02-13 13:11:00', '2026-02-13 13:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'buy', 24, 82100, 0.0, '2026-02-13 09:43:00', '2026-02-13 09:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '005930', 'sell', 24, 81300, -23981, '2026-02-16 15:02:00', '2026-02-16 15:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-old', '035720', 'buy', 34, 58800, 0.0, '2026-02-16 10:06:00', '2026-02-16 10:06:00');

-- ── 최종 포지션 (8건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-browse', '000660', 22, 165200, 0.0, '2026-03-12 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-browse', '035420', 17, 220500, 0.0, '2026-03-12 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-browse', '005930', 0, 0.0, 149855, '2026-03-12 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-browse', '005380', 0, 0.0, -93757, '2026-03-12 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-browse', '035720', 0, 0.0, 11713, '2026-03-12 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-old', '035720', 34, 58800, 0.0, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-old', '035420', 0, 0.0, -117696, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-old', '005930', 0, 0.0, -4840, '2026-02-19 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-browse', 15000000, 295637, 0.0, 154814720, 147493257);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-browse', 5000000, 4914871, 0.0, 20562535, 20477406);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 50000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 20000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 30000000);

-- ── 자금 변동 이력 (120건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'allocate', 15000000, '초기 할당', '2025-12-19 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'allocate', 5000000, '초기 할당', '2025-12-19 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3739361, '삼성전자 52주 매수', '2025-12-19 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1100165, '현대차 5주 매수', '2025-12-19 11:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3692054, 'SK하이닉스 23주 매수', '2025-12-22 11:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3599740, 'SK하이닉스 22주 매수', '2025-12-23 09:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3722642, '삼성전자 52주 매도', '2025-12-23 14:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3762236, 'SK하이닉스 23주 매도', '2025-12-23 15:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3732060, 'NAVER 17주 매수', '2025-12-25 10:09:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1212182, '카카오 24주 매수', '2025-12-25 11:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3728659, '삼성전자 51주 매수', '2025-12-26 10:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3671449, 'NAVER 17주 매도', '2025-12-29 10:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3672551, 'NAVER 17주 매수', '2025-12-29 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3664450, 'SK하이닉스 23주 매수', '2025-12-30 09:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1090163, '현대차 5주 매수', '2025-12-30 10:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3758136, '삼성전자 51주 매도', '2025-12-30 10:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3504074, 'SK하이닉스 22주 매도', '2025-12-30 10:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1089837, '현대차 5주 매도', '2025-12-30 11:45:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3718558, '삼성전자 52주 매수', '2025-12-31 11:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3587538, 'NAVER 17주 매수', '2026-01-01 09:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1307804, '카카오 24주 매도', '2026-01-01 14:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3586462, 'NAVER 17주 매도', '2026-01-01 15:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1216782, '카카오 22주 매수', '2026-01-02 10:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3672551, 'SK하이닉스 24주 매수', '2026-01-05 09:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3518472, 'SK하이닉스 23주 매도', '2026-01-05 11:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3721158, '삼성전자 53주 매수', '2026-01-06 09:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3649852, '삼성전자 52주 매도', '2026-01-06 13:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3660549, 'SK하이닉스 24주 매수', '2026-01-07 11:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1065160, '현대차 5주 매수', '2026-01-07 11:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3688247, '삼성전자 53주 매도', '2026-01-07 13:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1064840, '현대차 5주 매도', '2026-01-07 14:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3659451, 'SK하이닉스 24주 매도', '2026-01-07 15:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3726459, '삼성전자 53주 매수', '2026-01-08 11:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1214582, '카카오 24주 매수', '2026-01-09 09:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1113033, '카카오 22주 매도', '2026-01-09 13:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3708556, 'NAVER 18주 매수', '2026-01-12 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3501475, 'NAVER 17주 매도', '2026-01-12 12:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3767735, '삼성전자 53주 매도', '2026-01-13 11:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3728959, '삼성전자 52주 매수', '2026-01-14 09:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1216617, '카카오 24주 매도', '2026-01-14 10:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1216983, '카카오 24주 매수', '2026-01-14 10:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1074839, '현대차 5주 매도', '2026-01-15 14:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3681052, 'NAVER 17주 매수', '2026-01-16 09:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1072661, '현대차 5주 매수', '2026-01-16 10:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3896415, 'NAVER 18주 매도', '2026-01-16 13:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3536530, 'NAVER 16주 매수', '2026-01-19 10:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3655052, '삼성전자 52주 매도', '2026-01-19 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3756436, 'NAVER 17주 매도', '2026-01-19 15:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3742661, 'SK하이닉스 23주 매수', '2026-01-20 09:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3904214, 'SK하이닉스 24주 매도', '2026-01-20 10:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1072661, '현대차 5주 매수', '2026-01-20 11:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1072339, '현대차 5주 매도', '2026-01-20 14:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3682152, '삼성전자 52주 매수', '2026-01-21 09:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1179423, '카카오 24주 매도', '2026-01-22 10:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3734160, '삼성전자 52주 매수', '2026-01-22 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3733040, '삼성전자 52주 매도', '2026-01-22 15:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1210482, '카카오 26주 매수', '2026-01-23 11:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3728959, '삼성전자 52주 매수', '2026-01-26 09:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3727841, '삼성전자 52주 매도', '2026-01-26 10:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3677148, 'SK하이닉스 23주 매도', '2026-01-26 13:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3744562, 'SK하이닉스 24주 매수', '2026-01-27 10:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3663450, 'NAVER 16주 매도', '2026-01-27 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1182177, '현대차 6주 매수', '2026-01-28 11:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 984852, '현대차 5주 매도', '2026-01-28 15:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3544532, 'NAVER 16주 매수', '2026-01-29 11:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3730560, 'SK하이닉스 25주 매수', '2026-02-02 09:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3580263, 'SK하이닉스 24주 매도', '2026-02-02 13:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3708256, '삼성전자 51주 매수', '2026-02-03 09:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1224184, '카카오 24주 매수', '2026-02-03 11:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1325801, '카카오 26주 매도', '2026-02-03 14:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3779833, '삼성전자 52주 매도', '2026-02-03 15:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3608541, 'NAVER 16주 매수', '2026-02-04 11:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3607459, 'NAVER 16주 매도', '2026-02-04 15:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3723558, '삼성전자 51주 매수', '2026-02-05 10:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3722442, '삼성전자 51주 매도', '2026-02-05 11:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3648547, 'NAVER 16주 매수', '2026-02-09 10:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1047657, '현대차 5주 매수', '2026-02-09 10:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1256811, '현대차 6주 매도', '2026-02-09 12:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3734440, 'SK하이닉스 25주 매도', '2026-02-09 12:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3647453, 'NAVER 16주 매도', '2026-02-09 15:45:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3689353, 'SK하이닉스 24주 매수', '2026-02-10 09:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3692954, '삼성전자 51주 매수', '2026-02-11 09:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3691846, '삼성전자 51주 매도', '2026-02-11 14:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1055158, '현대차 5주 매수', '2026-02-12 10:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1207019, '카카오 24주 매도', '2026-02-12 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3632545, 'NAVER 16주 매수', '2026-02-12 11:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1054842, '현대차 5주 매도', '2026-02-12 13:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3631455, 'NAVER 16주 매도', '2026-02-12 15:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3700555, '삼성전자 50주 매수', '2026-02-13 11:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3773434, '삼성전자 51주 매도', '2026-02-13 14:09:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3599460, 'NAVER 16주 매도', '2026-02-13 14:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3664550, 'NAVER 16주 매수', '2026-02-16 09:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1237686, '카카오 25주 매수', '2026-02-16 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3735560, '삼성전자 50주 매수', '2026-02-17 09:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3734440, '삼성전자 50주 매도', '2026-02-17 13:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3685847, 'SK하이닉스 24주 매도', '2026-02-17 15:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3680552, 'SK하이닉스 23주 매수', '2026-02-18 11:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1042656, '현대차 5주 매수', '2026-02-19 10:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1042344, '현대차 5주 매도', '2026-02-19 13:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1144828, '카카오 25주 매도', '2026-02-20 10:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3506974, 'SK하이닉스 23주 매도', '2026-02-20 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1243537, '카카오 27주 매수', '2026-02-23 11:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3794431, '삼성전자 50주 매도', '2026-02-23 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', -1057659, '현대차 5주 매수', '2026-02-24 09:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1057341, '현대차 5주 매도', '2026-02-24 10:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3647453, 'NAVER 16주 매도', '2026-02-24 11:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3744162, '삼성전자 49주 매수', '2026-02-24 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3710957, 'SK하이닉스 24주 매수', '2026-02-27 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3694354, '삼성전자 46주 매수', '2026-03-02 09:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3934110, '삼성전자 49주 매도', '2026-03-02 13:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3632545, 'NAVER 16주 매수', '2026-03-03 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3685353, '삼성전자 47주 매수', '2026-03-06 10:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3647453, 'NAVER 16주 매도', '2026-03-06 14:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3605859, '삼성전자 46주 매도', '2026-03-06 15:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1017347, '현대차 5주 매도', '2026-03-09 13:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3740639, '삼성전자 47주 매도', '2026-03-09 15:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3634945, 'SK하이닉스 22주 매수', '2026-03-10 11:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', 3964205, 'SK하이닉스 24주 매도', '2026-03-10 15:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-browse', 'trade', 1314703, '카카오 27주 매도', '2026-03-11 15:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-browse', 'trade', -3749062, 'NAVER 17주 매수', '2026-03-12 10:44:00');

-- ── 이벤트 로그 (25건) ──────────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-001', 'bot.step.success', '2025-12-19 11:17:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-002', 'bot.step.success', '2025-12-25 10:09:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-003', 'bot.step.success', '2025-12-30 10:24:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-004', 'bot.step.success', '2026-01-05 11:41:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-005', 'bot.step.success', '2026-01-07 13:24:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-006', 'bot.step.success', '2026-01-13 11:34:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-007', 'bot.step.success', '2026-01-19 15:44:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-008', 'bot.step.success', '2026-01-22 15:31:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-009', 'bot.step.success', '2026-01-27 11:12:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-010', 'bot.step.success', '2026-02-03 15:50:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-011', 'bot.step.success', '2026-02-05 10:07:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-012', 'bot.step.success', '2026-02-11 14:16:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-013', 'bot.step.success', '2026-02-13 14:13:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-014', 'bot.step.success', '2026-02-17 09:56:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-015', 'bot.step.success', '2026-02-24 11:59:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-016', 'bot.step.success', '2026-03-06 15:50:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-017', 'bot.step.success', '2026-03-10 11:54:00', '{"bot_id": "bot-momentum-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--001', 'bot.step.success', '2025-12-19 11:48:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--002', 'bot.step.success', '2026-01-02 10:41:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--003', 'bot.step.success', '2026-01-14 10:02:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--004', 'bot.step.success', '2026-01-20 11:26:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--005', 'bot.step.success', '2026-02-03 14:22:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--006', 'bot.step.success', '2026-02-12 13:42:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--007', 'bot.step.success', '2026-02-20 10:11:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--008', 'bot.step.success', '2026-03-11 15:14:00', '{"bot_id": "bot-rsi-browse", "message": "매매 사이클 완료"}');

-- ── 멤버 ────────────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write", "data:read", "backtest:run", "report:write"]', 'datetime(''now'', ''-60 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write", "data:read", "backtest:run"]', 'datetime(''now'', ''-45 days'')');
