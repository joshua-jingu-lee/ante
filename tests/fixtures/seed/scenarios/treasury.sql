-- 시나리오: treasury
-- 생성: generate_scenario.py (seed=456)
-- 생성일: 2026-03-19

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-01-18 09:00:00', '20일 고점 돌파 시 매수', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('macd-cross', 'MACD 크로스', '1.0.0', 'strategies/macd_cross.py', 'active', '2026-02-17 09:00:00', 'MACD 골든/데드크로스 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', '2026-02-02 09:00:00', 'RSI 과매도 반등 전략', 'strategy-dev-02');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-01", "strategy_id": "momentum-v2", "name": "모멘텀 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "035420"]}', 'running', '2026-01-28 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-macd-cross', 'MACD 봇', 'macd-cross', 'live', '{"bot_id": "bot-macd-cross", "strategy_id": "macd-cross", "name": "MACD 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "000660"]}', 'running', '2026-02-17 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-01', 'RSI 봇', 'rsi-reversal', 'live', '{"bot_id": "bot-rsi-01", "strategy_id": "rsi-reversal", "name": "RSI 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["035720", "005380"]}', 'stopped', '2026-02-07 09:00:00');

-- ── 거래 내역 (107건) ────────────────────────
-- bot-momentum-01: 52건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a803ad04-c6f6-5bb7-ad82-f87b689c887b', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 53, 70400, 'filled', 560, '2025-12-23 11:46:00', '2025-12-23 11:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9a70bca9-4a10-535e-8c7d-9fd0ea28dbda', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 19, 194500, 'filled', 554, '2025-12-25 09:30:00', '2025-12-25 09:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8c2d74e8-4c48-58cc-9a8d-b5a6d2c12b7a', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 53, 72600, 'filled', 577, '2025-12-31 12:04:00', '2025-12-31 12:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('36d2b8bc-974f-5278-89b8-9356d0ec0d17', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 19, 197600, 'filled', 563, '2025-12-31 10:23:00', '2025-12-31 10:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aec44eda-8fa0-5801-b470-447ffa3c2525', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 199600, 'filled', 539, '2026-01-01 11:55:00', '2026-01-01 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b8796a3-6f78-52d3-ba3a-6768daa84396', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 71400, 'filled', 557, '2026-01-02 09:28:00', '2026-01-02 09:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8530525e-fc21-544e-8392-44ad4601b6f0', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 201500, 'filled', 544, '2026-01-05 10:20:00', '2026-01-05 10:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c8092f4a-10f2-5ffc-b498-0455485ab26f', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 72000, 'filled', 562, '2026-01-06 14:44:00', '2026-01-06 14:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e170ad1f-6441-5158-a3cc-9dce4df82cd6', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 72000, 'filled', 562, '2026-01-06 10:31:00', '2026-01-06 10:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7712478d-610a-56a8-b076-02aae5914c47', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 199300, 'filled', 538, '2026-01-07 11:02:00', '2026-01-07 11:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('437d1658-1b76-5b14-84fd-24f68e8fb8bc', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 71500, 'filled', 558, '2026-01-09 11:17:00', '2026-01-09 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('88a305dd-e794-55da-a122-c8cc138f537d', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 71500, 'filled', 558, '2026-01-09 11:48:00', '2026-01-09 11:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39727373-84d4-5790-a65c-9c4e51cdce92', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 202000, 'filled', 545, '2026-01-12 11:57:00', '2026-01-12 11:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8f9a70a5-7b4a-54ce-9a3a-e71fcfd786d6', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 202000, 'filled', 545, '2026-01-12 10:33:00', '2026-01-12 10:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5fe362c5-8aef-514c-a16d-4d8a0264828f', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 72600, 'filled', 566, '2026-01-14 11:42:00', '2026-01-14 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9d6aaec5-5aed-587e-b0e5-03a0eeea3f1f', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72600, 'filled', 555, '2026-01-14 09:41:00', '2026-01-14 09:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ca4230d1-7bae-5f70-99bf-07d857325955', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 204000, 'filled', 551, '2026-01-15 11:19:00', '2026-01-15 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('72aafdd0-fac0-5556-8bf5-601ff0071c9f', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 204000, 'filled', 551, '2026-01-15 10:27:00', '2026-01-15 10:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('402e0815-2f8e-5c03-a226-581ae13487a4', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 69900, 'filled', 535, '2026-01-19 14:10:00', '2026-01-19 14:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1fe78282-3b83-550f-b663-953e320e48ca', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 214500, 'filled', 579, '2026-01-21 10:51:00', '2026-01-21 10:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fa56a5b8-7613-5264-91c4-a4adc7aa4108', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 214500, 'filled', 547, '2026-01-21 11:57:00', '2026-01-21 11:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('db35cb38-51f3-58a1-91cd-83d232dcab70', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 71300, 'filled', 556, '2026-01-22 09:36:00', '2026-01-22 09:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0db2a51d-b3cd-5db9-872e-96ec6eff9e7b', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 71600, 'filled', 558, '2026-01-23 15:41:00', '2026-01-23 15:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0b37ad4c-a089-555b-98f8-325348e201d2', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 212000, 'filled', 541, '2026-01-26 13:30:00', '2026-01-26 13:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7f2a9d2f-b3e9-5f4d-8273-cecaef5309c6', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72300, 'filled', 553, '2026-01-26 10:54:00', '2026-01-26 10:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aa21ce21-6b87-5d9f-bf91-22378d60e952', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 213500, 'filled', 544, '2026-01-27 11:17:00', '2026-01-27 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('cf92a519-a695-5272-ab5a-90291df40adc', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 73100, 'filled', 559, '2026-01-29 11:55:00', '2026-01-29 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c82c52cd-6283-592d-9a51-40d8a9006e39', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 73100, 'filled', 559, '2026-01-29 11:44:00', '2026-01-29 11:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9070683e-d9cd-5f36-a905-316f42c4b521', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 210000, 'filled', 536, '2026-02-02 11:36:00', '2026-02-02 11:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7cdc81cd-4271-542e-a935-d945081f1058', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 210000, 'filled', 536, '2026-02-02 09:51:00', '2026-02-02 09:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a0f6caf5-0ab3-5571-94e0-09c2ea80afc9', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 72600, 'filled', 555, '2026-02-04 15:37:00', '2026-02-04 15:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('48da81a7-1ab2-52b0-9145-3570d489962b', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 206000, 'filled', 525, '2026-02-04 11:42:00', '2026-02-04 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8127f3dc-46fb-569a-a327-2fbddee1cd09', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72400, 'filled', 554, '2026-02-05 10:51:00', '2026-02-05 10:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39e396ed-2fbe-5f8b-9498-e40423041638', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 73600, 'filled', 563, '2026-02-10 10:47:00', '2026-02-10 10:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9ace70f0-e70c-554d-968e-d5124d56bc05', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 18, 203500, 'filled', 549, '2026-02-12 11:09:00', '2026-02-12 11:09:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('57fb0c35-2604-57a4-ba01-fc3458ed9411', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 76100, 'filled', 559, '2026-02-13 10:30:00', '2026-02-13 10:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('f264590a-e9b8-585f-b842-6b6f7773b8f4', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 77600, 'filled', 570, '2026-02-17 12:33:00', '2026-02-17 12:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b0d8b6a9-67b2-5d75-bff5-6f6a837d3349', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 48, 77600, 'filled', 559, '2026-02-17 09:43:00', '2026-02-17 09:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('68477f5c-b3bf-52a5-b275-89d290c27047', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 18, 187600, 'filled', 507, '2026-02-18 11:37:00', '2026-02-18 11:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8aa0d94e-2f79-5170-a26c-2be55b9993ce', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 20, 186600, 'filled', 560, '2026-02-19 11:22:00', '2026-02-19 11:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6194eeb4-8f00-515d-8af3-4043c440923c', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 48, 73700, 'filled', 531, '2026-02-20 14:36:00', '2026-02-20 14:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4a8d8622-dcfc-5e0d-be3d-7aef2b8cb184', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 73700, 'filled', 553, '2026-02-20 10:13:00', '2026-02-20 10:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099625e2-1608-5e9f-a66f-9654a4e81798', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 73600, 'filled', 552, '2026-02-24 12:34:00', '2026-02-24 12:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('393b488a-2a76-5981-a46f-34829415b07b', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 73600, 'filled', 552, '2026-02-24 10:26:00', '2026-02-24 10:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8e49e161-d1f5-5372-b438-494c3f5fcfe5', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 20, 174900, 'filled', 525, '2026-02-25 11:07:00', '2026-02-25 11:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2c40ac3c-76f6-5567-9b6a-0a77d0cd2e89', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 21, 174900, 'filled', 551, '2026-02-25 11:36:00', '2026-02-25 11:36:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e1458b94-f14f-51ce-9896-b27e8aa4d3f6', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 72300, 'filled', 542, '2026-02-27 12:42:00', '2026-02-27 12:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2e6e1dbd-0b22-5ca4-b5ae-194b150512b3', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 21, 170900, 'filled', 538, '2026-03-02 11:15:00', '2026-03-02 11:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6487d438-6b7e-56ce-a1fc-7ebf717618ce', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 75800, 'filled', 557, '2026-03-04 11:35:00', '2026-03-04 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1e33fbad-957c-54dd-adb8-92a8bbaddb2d', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 77300, 'filled', 568, '2026-03-09 14:44:00', '2026-03-09 14:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0f14fe74-8e3b-5011-8b3b-8513d4d7519f', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 21, 170600, 'filled', 537, '2026-03-10 09:00:00', '2026-03-10 09:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b401315-60ce-5cf6-9779-0fb3db8c6033', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 76100, 'filled', 559, '2026-03-11 09:51:00', '2026-03-11 09:51:00');

-- bot-macd-cross: 26건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fef8d21d-1bc2-56e5-99e7-be38cbf41ae3', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 158200, 'filled', 356, '2025-12-23 10:50:00', '2025-12-23 10:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e53b4cb7-9558-55a3-9283-5a0a9c36685e', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 35, 70300, 'filled', 369, '2025-12-30 11:12:00', '2025-12-30 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d06fb08c-0464-524e-9673-768178255b53', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 163000, 'filled', 367, '2026-01-01 14:51:00', '2026-01-01 14:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7e77446c-6484-549f-8719-a904ae6d9ee9', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 14, 168300, 'filled', 353, '2026-01-05 11:51:00', '2026-01-05 11:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('057c132e-f77a-5c98-b801-83a8fe099124', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 14, 163500, 'filled', 343, '2026-01-06 10:43:00', '2026-01-06 10:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('699e4962-65b5-57f9-98e0-de84d31798ec', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 163500, 'filled', 368, '2026-01-06 10:43:00', '2026-01-06 10:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2e9d938f-ad36-5b01-b255-711caf514bdd', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 35, 72200, 'filled', 379, '2026-01-07 13:39:00', '2026-01-07 13:39:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('096b7bb5-b951-57d1-aca1-0d5eda6ffc88', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 34, 72200, 'filled', 368, '2026-01-07 11:02:00', '2026-01-07 11:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e217705b-eb44-5238-90a5-5b1411d9c7d7', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 171700, 'filled', 386, '2026-01-14 14:15:00', '2026-01-14 14:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('76fffd98-a311-52aa-8a1e-b355ba70015c', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 34, 75400, 'filled', 385, '2026-01-14 10:23:00', '2026-01-14 10:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('f7e4261f-c4fb-5f0e-89d9-c8906bf60d9c', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 14, 173700, 'filled', 365, '2026-01-15 10:48:00', '2026-01-15 10:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c831efe6-466d-5cfc-94a6-f61d9ed3e9dd', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 32, 76800, 'filled', 369, '2026-01-16 11:19:00', '2026-01-16 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('52026244-1e7d-5e4b-95ee-8fd7360e177c', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 14, 162500, 'filled', 341, '2026-01-23 14:02:00', '2026-01-23 14:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('13495dfb-7c3d-5e03-a73c-3e4ca3129956', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 32, 78500, 'filled', 377, '2026-01-26 15:14:00', '2026-01-26 15:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('05108027-3901-569e-b8c2-32e12201364d', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 31, 78500, 'filled', 365, '2026-01-26 11:28:00', '2026-01-26 11:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('68b0942e-c35f-5a6e-bab3-0bb73256484d', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 164900, 'filled', 371, '2026-01-29 10:15:00', '2026-01-29 10:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('26e581d9-4265-5af4-a312-14962a2f3c4e', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 31, 77900, 'filled', 362, '2026-02-05 13:45:00', '2026-02-05 13:45:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b09e2f2c-59d6-563d-9a0e-dbdaef057caa', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 32, 77900, 'filled', 374, '2026-02-05 11:33:00', '2026-02-05 11:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('32bea231-229f-5d58-976a-628f2848beb9', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 161200, 'filled', 363, '2026-02-06 15:41:00', '2026-02-06 15:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0b65828d-5947-5b31-9d9d-1f10a724964a', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 161200, 'filled', 363, '2026-02-06 11:41:00', '2026-02-06 11:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1208fdf2-11aa-5010-aae9-d5fda8a41d85', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 162800, 'filled', 366, '2026-02-12 13:07:00', '2026-02-12 13:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7c33fbd6-0a4d-5414-b1f2-e0aea5c59554', 'bot-macd-cross', 'macd-cross', '005930', 'sell', 32, 80400, 'filled', 386, '2026-02-13 13:29:00', '2026-02-13 13:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('53f06c91-2f7c-5561-9eba-435f2d57761f', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 15, 163300, 'filled', 367, '2026-02-13 11:32:00', '2026-02-13 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5dd62313-ee77-5754-9c62-9a16b14d9f04', 'bot-macd-cross', 'macd-cross', '005930', 'buy', 30, 81200, 'filled', 365, '2026-02-16 09:40:00', '2026-02-16 09:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9a289e23-8467-5b3e-99ea-fcb533b515f9', 'bot-macd-cross', 'macd-cross', '000660', 'sell', 15, 156000, 'filled', 351, '2026-02-17 15:37:00', '2026-02-17 15:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('84604cda-06ca-53f5-8ab0-ce436dfdfab4', 'bot-macd-cross', 'macd-cross', '000660', 'buy', 16, 153500, 'filled', 368, '2026-02-19 11:56:00', '2026-02-19 11:56:00');

-- bot-rsi-01: 29건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2679e84b-6e80-5b50-a4d0-ea2a197cddba', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 208000, 'filled', 374, '2025-12-22 11:55:00', '2025-12-22 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b64cb88b-ab1d-5f82-ab9e-dc83d5bedc8c', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 51, 48550, 'filled', 371, '2025-12-23 10:56:00', '2025-12-23 10:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('444fe038-94b4-5338-ac66-ff042534c22c', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 204000, 'filled', 367, '2025-12-26 15:07:00', '2025-12-26 15:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('beaeafc6-196b-58e2-8c34-3bf058322e46', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 51, 45350, 'filled', 347, '2025-12-26 11:16:00', '2025-12-26 11:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0e43875a-0de3-5c0d-a613-9fd5b2ed4f28', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 55, 45350, 'filled', 374, '2025-12-26 10:38:00', '2025-12-26 10:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('58d28e64-222b-5524-8892-349856edd1b9', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 55, 44950, 'filled', 371, '2025-12-31 15:56:00', '2025-12-31 15:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('3bedaafd-0316-5989-a80b-916e0bb6aa29', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 11, 209000, 'filled', 345, '2026-01-01 10:31:00', '2026-01-01 10:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8decd3e6-0502-5a64-b4d9-57345670df22', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 11, 212000, 'filled', 350, '2026-01-06 11:17:00', '2026-01-06 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0c6cfadb-b883-5b0e-9a5e-5e33865e7890', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 11, 213000, 'filled', 351, '2026-01-07 10:55:00', '2026-01-07 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('36f717fd-d784-5946-be3a-82d6fcb15f4a', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 52, 48050, 'filled', 375, '2026-01-12 11:28:00', '2026-01-12 11:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('41f14c7a-f1ec-58bb-8bec-0182da8a00ef', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 11, 211000, 'filled', 348, '2026-01-13 15:58:00', '2026-01-13 15:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('27b03a11-5634-5f51-9c84-cc295433d9cb', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 11, 213500, 'filled', 352, '2026-01-14 11:01:00', '2026-01-14 11:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fdc3ee81-c634-5fe6-8944-00273d128918', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 11, 216000, 'filled', 356, '2026-01-15 10:18:00', '2026-01-15 10:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('bdf9cc9e-611c-515c-8a3e-2f8a1c1c490a', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 11, 216000, 'filled', 356, '2026-01-15 11:07:00', '2026-01-15 11:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('cdb1c239-adbb-5b1c-b1ec-c7180045c773', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 52, 46250, 'filled', 361, '2026-01-21 12:14:00', '2026-01-21 12:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('33c88a09-1678-519c-a003-7c287c70ec5a', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 11, 211000, 'filled', 348, '2026-01-21 12:44:00', '2026-01-21 12:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('01737cfd-6dda-5034-bef4-f8dc01a850c5', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 54, 46250, 'filled', 375, '2026-01-21 09:15:00', '2026-01-21 09:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('bf8305c0-1399-59a5-a77f-37aac79d1770', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 208000, 'filled', 374, '2026-01-26 10:04:00', '2026-01-26 10:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1bb9417c-1435-552d-ab8b-3cf756234dc0', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 54, 48000, 'filled', 389, '2026-01-27 10:31:00', '2026-01-27 10:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('71e61f8e-eedc-5846-a1ba-d59ba1436049', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 54, 46000, 'filled', 373, '2026-02-03 09:17:00', '2026-02-03 09:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4b5660d1-a0b8-56db-a7b7-6defe84f1932', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 197200, 'filled', 355, '2026-02-06 15:11:00', '2026-02-06 15:11:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('765e6e50-c0e3-5cce-b5c5-f68c9980f6a5', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 197200, 'filled', 355, '2026-02-06 10:37:00', '2026-02-06 10:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9ee33bcd-5668-5af0-9d9c-962937fed774', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 193200, 'filled', 348, '2026-02-09 10:15:00', '2026-02-09 10:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099b2cd4-5d35-54db-8cc4-e16d8379d722', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 54, 45500, 'filled', 369, '2026-02-10 10:52:00', '2026-02-10 10:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b336bb5c-8487-5a66-8b69-626a10b9daf9', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 54, 45500, 'filled', 369, '2026-02-10 10:07:00', '2026-02-10 10:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fc3348e9-9449-57ad-a749-326bcfe59ea3', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 12, 198900, 'filled', 358, '2026-02-12 09:28:00', '2026-02-12 09:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('023b3304-59af-582f-b129-7726cbdb4919', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 12, 207000, 'filled', 373, '2026-02-17 10:46:00', '2026-02-17 10:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('039c67fc-38a2-59c3-a296-5b5dc3731790', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 54, 43450, 'filled', 352, '2026-02-19 15:14:00', '2026-02-19 15:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('92df45ef-c007-53dd-86fc-603b6aac0a48', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 11, 215500, 'filled', 356, '2026-02-19 09:25:00', '2026-02-19 09:25:00');

-- ── 포지션 이력 (107건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 53, 70400, 0.0, '2025-12-23 11:46:00', '2025-12-23 11:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 19, 194500, 0.0, '2025-12-25 09:30:00', '2025-12-25 09:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 53, 72600, 107173, '2025-12-31 12:04:00', '2025-12-31 12:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 19, 197600, 49702, '2025-12-31 10:23:00', '2025-12-31 10:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 199600, 0.0, '2026-01-01 11:55:00', '2026-01-01 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 71400, 0.0, '2026-01-02 09:28:00', '2026-01-02 09:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 201500, 25314, '2026-01-05 10:20:00', '2026-01-05 10:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 72000, 22027, '2026-01-06 14:44:00', '2026-01-06 14:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 72000, 0.0, '2026-01-06 10:31:00', '2026-01-06 10:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 199300, 0.0, '2026-01-07 11:02:00', '2026-01-07 11:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 71500, -35109, '2026-01-09 11:17:00', '2026-01-09 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 71500, 0.0, '2026-01-09 11:48:00', '2026-01-09 11:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 202000, 39692, '2026-01-12 11:57:00', '2026-01-12 11:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 202000, 0.0, '2026-01-12 10:33:00', '2026-01-12 10:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 72600, 47951, '2026-01-14 11:42:00', '2026-01-14 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72600, 0.0, '2026-01-14 09:41:00', '2026-01-14 09:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 204000, 27003, '2026-01-15 11:19:00', '2026-01-15 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 204000, 0.0, '2026-01-15 10:27:00', '2026-01-15 10:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 69900, -146434, '2026-01-19 14:10:00', '2026-01-19 14:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 214500, 179541, '2026-01-21 10:51:00', '2026-01-21 10:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 214500, 0.0, '2026-01-21 11:57:00', '2026-01-21 11:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 71300, 0.0, '2026-01-22 09:36:00', '2026-01-22 09:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 71600, 6479, '2026-01-23 15:41:00', '2026-01-23 15:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 212000, -51330, '2026-01-26 13:30:00', '2026-01-26 13:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72300, 0.0, '2026-01-26 10:54:00', '2026-01-26 10:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 213500, 0.0, '2026-01-27 11:17:00', '2026-01-27 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 73100, 31666, '2026-01-29 11:55:00', '2026-01-29 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 73100, 0.0, '2026-01-29 11:44:00', '2026-01-29 11:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 210000, -68247, '2026-02-02 11:36:00', '2026-02-02 11:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 210000, 0.0, '2026-02-02 09:51:00', '2026-02-02 09:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 72600, -34571, '2026-02-04 15:37:00', '2026-02-04 15:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 206000, -76580, '2026-02-04 11:42:00', '2026-02-04 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72400, 0.0, '2026-02-05 10:51:00', '2026-02-05 10:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 73600, 52004, '2026-02-10 10:47:00', '2026-02-10 10:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 18, 203500, 0.0, '2026-02-12 11:09:00', '2026-02-12 11:09:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 76100, 0.0, '2026-02-13 10:30:00', '2026-02-13 10:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 77600, 64184, '2026-02-17 12:33:00', '2026-02-17 12:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 48, 77600, 0.0, '2026-02-17 09:43:00', '2026-02-17 09:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 18, 187600, -294474, '2026-02-18 11:37:00', '2026-02-18 11:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 20, 186600, 0.0, '2026-02-19 11:22:00', '2026-02-19 11:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 48, 73700, -195867, '2026-02-20 14:36:00', '2026-02-20 14:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 73700, 0.0, '2026-02-20 10:13:00', '2026-02-20 10:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 73600, -14016, '2026-02-24 12:34:00', '2026-02-24 12:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 73600, 0.0, '2026-02-24 10:26:00', '2026-02-24 10:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 20, 174900, -242570, '2026-02-25 11:07:00', '2026-02-25 11:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 21, 174900, 0.0, '2026-02-25 11:36:00', '2026-02-25 11:36:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 72300, -73856, '2026-02-27 12:42:00', '2026-02-27 12:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 21, 170900, -92792, '2026-03-02 11:15:00', '2026-03-02 11:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 75800, 0.0, '2026-03-04 11:35:00', '2026-03-04 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 77300, 64220, '2026-03-09 14:44:00', '2026-03-09 14:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 21, 170600, 0.0, '2026-03-10 09:00:00', '2026-03-10 09:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 76100, 0.0, '2026-03-11 09:51:00', '2026-03-11 09:51:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 158200, 0.0, '2025-12-23 10:50:00', '2025-12-23 10:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 35, 70300, 0.0, '2025-12-30 11:12:00', '2025-12-30 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 163000, 66009, '2026-01-01 14:51:00', '2026-01-01 14:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 14, 168300, 0.0, '2026-01-05 11:51:00', '2026-01-05 11:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 14, 163500, -72808, '2026-01-06 10:43:00', '2026-01-06 10:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 163500, 0.0, '2026-01-06 10:43:00', '2026-01-06 10:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 35, 72200, 60309, '2026-01-07 13:39:00', '2026-01-07 13:39:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 34, 72200, 0.0, '2026-01-07 11:02:00', '2026-01-07 11:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 171700, 116690, '2026-01-14 14:15:00', '2026-01-14 14:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 34, 75400, 102519, '2026-01-14 10:23:00', '2026-01-14 10:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 14, 173700, 0.0, '2026-01-15 10:48:00', '2026-01-15 10:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 32, 76800, 0.0, '2026-01-16 11:19:00', '2026-01-16 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 14, 162500, -162373, '2026-01-23 14:02:00', '2026-01-23 14:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 32, 78500, 48245, '2026-01-26 15:14:00', '2026-01-26 15:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 31, 78500, 0.0, '2026-01-26 11:28:00', '2026-01-26 11:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 164900, 0.0, '2026-01-29 10:15:00', '2026-01-29 10:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 31, 77900, -24516, '2026-02-05 13:45:00', '2026-02-05 13:45:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 32, 77900, 0.0, '2026-02-05 11:33:00', '2026-02-05 11:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 161200, -61424, '2026-02-06 15:41:00', '2026-02-06 15:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 161200, 0.0, '2026-02-06 11:41:00', '2026-02-06 11:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 162800, 18017, '2026-02-12 13:07:00', '2026-02-12 13:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'sell', 32, 80400, 73697, '2026-02-13 13:29:00', '2026-02-13 13:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 15, 163300, 0.0, '2026-02-13 11:32:00', '2026-02-13 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '005930', 'buy', 30, 81200, 0.0, '2026-02-16 09:40:00', '2026-02-16 09:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'sell', 15, 156000, -115233, '2026-02-17 15:37:00', '2026-02-17 15:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-macd-cross', '000660', 'buy', 16, 153500, 0.0, '2026-02-19 11:56:00', '2026-02-19 11:56:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 208000, 0.0, '2025-12-22 11:55:00', '2025-12-22 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 51, 48550, 0.0, '2025-12-23 10:56:00', '2025-12-23 10:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 204000, -53997, '2025-12-26 15:07:00', '2025-12-26 15:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 51, 45350, -168867, '2025-12-26 11:16:00', '2025-12-26 11:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 55, 45350, 0.0, '2025-12-26 10:38:00', '2025-12-26 10:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 55, 44950, -28057, '2025-12-31 15:56:00', '2025-12-31 15:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 11, 209000, 0.0, '2026-01-01 10:31:00', '2026-01-01 10:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 11, 212000, 27286, '2026-01-06 11:17:00', '2026-01-06 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 11, 213000, 0.0, '2026-01-07 10:55:00', '2026-01-07 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 52, 48050, 0.0, '2026-01-12 11:28:00', '2026-01-12 11:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 11, 211000, -27686, '2026-01-13 15:58:00', '2026-01-13 15:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 11, 213500, 0.0, '2026-01-14 11:01:00', '2026-01-14 11:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 11, 216000, 21679, '2026-01-15 10:18:00', '2026-01-15 10:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 11, 216000, 0.0, '2026-01-15 11:07:00', '2026-01-15 11:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 52, 46250, -99493, '2026-01-21 12:14:00', '2026-01-21 12:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 11, 211000, -60686, '2026-01-21 12:44:00', '2026-01-21 12:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 54, 46250, 0.0, '2026-01-21 09:15:00', '2026-01-21 09:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 208000, 0.0, '2026-01-26 10:04:00', '2026-01-26 10:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 54, 48000, 88149, '2026-01-27 10:31:00', '2026-01-27 10:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 54, 46000, 0.0, '2026-02-03 09:17:00', '2026-02-03 09:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 197200, -135398, '2026-02-06 15:11:00', '2026-02-06 15:11:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 197200, 0.0, '2026-02-06 10:37:00', '2026-02-06 10:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 193200, -53680, '2026-02-09 10:15:00', '2026-02-09 10:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 54, 45500, -33020, '2026-02-10 10:52:00', '2026-02-10 10:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 54, 45500, 0.0, '2026-02-10 10:07:00', '2026-02-10 10:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 12, 198900, 0.0, '2026-02-12 09:28:00', '2026-02-12 09:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 12, 207000, 91114, '2026-02-17 10:46:00', '2026-02-17 10:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 54, 43450, -116448, '2026-02-19 15:14:00', '2026-02-19 15:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 11, 215500, 0.0, '2026-02-19 09:25:00', '2026-02-19 09:25:00');

-- ── 최종 포지션 (6건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 21, 170600, 0.0, '2026-03-12 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 49, 76100, 0.0, '2026-03-12 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-macd-cross', '005930', 30, 81200, 0.0, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-macd-cross', '000660', 16, 153500, 0.0, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '005380', 11, 215500, 0.0, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '035720', 0, 0.0, -357736, '2026-02-19 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 15000000, 0, 0.0, 99380904, 91445610);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-macd-cross', 10000000, 260011, 0.0, 34150821, 29302832);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-01', 10000000, 4704438, 0.0, 36395058, 33469996);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 42000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 35000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 7000000);

-- ── 자금 변동 이력 (110건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'allocate', 10000000, '초기 할당', '2025-12-22 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2496374, '현대차 12주 매수', '2025-12-22 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 15000000, '초기 할당', '2025-12-23 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'allocate', 10000000, '초기 할당', '2025-12-23 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2373356, 'SK하이닉스 15주 매수', '2025-12-23 10:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2476421, '카카오 51주 매수', '2025-12-23 10:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3731760, '삼성전자 53주 매수', '2025-12-23 11:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3696054, 'NAVER 19주 매수', '2025-12-25 09:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2494624, '카카오 55주 매수', '2025-12-26 10:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2312503, '카카오 51주 매도', '2025-12-26 11:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2447633, '현대차 12주 매도', '2025-12-26 15:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2460869, '삼성전자 35주 매수', '2025-12-30 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3753837, 'NAVER 19주 매도', '2025-12-31 10:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3847223, '삼성전자 53주 매도', '2025-12-31 12:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2471879, '카카오 55주 매도', '2025-12-31 15:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2299345, '현대차 11주 매수', '2026-01-01 10:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3593339, 'NAVER 18주 매수', '2026-01-01 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2444633, 'SK하이닉스 15주 매도', '2026-01-01 14:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3713357, '삼성전자 52주 매수', '2026-01-02 09:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3626456, 'NAVER 18주 매도', '2026-01-05 10:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2356553, 'SK하이닉스 14주 매수', '2026-01-05 11:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3744562, '삼성전자 52주 매수', '2026-01-06 10:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2288657, 'SK하이닉스 14주 매도', '2026-01-06 10:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2452868, 'SK하이닉스 15주 매수', '2026-01-06 10:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2331650, '현대차 11주 매도', '2026-01-06 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3743438, '삼성전자 52주 매도', '2026-01-06 14:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2343351, '현대차 11주 매수', '2026-01-07 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3587938, 'NAVER 18주 매수', '2026-01-07 11:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2455168, '삼성전자 34주 매수', '2026-01-07 11:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2526621, '삼성전자 35주 매도', '2026-01-07 13:39:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3717442, '삼성전자 52주 매도', '2026-01-09 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3718558, '삼성전자 52주 매수', '2026-01-09 11:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3636545, 'NAVER 18주 매수', '2026-01-12 10:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2498975, '카카오 52주 매수', '2026-01-12 11:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3635455, 'NAVER 18주 매도', '2026-01-12 11:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2320652, '현대차 11주 매도', '2026-01-13 15:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3703155, '삼성전자 51주 매수', '2026-01-14 09:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2563215, '삼성전자 34주 매도', '2026-01-14 10:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2348852, '현대차 11주 매수', '2026-01-14 11:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3774634, '삼성전자 52주 매도', '2026-01-14 11:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2575114, 'SK하이닉스 15주 매도', '2026-01-14 14:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2375644, '현대차 11주 매도', '2026-01-15 10:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3672551, 'NAVER 18주 매수', '2026-01-15 10:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2432165, 'SK하이닉스 14주 매수', '2026-01-15 10:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2376356, '현대차 11주 매수', '2026-01-15 11:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3671449, 'NAVER 18주 매도', '2026-01-15 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2457969, '삼성전자 32주 매수', '2026-01-16 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3564365, '삼성전자 51주 매도', '2026-01-19 14:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2497875, '카카오 54주 매수', '2026-01-21 09:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3860421, 'NAVER 18주 매도', '2026-01-21 10:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3647047, 'NAVER 17주 매수', '2026-01-21 11:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2404639, '카카오 52주 매도', '2026-01-21 12:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2320652, '현대차 11주 매도', '2026-01-21 12:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3708156, '삼성전자 52주 매수', '2026-01-22 09:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2274659, 'SK하이닉스 14주 매도', '2026-01-23 14:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3722642, '삼성전자 52주 매도', '2026-01-23 15:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2496374, '현대차 12주 매수', '2026-01-26 10:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3687853, '삼성전자 51주 매수', '2026-01-26 10:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2433865, '삼성전자 31주 매수', '2026-01-26 11:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3603459, 'NAVER 17주 매도', '2026-01-26 13:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2511623, '삼성전자 32주 매도', '2026-01-26 15:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2591611, '카카오 54주 매도', '2026-01-27 10:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3630044, 'NAVER 17주 매수', '2026-01-27 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2473871, 'SK하이닉스 15주 매수', '2026-01-29 10:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3728659, '삼성전자 51주 매수', '2026-01-29 11:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3727541, '삼성전자 51주 매도', '2026-01-29 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3570536, 'NAVER 17주 매수', '2026-02-02 09:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3569464, 'NAVER 17주 매도', '2026-02-02 11:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2484373, '카카오 54주 매수', '2026-02-03 09:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3501475, 'NAVER 17주 매도', '2026-02-04 11:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3702045, '삼성전자 51주 매도', '2026-02-04 15:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3692954, '삼성전자 51주 매수', '2026-02-05 10:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2493174, '삼성전자 32주 매수', '2026-02-05 11:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2414538, '삼성전자 31주 매도', '2026-02-05 13:45:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2366755, '현대차 12주 매수', '2026-02-06 10:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2418363, 'SK하이닉스 15주 매수', '2026-02-06 11:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2366045, '현대차 12주 매도', '2026-02-06 15:11:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2417637, 'SK하이닉스 15주 매도', '2026-02-06 15:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2318052, '현대차 12주 매도', '2026-02-09 10:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2457369, '카카오 54주 매수', '2026-02-10 10:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3753037, '삼성전자 51주 매도', '2026-02-10 10:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2456631, '카카오 54주 매도', '2026-02-10 10:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2387158, '현대차 12주 매수', '2026-02-12 09:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3663549, 'NAVER 18주 매수', '2026-02-12 11:09:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2441634, 'SK하이닉스 15주 매도', '2026-02-12 13:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3729459, '삼성전자 49주 매수', '2026-02-13 10:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2449867, 'SK하이닉스 15주 매수', '2026-02-13 11:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2572414, '삼성전자 32주 매도', '2026-02-13 13:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2436365, '삼성전자 30주 매수', '2026-02-16 09:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3725359, '삼성전자 48주 매수', '2026-02-17 09:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2483627, '현대차 12주 매도', '2026-02-17 10:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3801830, '삼성전자 49주 매도', '2026-02-17 12:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', 2339649, 'SK하이닉스 15주 매도', '2026-02-17 15:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3376293, 'NAVER 18주 매도', '2026-02-18 11:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -2370856, '현대차 11주 매수', '2026-02-19 09:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3732560, 'NAVER 20주 매수', '2026-02-19 11:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-macd-cross', 'trade', -2456368, 'SK하이닉스 16주 매수', '2026-02-19 11:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 2345948, '카카오 54주 매도', '2026-02-19 15:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3685553, '삼성전자 50주 매수', '2026-02-20 10:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3537069, '삼성전자 48주 매도', '2026-02-20 14:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3680552, '삼성전자 50주 매수', '2026-02-24 10:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3679448, '삼성전자 50주 매도', '2026-02-24 12:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3497475, 'NAVER 20주 매도', '2026-02-25 11:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3673451, 'NAVER 21주 매수', '2026-02-25 11:36:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3614458, '삼성전자 50주 매도', '2026-02-27 12:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3588362, 'NAVER 21주 매도', '2026-03-02 11:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3714757, '삼성전자 49주 매수', '2026-03-04 11:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3787132, '삼성전자 49주 매도', '2026-03-09 14:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3583137, 'NAVER 21주 매수', '2026-03-10 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3729459, '삼성전자 49주 매수', '2026-03-11 09:51:00');

-- ── 이벤트 로그 (24건) ──────────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-001', 'bot.step.success', '2025-12-23 11:46:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-002', 'bot.step.success', '2026-01-02 09:28:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-003', 'bot.step.success', '2026-01-09 11:17:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-004', 'bot.step.success', '2026-01-14 09:41:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-005', 'bot.step.success', '2026-01-21 11:57:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-006', 'bot.step.success', '2026-01-27 11:17:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-007', 'bot.step.success', '2026-02-04 15:37:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-008', 'bot.step.success', '2026-02-13 10:30:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-009', 'bot.step.success', '2026-02-20 14:36:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-010', 'bot.step.success', '2026-02-25 11:36:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-011', 'bot.step.success', '2026-03-10 09:00:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-001', 'bot.step.success', '2025-12-23 10:50:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-002', 'bot.step.success', '2026-01-06 10:43:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-003', 'bot.step.success', '2026-01-15 10:48:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-004', 'bot.step.success', '2026-01-29 10:15:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-005', 'bot.step.success', '2026-02-12 13:07:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-macd-006', 'bot.step.success', '2026-02-19 11:56:00', '{"bot_id": "bot-macd-cross", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--001', 'bot.step.success', '2025-12-22 11:55:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--002', 'bot.step.success', '2025-12-31 15:56:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--003', 'bot.step.success', '2026-01-13 15:58:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--004', 'bot.step.success', '2026-01-21 12:44:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--005', 'bot.step.success', '2026-02-06 15:11:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--006', 'bot.step.success', '2026-02-12 09:28:00', '{"bot_id": "bot-rsi-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-rsi--007', 'bot.stopped', '2026-03-18 15:00:00', '{"bot_id": "bot-rsi-01", "message": "Bot 중지됨 — 사용자 요청"}');

-- ── 멤버 ────────────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write", "data:read", "backtest:run", "report:write"]', 'datetime(''now'', ''-60 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write", "data:read", "backtest:run"]', 'datetime(''now'', ''-45 days'')');
