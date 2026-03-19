-- 시나리오: login-dashboard
-- 생성: generate_scenario.py (seed=789)
-- 생성일: 2026-03-19

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-01-18 09:00:00', '20일 고점 돌파 시 매수', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('rsi-reversal', 'RSI 반등', '1.0.0', 'strategies/rsi_reversal.py', 'active', '2026-02-02 09:00:00', 'RSI 과매도 반등 전략', 'strategy-dev-02');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-01", "strategy_id": "momentum-v2", "name": "모멘텀 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "000660", "035420"]}', 'running', '2026-01-23 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-rsi-01', 'RSI 봇', 'rsi-reversal', 'live', '{"bot_id": "bot-rsi-01", "strategy_id": "rsi-reversal", "name": "RSI 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["035720", "005380"]}', 'running', '2026-01-28 09:00:00');

-- ── 거래 내역 (116건) ────────────────────────
-- bot-momentum-01: 76건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a803ad04-c6f6-5bb7-ad82-f87b689c887b', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 30, 208000, 'filled', 936, '2025-12-09 09:31:00', '2025-12-09 09:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9a70bca9-4a10-535e-8c7d-9fd0ea28dbda', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 42, 147300, 'filled', 928, '2025-12-10 11:33:00', '2025-12-10 11:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8c2d74e8-4c48-58cc-9a8d-b5a6d2c12b7a', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 30, 203500, 'filled', 916, '2025-12-11 12:19:00', '2025-12-11 12:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('36d2b8bc-974f-5278-89b8-9356d0ec0d17', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 70100, 'filled', 936, '2025-12-12 10:29:00', '2025-12-12 10:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aec44eda-8fa0-5801-b470-447ffa3c2525', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 42, 149700, 'filled', 943, '2025-12-17 13:27:00', '2025-12-17 13:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b8796a3-6f78-52d3-ba3a-6768daa84396', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 41, 149700, 'filled', 921, '2025-12-17 09:07:00', '2025-12-17 09:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8530525e-fc21-544e-8392-44ad4601b6f0', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 89, 70400, 'filled', 940, '2025-12-18 14:33:00', '2025-12-18 14:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c8092f4a-10f2-5ffc-b498-0455485ab26f', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 31, 201000, 'filled', 935, '2025-12-19 10:04:00', '2025-12-19 10:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e170ad1f-6441-5158-a3cc-9dce4df82cd6', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 41, 142800, 'filled', 878, '2025-12-22 10:47:00', '2025-12-22 10:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7712478d-610a-56a8-b076-02aae5914c47', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 89, 69600, 'filled', 929, '2025-12-22 09:31:00', '2025-12-22 09:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('437d1658-1b76-5b14-84fd-24f68e8fb8bc', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 89, 68900, 'filled', 920, '2025-12-24 14:56:00', '2025-12-24 14:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('88a305dd-e794-55da-a122-c8cc138f537d', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 90, 68900, 'filled', 930, '2025-12-24 10:33:00', '2025-12-24 10:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39727373-84d4-5790-a65c-9c4e51cdce92', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 31, 216000, 'filled', 1004, '2025-12-25 15:33:00', '2025-12-25 15:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8f9a70a5-7b4a-54ce-9a3a-e71fcfd786d6', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 28, 216000, 'filled', 907, '2025-12-25 10:53:00', '2025-12-25 10:53:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5fe362c5-8aef-514c-a16d-4d8a0264828f', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 90, 66700, 'filled', 900, '2025-12-26 10:31:00', '2025-12-26 10:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9d6aaec5-5aed-587e-b0e5-03a0eeea3f1f', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 41, 151600, 'filled', 932, '2025-12-29 11:28:00', '2025-12-29 11:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ca4230d1-7bae-5f70-99bf-07d857325955', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 41, 150400, 'filled', 925, '2025-12-30 11:02:00', '2025-12-30 11:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('72aafdd0-fac0-5556-8bf5-601ff0071c9f', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 96, 64900, 'filled', 935, '2025-12-31 10:59:00', '2025-12-31 10:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('402e0815-2f8e-5c03-a226-581ae13487a4', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 28, 215000, 'filled', 903, '2026-01-01 10:02:00', '2026-01-01 10:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1fe78282-3b83-550f-b663-953e320e48ca', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 42, 147000, 'filled', 926, '2026-01-01 11:01:00', '2026-01-01 11:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fa56a5b8-7613-5264-91c4-a4adc7aa4108', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 96, 65600, 'filled', 945, '2026-01-05 15:58:00', '2026-01-05 15:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('db35cb38-51f3-58a1-91cd-83d232dcab70', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 210500, 'filled', 916, '2026-01-05 10:37:00', '2026-01-05 10:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0db2a51d-b3cd-5db9-872e-96ec6eff9e7b', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 94, 66200, 'filled', 933, '2026-01-06 10:07:00', '2026-01-06 10:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0b37ad4c-a089-555b-98f8-325348e201d2', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 42, 150600, 'filled', 949, '2026-01-08 12:08:00', '2026-01-08 12:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7f2a9d2f-b3e9-5f4d-8273-cecaef5309c6', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 29, 214000, 'filled', 931, '2026-01-08 13:07:00', '2026-01-08 13:07:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aa21ce21-6b87-5d9f-bf91-22378d60e952', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 41, 150600, 'filled', 926, '2026-01-08 09:38:00', '2026-01-08 09:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('cf92a519-a695-5272-ab5a-90291df40adc', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 28, 216000, 'filled', 907, '2026-01-09 11:40:00', '2026-01-09 11:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c82c52cd-6283-592d-9a51-40d8a9006e39', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 28, 218000, 'filled', 916, '2026-01-12 14:55:00', '2026-01-12 14:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9070683e-d9cd-5f36-a905-316f42c4b521', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 41, 140200, 'filled', 862, '2026-01-13 15:13:00', '2026-01-13 15:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7cdc81cd-4271-542e-a935-d945081f1058', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 44, 140200, 'filled', 925, '2026-01-13 10:50:00', '2026-01-13 10:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a0f6caf5-0ab3-5571-94e0-09c2ea80afc9', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 28, 222000, 'filled', 932, '2026-01-14 10:50:00', '2026-01-14 10:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('48da81a7-1ab2-52b0-9145-3570d489962b', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 44, 139000, 'filled', 917, '2026-01-16 13:37:00', '2026-01-16 13:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8127f3dc-46fb-569a-a327-2fbddee1cd09', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 44, 139000, 'filled', 917, '2026-01-16 09:46:00', '2026-01-16 09:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39e396ed-2fbe-5f8b-9498-e40423041638', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 28, 225500, 'filled', 947, '2026-01-19 15:33:00', '2026-01-19 15:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9ace70f0-e70c-554d-968e-d5124d56bc05', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 27, 225500, 'filled', 913, '2026-01-19 11:27:00', '2026-01-19 11:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('57fb0c35-2604-57a4-ba01-fc3458ed9411', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 94, 70400, 'filled', 993, '2026-01-20 10:34:00', '2026-01-20 10:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('f264590a-e9b8-585f-b842-6b6f7773b8f4', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 44, 144500, 'filled', 954, '2026-01-20 11:42:00', '2026-01-20 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b0d8b6a9-67b2-5d75-bff5-6f6a837d3349', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 87, 71500, 'filled', 933, '2026-01-21 11:15:00', '2026-01-21 11:15:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('68477f5c-b3bf-52a5-b275-89d290c27047', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 27, 222000, 'filled', 899, '2026-01-22 10:45:00', '2026-01-22 10:45:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8aa0d94e-2f79-5170-a26c-2be55b9993ce', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 43, 143600, 'filled', 926, '2026-01-22 09:57:00', '2026-01-22 09:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6194eeb4-8f00-515d-8af3-4043c440923c', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 27, 231000, 'filled', 936, '2026-01-23 11:34:00', '2026-01-23 11:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4a8d8622-dcfc-5e0d-be3d-7aef2b8cb184', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 87, 72900, 'filled', 951, '2026-01-26 12:25:00', '2026-01-26 12:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099625e2-1608-5e9f-a66f-9654a4e81798', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 27, 230500, 'filled', 934, '2026-01-27 12:34:00', '2026-01-27 12:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('393b488a-2a76-5981-a46f-34829415b07b', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 87, 71500, 'filled', 933, '2026-01-27 11:29:00', '2026-01-27 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8e49e161-d1f5-5372-b438-494c3f5fcfe5', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 27, 229000, 'filled', 927, '2026-01-28 11:40:00', '2026-01-28 11:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2c40ac3c-76f6-5567-9b6a-0a77d0cd2e89', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 43, 148500, 'filled', 958, '2026-01-29 15:33:00', '2026-01-29 15:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e1458b94-f14f-51ce-9896-b27e8aa4d3f6', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 87, 70600, 'filled', 921, '2026-01-29 11:01:00', '2026-01-29 11:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2e6e1dbd-0b22-5ca4-b5ae-194b150512b3', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 88, 70600, 'filled', 932, '2026-01-29 11:59:00', '2026-01-29 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6487d438-6b7e-56ce-a1fc-7ebf717618ce', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 88, 70600, 'filled', 932, '2026-02-02 13:00:00', '2026-02-02 13:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1e33fbad-957c-54dd-adb8-92a8bbaddb2d', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 27, 222000, 'filled', 899, '2026-02-03 13:24:00', '2026-02-03 13:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0f14fe74-8e3b-5011-8b3b-8513d4d7519f', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 28, 222000, 'filled', 932, '2026-02-03 09:26:00', '2026-02-03 09:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b401315-60ce-5cf6-9779-0fb3db8c6033', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 44, 141600, 'filled', 935, '2026-02-04 11:48:00', '2026-02-04 11:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b779fd40-0484-5c5d-a53a-82733f4eb064', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 88, 71000, 'filled', 937, '2026-02-06 11:59:00', '2026-02-06 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('53192086-1933-54b0-8514-f0ce05553347', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 44, 141300, 'filled', 933, '2026-02-09 14:37:00', '2026-02-09 14:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('980a0d7b-226c-5045-bdfb-31722675a9a5', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 88, 71300, 'filled', 941, '2026-02-09 12:00:00', '2026-02-09 12:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b96a9387-a880-5b5e-9c4b-4982bbe4ecf3', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 87, 71300, 'filled', 930, '2026-02-09 10:01:00', '2026-02-09 10:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a0c4ef04-e7e0-5238-8cb1-08f4ce69494c', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 28, 220500, 'filled', 926, '2026-02-10 11:48:00', '2026-02-10 11:48:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d433343f-6837-55c9-b629-7e1c6f7de0c9', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 87, 71200, 'filled', 929, '2026-02-10 13:22:00', '2026-02-10 13:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9db948e2-c621-534c-89e2-7a928fb1a0b4', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 28, 220500, 'filled', 926, '2026-02-10 11:31:00', '2026-02-10 11:31:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d10d9f3b-658e-5907-9a5f-775c073e5f56', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 28, 219000, 'filled', 920, '2026-02-11 10:41:00', '2026-02-11 10:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('49bf3b48-0cb4-567c-b6b5-90e6c2461b43', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 41, 149900, 'filled', 922, '2026-02-11 10:52:00', '2026-02-11 10:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2ed32da0-b938-5629-bb4e-814dde1d763d', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 214000, 'filled', 931, '2026-02-12 11:51:00', '2026-02-12 11:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('89f63f4a-4fc6-5e1b-93aa-d269b48cd2d8', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 41, 153400, 'filled', 943, '2026-02-13 14:37:00', '2026-02-13 14:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('24233958-8e2a-50c3-ad32-57e116ac69e6', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 39, 160200, 'filled', 937, '2026-02-16 09:55:00', '2026-02-16 09:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('26c47405-cef8-54bd-9d83-822d51d1494b', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 85, 73000, 'filled', 931, '2026-02-17 11:41:00', '2026-02-17 11:41:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('722668f2-ba18-5aee-8690-52fb586010e1', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 29, 204000, 'filled', 887, '2026-02-18 12:06:00', '2026-02-18 12:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('15fc72b9-6d5e-5fd7-a117-b471d9529649', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 30, 204000, 'filled', 918, '2026-02-18 11:58:00', '2026-02-18 11:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c70d8789-9c28-5233-b792-85ad57e5d52a', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 39, 164000, 'filled', 959, '2026-02-19 15:35:00', '2026-02-19 15:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('3166d2b1-451a-5f2e-b95f-1837e4e72724', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 85, 71400, 'filled', 910, '2026-02-20 12:56:00', '2026-02-20 12:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b9b69623-00a2-5760-8aa1-377df4d02d6b', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 87, 71400, 'filled', 932, '2026-02-20 11:06:00', '2026-02-20 11:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('32b026be-6534-5213-b379-b949a1b1a079', 'bot-momentum-01', 'momentum-v2', '000660', 'buy', 37, 166900, 'filled', 926, '2026-02-23 11:35:00', '2026-02-23 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c5c8e7a5-8d22-5fe3-8705-4d1dddb0041e', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 30, 203500, 'filled', 916, '2026-02-24 12:00:00', '2026-02-24 12:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('045be7ba-68e6-59f0-a717-85b32e5f185d', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 87, 70700, 'filled', 923, '2026-02-25 13:22:00', '2026-02-25 13:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('81771c09-93b5-5cfc-8614-1d153d150617', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 88, 70700, 'filled', 933, '2026-02-25 11:02:00', '2026-02-25 11:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('27d8614b-537b-5b42-8e6c-04b09b7d7ab4', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 29, 215500, 'filled', 937, '2026-02-26 11:24:00', '2026-02-26 11:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0a5ff33b-129c-5893-85a6-df2195c00feb', 'bot-momentum-01', 'momentum-v2', '000660', 'sell', 37, 171100, 'filled', 950, '2026-03-02 15:17:00', '2026-03-02 15:17:00');

-- bot-rsi-01: 40건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2679e84b-6e80-5b50-a4d0-ea2a197cddba', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 17, 218500, 'filled', 557, '2025-12-10 11:13:00', '2025-12-10 11:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b64cb88b-ab1d-5f82-ab9e-dc83d5bedc8c', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 75, 49350, 'filled', 555, '2025-12-11 11:00:00', '2025-12-11 11:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('444fe038-94b4-5338-ac66-ff042534c22c', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 17, 215000, 'filled', 548, '2025-12-16 10:50:00', '2025-12-16 10:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('beaeafc6-196b-58e2-8c34-3bf058322e46', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 17, 214500, 'filled', 547, '2025-12-17 11:23:00', '2025-12-17 11:23:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0e43875a-0de3-5c0d-a613-9fd5b2ed4f28', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 17, 219500, 'filled', 560, '2025-12-23 14:59:00', '2025-12-23 14:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('58d28e64-222b-5524-8892-349856edd1b9', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 75, 48000, 'filled', 540, '2025-12-24 10:22:00', '2025-12-24 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('3bedaafd-0316-5989-a80b-916e0bb6aa29', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 78, 48000, 'filled', 562, '2025-12-24 09:46:00', '2025-12-24 09:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8decd3e6-0502-5a64-b4d9-57345670df22', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 17, 216000, 'filled', 551, '2025-12-26 11:34:00', '2025-12-26 11:34:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0c6cfadb-b883-5b0e-9a5e-5e33865e7890', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 78, 47400, 'filled', 555, '2025-12-29 13:14:00', '2025-12-29 13:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('36f717fd-d784-5946-be3a-82d6fcb15f4a', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 79, 47400, 'filled', 562, '2025-12-29 09:29:00', '2025-12-29 09:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('41f14c7a-f1ec-58bb-8bec-0182da8a00ef', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 17, 210000, 'filled', 536, '2025-12-31 12:19:00', '2025-12-31 12:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('27b03a11-5634-5f51-9c84-cc295433d9cb', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 79, 45400, 'filled', 538, '2026-01-02 13:27:00', '2026-01-02 13:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fdc3ee81-c634-5fe6-8944-00273d128918', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 84, 44400, 'filled', 559, '2026-01-05 10:49:00', '2026-01-05 10:49:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('bdf9cc9e-611c-515c-8a3e-2f8a1c1c490a', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 208000, 'filled', 562, '2026-01-06 11:19:00', '2026-01-06 11:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('cdb1c239-adbb-5b1c-b1ec-c7180045c773', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 199800, 'filled', 539, '2026-01-12 15:40:00', '2026-01-12 15:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('33c88a09-1678-519c-a003-7c287c70ec5a', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 198500, 'filled', 536, '2026-01-13 09:10:00', '2026-01-13 09:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('01737cfd-6dda-5034-bef4-f8dc01a850c5', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 84, 46050, 'filled', 580, '2026-01-14 13:17:00', '2026-01-14 13:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('bf8305c0-1399-59a5-a77f-37aac79d1770', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 81, 46050, 'filled', 560, '2026-01-14 09:02:00', '2026-01-14 09:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1bb9417c-1435-552d-ab8b-3cf756234dc0', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 195800, 'filled', 529, '2026-01-19 13:28:00', '2026-01-19 13:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('71e61f8e-eedc-5846-a1ba-d59ba1436049', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 19, 195800, 'filled', 558, '2026-01-19 09:47:00', '2026-01-19 09:47:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4b5660d1-a0b8-56db-a7b7-6defe84f1932', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 81, 44350, 'filled', 539, '2026-01-21 13:26:00', '2026-01-21 13:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('765e6e50-c0e3-5cce-b5c5-f68c9980f6a5', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 84, 44350, 'filled', 559, '2026-01-21 11:21:00', '2026-01-21 11:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9ee33bcd-5668-5af0-9d9c-962937fed774', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 19, 203000, 'filled', 579, '2026-01-27 14:30:00', '2026-01-27 14:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099b2cd4-5d35-54db-8cc4-e16d8379d722', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 203000, 'filled', 548, '2026-01-27 10:03:00', '2026-01-27 10:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b336bb5c-8487-5a66-8b69-626a10b9daf9', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 84, 43950, 'filled', 554, '2026-01-28 10:29:00', '2026-01-28 10:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fc3348e9-9449-57ad-a749-326bcfe59ea3', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 86, 43150, 'filled', 557, '2026-01-29 11:35:00', '2026-01-29 11:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('023b3304-59af-582f-b129-7726cbdb4919', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 204000, 'filled', 551, '2026-02-06 12:38:00', '2026-02-06 12:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('039c67fc-38a2-59c3-a296-5b5dc3731790', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 86, 41700, 'filled', 538, '2026-02-06 13:05:00', '2026-02-06 13:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('92df45ef-c007-53dd-86fc-603b6aac0a48', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 204000, 'filled', 551, '2026-02-06 09:58:00', '2026-02-06 09:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('11784d04-55d2-5565-8a24-0fce59291a1d', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 91, 40950, 'filled', 559, '2026-02-09 11:17:00', '2026-02-09 11:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('3051a925-1a19-5ed1-a314-7ada57a912bb', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 206500, 'filled', 558, '2026-02-10 12:50:00', '2026-02-10 12:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ed2bba5c-1526-5b92-be94-1a58e606b058', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 205000, 'filled', 554, '2026-02-11 09:57:00', '2026-02-11 09:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7c739527-d673-5bf5-b645-e2837f75886c', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 91, 41650, 'filled', 569, '2026-02-12 11:51:00', '2026-02-12 11:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d13a33fe-6d97-54be-9954-fe8f0225054c', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 88, 42550, 'filled', 562, '2026-02-17 09:57:00', '2026-02-17 09:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('33e193e9-79ff-5b4a-99d2-1386ce136a57', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 194500, 'filled', 525, '2026-02-19 10:03:00', '2026-02-19 10:03:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('25dd2db4-3307-5de8-8542-83c89a04fdb7', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 198100, 'filled', 535, '2026-02-20 11:21:00', '2026-02-20 11:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fc6563d5-845f-506a-8d36-a29b53e242d6', 'bot-rsi-01', 'rsi-reversal', '035720', 'sell', 88, 43600, 'filled', 576, '2026-02-25 15:38:00', '2026-02-25 15:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b78d6916-7723-5f49-890a-5be970cb7e6e', 'bot-rsi-01', 'rsi-reversal', '005380', 'sell', 18, 201000, 'filled', 543, '2026-02-25 10:02:00', '2026-02-25 10:02:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('979d6727-bb5f-569f-8ea1-b0a3243f6968', 'bot-rsi-01', 'rsi-reversal', '005380', 'buy', 18, 201000, 'filled', 543, '2026-02-25 09:40:00', '2026-02-25 09:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('97f83645-093b-5ad0-b082-f8395067a795', 'bot-rsi-01', 'rsi-reversal', '035720', 'buy', 87, 43050, 'filled', 562, '2026-02-27 10:22:00', '2026-02-27 10:22:00');

-- ── 포지션 이력 (116건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 30, 208000, 0.0, '2025-12-09 09:31:00', '2025-12-09 09:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 42, 147300, 0.0, '2025-12-10 11:33:00', '2025-12-10 11:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 30, 203500, -149958, '2025-12-11 12:19:00', '2025-12-11 12:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 70100, 0.0, '2025-12-12 10:29:00', '2025-12-12 10:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 42, 149700, 85396, '2025-12-17 13:27:00', '2025-12-17 13:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 41, 149700, 0.0, '2025-12-17 09:07:00', '2025-12-17 09:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 89, 70400, 11349, '2025-12-18 14:33:00', '2025-12-18 14:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 31, 201000, 0.0, '2025-12-19 10:04:00', '2025-12-19 10:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 41, 142800, -297244, '2025-12-22 10:47:00', '2025-12-22 10:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 89, 69600, 0.0, '2025-12-22 09:31:00', '2025-12-22 09:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 89, 68900, -77324, '2025-12-24 14:56:00', '2025-12-24 14:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 90, 68900, 0.0, '2025-12-24 10:33:00', '2025-12-24 10:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 31, 216000, 448595, '2025-12-25 15:33:00', '2025-12-25 15:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 28, 216000, 0.0, '2025-12-25 10:53:00', '2025-12-25 10:53:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 90, 66700, -212707, '2025-12-26 10:31:00', '2025-12-26 10:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 41, 151600, 0.0, '2025-12-29 11:28:00', '2025-12-29 11:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 41, 150400, -64308, '2025-12-30 11:02:00', '2025-12-30 11:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 96, 64900, 0.0, '2025-12-31 10:59:00', '2025-12-31 10:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 28, 215000, -42749, '2026-01-01 10:02:00', '2026-01-01 10:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 42, 147000, 0.0, '2026-01-01 11:01:00', '2026-01-01 11:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 96, 65600, 51771, '2026-01-05 15:58:00', '2026-01-05 15:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 210500, 0.0, '2026-01-05 10:37:00', '2026-01-05 10:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 94, 66200, 0.0, '2026-01-06 10:07:00', '2026-01-06 10:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 42, 150600, 135703, '2026-01-08 12:08:00', '2026-01-08 12:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 29, 214000, 86295, '2026-01-08 13:07:00', '2026-01-08 13:07:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 41, 150600, 0.0, '2026-01-08 09:38:00', '2026-01-08 09:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 28, 216000, 0.0, '2026-01-09 11:40:00', '2026-01-09 11:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 28, 218000, 41045, '2026-01-12 14:55:00', '2026-01-12 14:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 41, 140200, -440483, '2026-01-13 15:13:00', '2026-01-13 15:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 44, 140200, 0.0, '2026-01-13 10:50:00', '2026-01-13 10:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 28, 222000, 0.0, '2026-01-14 10:50:00', '2026-01-14 10:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 44, 139000, -67784, '2026-01-16 13:37:00', '2026-01-16 13:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 44, 139000, 0.0, '2026-01-16 09:46:00', '2026-01-16 09:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 28, 225500, 82531, '2026-01-19 15:33:00', '2026-01-19 15:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 27, 225500, 0.0, '2026-01-19 11:27:00', '2026-01-19 11:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 94, 70400, 378587, '2026-01-20 10:34:00', '2026-01-20 10:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 44, 144500, 226423, '2026-01-20 11:42:00', '2026-01-20 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 87, 71500, 0.0, '2026-01-21 11:15:00', '2026-01-21 11:15:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 27, 222000, -109185, '2026-01-22 10:45:00', '2026-01-22 10:45:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 43, 143600, 0.0, '2026-01-22 09:57:00', '2026-01-22 09:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 27, 231000, 0.0, '2026-01-23 11:34:00', '2026-01-23 11:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 87, 72900, 106262, '2026-01-26 12:25:00', '2026-01-26 12:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 27, 230500, -28748, '2026-01-27 12:34:00', '2026-01-27 12:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 87, 71500, 0.0, '2026-01-27 11:29:00', '2026-01-27 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 27, 229000, 0.0, '2026-01-28 11:40:00', '2026-01-28 11:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 43, 148500, 195055, '2026-01-29 15:33:00', '2026-01-29 15:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 87, 70600, -93348, '2026-01-29 11:01:00', '2026-01-29 11:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 88, 70600, 0.0, '2026-01-29 11:59:00', '2026-01-29 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 88, 70600, -15221, '2026-02-02 13:00:00', '2026-02-02 13:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 27, 222000, -203685, '2026-02-03 13:24:00', '2026-02-03 13:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 28, 222000, 0.0, '2026-02-03 09:26:00', '2026-02-03 09:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 44, 141600, 0.0, '2026-02-04 11:48:00', '2026-02-04 11:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 88, 71000, 0.0, '2026-02-06 11:59:00', '2026-02-06 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 44, 141300, -28433, '2026-02-09 14:37:00', '2026-02-09 14:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 88, 71300, 11028, '2026-02-09 12:00:00', '2026-02-09 12:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 87, 71300, 0.0, '2026-02-09 10:01:00', '2026-02-09 10:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 28, 220500, -57126, '2026-02-10 11:48:00', '2026-02-10 11:48:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 87, 71200, -23876, '2026-02-10 13:22:00', '2026-02-10 13:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 28, 220500, 0.0, '2026-02-10 11:31:00', '2026-02-10 11:31:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 28, 219000, -57024, '2026-02-11 10:41:00', '2026-02-11 10:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 41, 149900, 0.0, '2026-02-11 10:52:00', '2026-02-11 10:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 214000, 0.0, '2026-02-12 11:51:00', '2026-02-12 11:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 41, 153400, 128091, '2026-02-13 14:37:00', '2026-02-13 14:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 39, 160200, 0.0, '2026-02-16 09:55:00', '2026-02-16 09:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 85, 73000, 0.0, '2026-02-17 11:41:00', '2026-02-17 11:41:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 29, 204000, -304494, '2026-02-18 12:06:00', '2026-02-18 12:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 30, 204000, 0.0, '2026-02-18 11:58:00', '2026-02-18 11:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 39, 164000, 132530, '2026-02-19 15:35:00', '2026-02-19 15:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 85, 71400, -150869, '2026-02-20 12:56:00', '2026-02-20 12:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 87, 71400, 0.0, '2026-02-20 11:06:00', '2026-02-20 11:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'buy', 37, 166900, 0.0, '2026-02-23 11:35:00', '2026-02-23 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 30, 203500, -29958, '2026-02-24 12:00:00', '2026-02-24 12:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 87, 70700, -75970, '2026-02-25 13:22:00', '2026-02-25 13:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 88, 70700, 0.0, '2026-02-25 11:02:00', '2026-02-25 11:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 29, 215500, 0.0, '2026-02-26 11:24:00', '2026-02-26 11:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '000660', 'sell', 37, 171100, 139889, '2026-03-02 15:17:00', '2026-03-02 15:17:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 17, 218500, 0.0, '2025-12-10 11:13:00', '2025-12-10 11:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 75, 49350, 0.0, '2025-12-11 11:00:00', '2025-12-11 11:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 17, 215000, -68454, '2025-12-16 10:50:00', '2025-12-16 10:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 17, 214500, 0.0, '2025-12-17 11:23:00', '2025-12-17 11:23:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 17, 219500, 75858, '2025-12-23 14:59:00', '2025-12-23 14:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 75, 48000, -110070, '2025-12-24 10:22:00', '2025-12-24 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 78, 48000, 0.0, '2025-12-24 09:46:00', '2025-12-24 09:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 17, 216000, 0.0, '2025-12-26 11:34:00', '2025-12-26 11:34:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 78, 47400, -55859, '2025-12-29 13:14:00', '2025-12-29 13:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 79, 47400, 0.0, '2025-12-29 09:29:00', '2025-12-29 09:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 17, 210000, -110747, '2025-12-31 12:19:00', '2025-12-31 12:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 79, 45400, -166787, '2026-01-02 13:27:00', '2026-01-02 13:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 84, 44400, 0.0, '2026-01-05 10:49:00', '2026-01-05 10:49:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 208000, 0.0, '2026-01-06 11:19:00', '2026-01-06 11:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 199800, -156411, '2026-01-12 15:40:00', '2026-01-12 15:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 198500, 0.0, '2026-01-13 09:10:00', '2026-01-13 09:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 84, 46050, 129123, '2026-01-14 13:17:00', '2026-01-14 13:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 81, 46050, 0.0, '2026-01-14 09:02:00', '2026-01-14 09:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 195800, -57235, '2026-01-19 13:28:00', '2026-01-19 13:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 19, 195800, 0.0, '2026-01-19 09:47:00', '2026-01-19 09:47:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 81, 44350, -146501, '2026-01-21 13:26:00', '2026-01-21 13:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 84, 44350, 0.0, '2026-01-21 11:21:00', '2026-01-21 11:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 19, 203000, 127350, '2026-01-27 14:30:00', '2026-01-27 14:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 203000, 0.0, '2026-01-27 10:03:00', '2026-01-27 10:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 84, 43950, -42645, '2026-01-28 10:29:00', '2026-01-28 10:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 86, 43150, 0.0, '2026-01-29 11:35:00', '2026-01-29 11:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 204000, 9003, '2026-02-06 12:38:00', '2026-02-06 12:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 86, 41700, -133486, '2026-02-06 13:05:00', '2026-02-06 13:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 204000, 0.0, '2026-02-06 09:58:00', '2026-02-06 09:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 91, 40950, 0.0, '2026-02-09 11:17:00', '2026-02-09 11:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 206500, 35893, '2026-02-10 12:50:00', '2026-02-10 12:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 205000, 0.0, '2026-02-11 09:57:00', '2026-02-11 09:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 91, 41650, 54414, '2026-02-12 11:51:00', '2026-02-12 11:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 88, 42550, 0.0, '2026-02-17 09:57:00', '2026-02-17 09:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 194500, -197577, '2026-02-19 10:03:00', '2026-02-19 10:03:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 198100, 0.0, '2026-02-20 11:21:00', '2026-02-20 11:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'sell', 88, 43600, 82999, '2026-02-25 15:38:00', '2026-02-25 15:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'sell', 18, 201000, 43336, '2026-02-25 10:02:00', '2026-02-25 10:02:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '005380', 'buy', 18, 201000, 0.0, '2026-02-25 09:40:00', '2026-02-25 09:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-rsi-01', '035720', 'buy', 87, 43050, 0.0, '2026-02-27 10:22:00', '2026-02-27 10:22:00');

-- ── 최종 포지션 (5건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 88, 70700, 0.0, '2026-03-02 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 29, 215500, 0.0, '2026-03-02 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '000660', 0, 0.0, 144835, '2026-03-02 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '005380', 18, 201000, 0.0, '2026-03-02 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-rsi-01', '035720', 87, 43050, 0.0, '2026-03-02 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 25000000, 0, 0.0, 241375998, 228598756);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-rsi-01', 15000000, 0, 0.0, 77583639, 69520854);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 100000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 40000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 60000000);

-- ── 자금 변동 이력 (118건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 25000000, '초기 할당', '2025-12-09 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6240936, 'NAVER 30주 매수', '2025-12-09 09:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'allocate', 15000000, '초기 할당', '2025-12-10 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3715057, '현대차 17주 매수', '2025-12-10 11:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6187528, 'SK하이닉스 42주 매수', '2025-12-10 11:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3701805, '카카오 75주 매수', '2025-12-11 11:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6104084, 'NAVER 30주 매도', '2025-12-11 12:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6239836, '삼성전자 89주 매수', '2025-12-12 10:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3654452, '현대차 17주 매도', '2025-12-16 10:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6138621, 'SK하이닉스 41주 매수', '2025-12-17 09:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3647047, '현대차 17주 매수', '2025-12-17 11:23:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6286457, 'SK하이닉스 42주 매도', '2025-12-17 13:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6264660, '삼성전자 89주 매도', '2025-12-18 14:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6231935, 'NAVER 31주 매수', '2025-12-19 10:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6195329, '삼성전자 89주 매수', '2025-12-22 09:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5853922, 'SK하이닉스 41주 매도', '2025-12-22 10:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3730940, '현대차 17주 매도', '2025-12-23 14:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3744562, '카카오 78주 매수', '2025-12-24 09:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3599460, '카카오 75주 매도', '2025-12-24 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6201930, '삼성전자 90주 매수', '2025-12-24 10:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6131180, '삼성전자 89주 매도', '2025-12-24 14:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6048907, 'NAVER 28주 매수', '2025-12-25 10:53:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6694996, 'NAVER 31주 매도', '2025-12-25 15:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6002100, '삼성전자 90주 매도', '2025-12-26 10:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3672551, '현대차 17주 매수', '2025-12-26 11:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3745162, '카카오 79주 매수', '2025-12-29 09:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6216532, 'SK하이닉스 41주 매수', '2025-12-29 11:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3696645, '카카오 78주 매도', '2025-12-29 13:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6165475, 'SK하이닉스 41주 매도', '2025-12-30 11:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6231335, '삼성전자 96주 매수', '2025-12-31 10:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3569464, '현대차 17주 매도', '2025-12-31 12:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6019097, 'NAVER 28주 매도', '2026-01-01 10:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6174926, 'SK하이닉스 42주 매수', '2026-01-01 11:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3586062, '카카오 79주 매도', '2026-01-02 13:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6105416, 'NAVER 29주 매수', '2026-01-05 10:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3730159, '카카오 84주 매수', '2026-01-05 10:49:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6296655, '삼성전자 96주 매도', '2026-01-05 15:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6223733, '삼성전자 94주 매수', '2026-01-06 10:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3744562, '현대차 18주 매수', '2026-01-06 11:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6175526, 'SK하이닉스 41주 매수', '2026-01-08 09:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6324251, 'SK하이닉스 42주 매도', '2026-01-08 12:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6205069, 'NAVER 29주 매도', '2026-01-08 13:07:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6048907, 'NAVER 28주 매수', '2026-01-09 11:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6103084, 'NAVER 28주 매도', '2026-01-12 14:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3595861, '현대차 18주 매도', '2026-01-12 15:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3573536, '현대차 18주 매수', '2026-01-13 09:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6169725, 'SK하이닉스 44주 매수', '2026-01-13 10:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5747338, 'SK하이닉스 41주 매도', '2026-01-13 15:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3730610, '카카오 81주 매수', '2026-01-14 09:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6216932, 'NAVER 28주 매수', '2026-01-14 10:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3867620, '카카오 84주 매도', '2026-01-14 13:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6116917, 'SK하이닉스 44주 매수', '2026-01-16 09:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6115083, 'SK하이닉스 44주 매도', '2026-01-16 13:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3720758, '현대차 19주 매수', '2026-01-19 09:47:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6089413, 'NAVER 27주 매수', '2026-01-19 11:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3523871, '현대차 18주 매도', '2026-01-19 13:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6313053, 'NAVER 28주 매도', '2026-01-19 15:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6616607, '삼성전자 94주 매도', '2026-01-20 10:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6357046, 'SK하이닉스 44주 매도', '2026-01-20 11:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6221433, '삼성전자 87주 매수', '2026-01-21 11:15:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3725959, '카카오 84주 매수', '2026-01-21 11:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3591811, '카카오 81주 매도', '2026-01-21 13:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6175726, 'SK하이닉스 43주 매수', '2026-01-22 09:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5993101, 'NAVER 27주 매도', '2026-01-22 10:45:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6237936, 'NAVER 27주 매수', '2026-01-23 11:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6341349, '삼성전자 87주 매도', '2026-01-26 12:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3654548, '현대차 18주 매수', '2026-01-27 10:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6221433, '삼성전자 87주 매수', '2026-01-27 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6222566, 'NAVER 27주 매도', '2026-01-27 12:34:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3856421, '현대차 19주 매도', '2026-01-27 14:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3691246, '카카오 84주 매도', '2026-01-28 10:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6183927, 'NAVER 27주 매수', '2026-01-28 11:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6141279, '삼성전자 87주 매도', '2026-01-29 11:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3711457, '카카오 86주 매수', '2026-01-29 11:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6213732, '삼성전자 88주 매수', '2026-01-29 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6384542, 'SK하이닉스 43주 매도', '2026-01-29 15:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6211868, '삼성전자 88주 매도', '2026-02-02 13:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6216932, 'NAVER 28주 매수', '2026-02-03 09:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5993101, 'NAVER 27주 매도', '2026-02-03 13:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6231335, 'SK하이닉스 44주 매수', '2026-02-04 11:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3672551, '현대차 18주 매수', '2026-02-06 09:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6248937, '삼성전자 88주 매수', '2026-02-06 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3671449, '현대차 18주 매도', '2026-02-06 12:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3585662, '카카오 86주 매도', '2026-02-06 13:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6204030, '삼성전자 87주 매수', '2026-02-09 10:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3727009, '카카오 91주 매수', '2026-02-09 11:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6273459, '삼성전자 88주 매도', '2026-02-09 12:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6216267, 'SK하이닉스 44주 매도', '2026-02-09 14:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6174926, 'NAVER 28주 매수', '2026-02-10 11:31:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6173074, 'NAVER 28주 매도', '2026-02-10 11:48:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3716442, '현대차 18주 매도', '2026-02-10 12:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6193471, '삼성전자 87주 매도', '2026-02-10 13:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3690554, '현대차 18주 매수', '2026-02-11 09:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6131080, 'NAVER 28주 매도', '2026-02-11 10:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6146822, 'SK하이닉스 41주 매수', '2026-02-11 10:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6206931, 'NAVER 29주 매수', '2026-02-12 11:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3789581, '카카오 91주 매도', '2026-02-12 11:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6288457, 'SK하이닉스 41주 매도', '2026-02-13 14:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6248737, 'SK하이닉스 39주 매수', '2026-02-16 09:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3744962, '카카오 88주 매수', '2026-02-17 09:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6205931, '삼성전자 85주 매수', '2026-02-17 11:41:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6120918, 'NAVER 30주 매수', '2026-02-18 11:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 5915113, 'NAVER 29주 매도', '2026-02-18 12:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3500475, '현대차 18주 매도', '2026-02-19 10:03:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6395041, 'SK하이닉스 39주 매도', '2026-02-19 15:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6212732, '삼성전자 87주 매수', '2026-02-20 11:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3566335, '현대차 18주 매수', '2026-02-20 11:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6068090, '삼성전자 85주 매도', '2026-02-20 12:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6176226, 'SK하이닉스 37주 매수', '2026-02-23 11:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6104084, 'NAVER 30주 매도', '2026-02-24 12:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3618543, '현대차 18주 매수', '2026-02-25 09:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3617457, '현대차 18주 매도', '2026-02-25 10:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6222533, '삼성전자 88주 매수', '2026-02-25 11:02:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6149977, '삼성전자 87주 매도', '2026-02-25 13:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', 3836224, '카카오 88주 매도', '2026-02-25 15:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -6250437, 'NAVER 29주 매수', '2026-02-26 11:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-rsi-01', 'trade', -3745912, '카카오 87주 매수', '2026-02-27 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 6329750, 'SK하이닉스 37주 매도', '2026-03-02 15:17:00');

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
