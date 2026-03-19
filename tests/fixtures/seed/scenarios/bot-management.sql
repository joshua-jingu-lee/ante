-- 시나리오: bot-management
-- 생성: generate_scenario.py (seed=123)
-- 생성일: 2026-03-19

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'active', '2026-02-02 09:00:00', 'SMA 5/20 크로스오버 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', '2026-01-18 09:00:00', '20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('mean-revert', '평균회귀', '1.2.0', 'strategies/mean_revert.py', 'active', '2026-02-02 09:00:00', '볼린저밴드 기반 평균회귀 전략', 'strategy-dev-02');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('broken-strategy', 'Broken Strategy', '0.1.0', 'strategies/broken.py', 'registered', '2026-03-05 09:00:00', '오류 테스트용 전략', 'seed');

-- ── 봇 ──────────────────────────────────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-sma-01', 'SMA 크로스 봇', 'sma-cross', 'paper', '{"bot_id": "bot-sma-01", "strategy_id": "sma-cross", "name": "SMA 크로스 봇", "bot_type": "paper", "interval_seconds": 60, "symbols": ["005930"]}', 'created', '2026-03-12 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-momentum-01', '모멘텀 추세 봇', 'momentum-v2', 'live', '{"bot_id": "bot-momentum-01", "strategy_id": "momentum-v2", "name": "모멘텀 추세 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "035420", "035720"]}', 'running', '2026-02-02 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-mean-01', '평균회귀 실전 봇', 'mean-revert', 'live', '{"bot_id": "bot-mean-01", "strategy_id": "mean-revert", "name": "평균회귀 실전 봇", "bot_type": "live", "interval_seconds": 60, "symbols": ["005930", "035420", "000660"]}', 'stopped', '2026-02-17 09:00:00');

INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-err-01', '오류 테스트 봇', 'broken-strategy', 'paper', '{"bot_id": "bot-err-01", "strategy_id": "broken-strategy", "name": "오류 테스트 봇", "bot_type": "paper", "interval_seconds": 60}', 'error', '2026-03-09 09:00:00');

-- ── 거래 내역 (83건) ────────────────────────
-- bot-momentum-01: 59건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a803ad04-c6f6-5bb7-ad82-f87b689c887b', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72400, 'filled', 554, '2025-12-19 10:17:00', '2025-12-19 10:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9a70bca9-4a10-535e-8c7d-9fd0ea28dbda', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 72500, 'filled', 555, '2025-12-22 10:24:00', '2025-12-22 10:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8c2d74e8-4c48-58cc-9a8d-b5a6d2c12b7a', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 213000, 'filled', 543, '2025-12-22 10:54:00', '2025-12-22 10:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('36d2b8bc-974f-5278-89b8-9356d0ec0d17', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 218500, 'filled', 557, '2025-12-23 14:21:00', '2025-12-23 14:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aec44eda-8fa0-5801-b470-447ffa3c2525', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 51, 72800, 'filled', 557, '2025-12-23 09:57:00', '2025-12-23 09:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b8796a3-6f78-52d3-ba3a-6768daa84396', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 69, 53800, 'filled', 557, '2025-12-24 09:00:00', '2025-12-24 09:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8530525e-fc21-544e-8392-44ad4601b6f0', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 51, 72000, 'filled', 551, '2025-12-26 10:18:00', '2025-12-26 10:18:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c8092f4a-10f2-5ffc-b498-0455485ab26f', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 69, 53100, 'filled', 550, '2025-12-26 14:30:00', '2025-12-26 14:30:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e170ad1f-6441-5158-a3cc-9dce4df82cd6', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 52, 72000, 'filled', 562, '2025-12-26 10:21:00', '2025-12-26 10:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7712478d-610a-56a8-b076-02aae5914c47', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 73, 51100, 'filled', 560, '2025-12-29 09:25:00', '2025-12-29 09:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('437d1658-1b76-5b14-84fd-24f68e8fb8bc', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 215000, 'filled', 548, '2025-12-30 11:42:00', '2025-12-30 11:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('88a305dd-e794-55da-a122-c8cc138f537d', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 73, 51400, 'filled', 563, '2026-01-01 12:21:00', '2026-01-01 12:21:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39727373-84d4-5790-a65c-9c4e51cdce92', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 72, 51400, 'filled', 555, '2026-01-01 11:29:00', '2026-01-01 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8f9a70a5-7b4a-54ce-9a3a-e71fcfd786d6', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 72, 50300, 'filled', 543, '2026-01-02 12:00:00', '2026-01-02 12:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5fe362c5-8aef-514c-a16d-4d8a0264828f', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 212000, 'filled', 541, '2026-01-05 10:40:00', '2026-01-05 10:40:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9d6aaec5-5aed-587e-b0e5-03a0eeea3f1f', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 76, 49000, 'filled', 559, '2026-01-05 11:46:00', '2026-01-05 11:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ca4230d1-7bae-5f70-99bf-07d857325955', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 52, 74200, 'filled', 579, '2026-01-06 14:28:00', '2026-01-06 14:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('72aafdd0-fac0-5556-8bf5-601ff0071c9f', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 17, 219000, 'filled', 558, '2026-01-06 09:00:00', '2026-01-06 09:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('402e0815-2f8e-5c03-a226-581ae13487a4', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 76, 48000, 'filled', 547, '2026-01-07 12:43:00', '2026-01-07 12:43:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1fe78282-3b83-550f-b663-953e320e48ca', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 78, 48000, 'filled', 562, '2026-01-07 11:26:00', '2026-01-07 11:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fa56a5b8-7613-5264-91c4-a4adc7aa4108', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 17, 217500, 'filled', 555, '2026-01-08 15:05:00', '2026-01-08 15:05:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('db35cb38-51f3-58a1-91cd-83d232dcab70', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 74600, 'filled', 560, '2026-01-08 11:24:00', '2026-01-08 11:24:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0db2a51d-b3cd-5db9-872e-96ec6eff9e7b', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 78, 48600, 'filled', 569, '2026-01-09 12:16:00', '2026-01-09 12:16:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0b37ad4c-a089-555b-98f8-325348e201d2', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 74700, 'filled', 560, '2026-01-12 13:22:00', '2026-01-12 13:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7f2a9d2f-b3e9-5f4d-8273-cecaef5309c6', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 80, 46600, 'filled', 559, '2026-01-12 09:56:00', '2026-01-12 09:56:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('aa21ce21-6b87-5d9f-bf91-22378d60e952', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 75200, 'filled', 553, '2026-01-13 10:42:00', '2026-01-13 10:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('cf92a519-a695-5272-ab5a-90291df40adc', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 223500, 'filled', 536, '2026-01-14 09:58:00', '2026-01-14 09:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('c82c52cd-6283-592d-9a51-40d8a9006e39', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 80, 48100, 'filled', 577, '2026-01-16 15:10:00', '2026-01-16 15:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9070683e-d9cd-5f36-a905-316f42c4b521', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 74700, 'filled', 549, '2026-01-16 13:27:00', '2026-01-16 13:27:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7cdc81cd-4271-542e-a935-d945081f1058', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 50, 74700, 'filled', 560, '2026-01-16 10:42:00', '2026-01-16 10:42:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a0f6caf5-0ab3-5571-94e0-09c2ea80afc9', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 228000, 'filled', 547, '2026-01-20 10:10:00', '2026-01-20 10:10:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('48da81a7-1ab2-52b0-9145-3570d489962b', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 50, 76000, 'filled', 570, '2026-01-20 14:32:00', '2026-01-20 14:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8127f3dc-46fb-569a-a327-2fbddee1cd09', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-01-20 11:06:00', '2026-01-20 11:06:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39e396ed-2fbe-5f8b-9498-e40423041638', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 76, 48900, 'filled', 557, '2026-01-21 09:17:00', '2026-01-21 09:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9ace70f0-e70c-554d-968e-d5124d56bc05', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 234500, 'filled', 563, '2026-01-23 11:32:00', '2026-01-23 11:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('57fb0c35-2604-57a4-ba01-fc3458ed9411', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 76, 49800, 'filled', 568, '2026-01-23 10:12:00', '2026-01-23 10:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('f264590a-e9b8-585f-b842-6b6f7773b8f4', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 49, 75700, 'filled', 556, '2026-01-23 09:38:00', '2026-01-23 09:38:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b0d8b6a9-67b2-5d75-bff5-6f6a837d3349', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 49, 77600, 'filled', 570, '2026-01-26 14:08:00', '2026-01-26 14:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('68477f5c-b3bf-52a5-b275-89d290c27047', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 226500, 'filled', 544, '2026-01-28 10:46:00', '2026-01-28 10:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8aa0d94e-2f79-5170-a26c-2be55b9993ce', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 79, 47100, 'filled', 558, '2026-01-29 10:25:00', '2026-01-29 10:25:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6194eeb4-8f00-515d-8af3-4043c440923c', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 48, 77300, 'filled', 557, '2026-02-02 10:44:00', '2026-02-02 10:44:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4a8d8622-dcfc-5e0d-be3d-7aef2b8cb184', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 228000, 'filled', 547, '2026-02-03 15:54:00', '2026-02-03 15:54:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099625e2-1608-5e9f-a66f-9654a4e81798', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 228000, 'filled', 547, '2026-02-03 09:49:00', '2026-02-03 09:49:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('393b488a-2a76-5981-a46f-34829415b07b', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 79, 45200, 'filled', 536, '2026-02-04 13:51:00', '2026-02-04 13:51:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8e49e161-d1f5-5372-b438-494c3f5fcfe5', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 82, 45200, 'filled', 556, '2026-02-04 10:32:00', '2026-02-04 10:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2c40ac3c-76f6-5567-9b6a-0a77d0cd2e89', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 48, 79400, 'filled', 572, '2026-02-05 10:58:00', '2026-02-05 10:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e1458b94-f14f-51ce-9896-b27e8aa4d3f6', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 47, 79400, 'filled', 560, '2026-02-05 11:52:00', '2026-02-05 11:52:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2e6e1dbd-0b22-5ca4-b5ae-194b150512b3', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 82, 45750, 'filled', 563, '2026-02-09 13:17:00', '2026-02-09 13:17:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6487d438-6b7e-56ce-a1fc-7ebf717618ce', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 47, 79400, 'filled', 560, '2026-02-10 14:57:00', '2026-02-10 14:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('1e33fbad-957c-54dd-adb8-92a8bbaddb2d', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 231500, 'filled', 556, '2026-02-11 10:01:00', '2026-02-11 10:01:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0f14fe74-8e3b-5011-8b3b-8513d4d7519f', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 231500, 'filled', 556, '2026-02-11 11:08:00', '2026-02-11 11:08:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('8b401315-60ce-5cf6-9779-0fb3db8c6033', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 47, 79600, 'filled', 561, '2026-02-12 10:55:00', '2026-02-12 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b779fd40-0484-5c5d-a53a-82733f4eb064', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 82, 45250, 'filled', 557, '2026-02-13 10:32:00', '2026-02-13 10:32:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('53192086-1933-54b0-8514-f0ce05553347', 'bot-momentum-01', 'momentum-v2', '035420', 'sell', 16, 223000, 'filled', 535, '2026-02-17 13:14:00', '2026-02-17 13:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('980a0d7b-226c-5045-bdfb-31722675a9a5', 'bot-momentum-01', 'momentum-v2', '005930', 'sell', 47, 79300, 'filled', 559, '2026-02-17 10:55:00', '2026-02-17 10:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b96a9387-a880-5b5e-9c4b-4982bbe4ecf3', 'bot-momentum-01', 'momentum-v2', '005930', 'buy', 47, 79300, 'filled', 559, '2026-02-17 10:22:00', '2026-02-17 10:22:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a0c4ef04-e7e0-5238-8cb1-08f4ce69494c', 'bot-momentum-01', 'momentum-v2', '035720', 'sell', 82, 42000, 'filled', 517, '2026-02-18 11:12:00', '2026-02-18 11:12:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('d433343f-6837-55c9-b629-7e1c6f7de0c9', 'bot-momentum-01', 'momentum-v2', '035420', 'buy', 16, 224500, 'filled', 539, '2026-02-18 11:59:00', '2026-02-18 11:59:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('9db948e2-c621-534c-89e2-7a928fb1a0b4', 'bot-momentum-01', 'momentum-v2', '035720', 'buy', 88, 42150, 'filled', 556, '2026-02-19 09:18:00', '2026-02-19 09:18:00');

-- bot-mean-01: 24건
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('4a6352b0-97ff-5e11-aeb4-de733adee207', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 154400, 'filled', 93, '2025-12-19 11:55:00', '2025-12-19 11:55:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2b5ac4a2-dd44-50b1-adaf-8dd200127517', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 72400, 'filled', 109, '2025-12-22 10:46:00', '2025-12-22 10:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('43e3780d-fd07-5dc7-8558-1e98bdee8232', 'bot-mean-01', 'mean-revert', '035420', 'buy', 3, 215500, 'filled', 97, '2025-12-23 09:29:00', '2025-12-23 09:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('fc703e83-cc93-5a06-b136-1eb9f72735be', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 153000, 'filled', 92, '2025-12-25 11:20:00', '2025-12-25 11:20:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('324424ce-0db9-5587-8061-86cf9572e1a8', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 153000, 'filled', 92, '2025-12-25 09:19:00', '2025-12-25 09:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b2942de1-cdd3-5381-b66c-e6a620bf215c', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 70600, 'filled', 106, '2025-12-26 11:29:00', '2025-12-26 11:29:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2f9b56ef-d6a9-5809-986c-38b106d002e8', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 70600, 'filled', 106, '2025-12-26 09:28:00', '2025-12-26 09:28:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('ba25c3cb-8f4c-5dd2-9438-f76326095cc7', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 160100, 'filled', 96, '2026-01-01 13:50:00', '2026-01-01 13:50:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('79a62d40-e264-5237-99dc-76e4bbe32d56', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 71100, 'filled', 107, '2026-01-01 11:57:00', '2026-01-01 11:57:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('031b9172-340e-53c7-b7df-05cb7a0f73d7', 'bot-mean-01', 'mean-revert', '035420', 'sell', 3, 219500, 'filled', 99, '2026-01-05 12:04:00', '2026-01-05 12:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('7cbe6dce-6e5c-5797-b498-635097fe07bf', 'bot-mean-01', 'mean-revert', '035420', 'buy', 3, 214500, 'filled', 97, '2026-01-06 09:19:00', '2026-01-06 09:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('2b7a2422-f3ff-5815-909b-de6e45c2e7a8', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 165700, 'filled', 99, '2026-01-09 10:00:00', '2026-01-09 10:00:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('b8e3b25a-86c9-55be-836b-f15092ce26f4', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 73600, 'filled', 110, '2026-01-12 11:04:00', '2026-01-12 11:04:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('0bfa8cb9-085b-52b8-8c1f-927bbcc044f1', 'bot-mean-01', 'mean-revert', '035420', 'sell', 3, 216500, 'filled', 97, '2026-01-14 11:13:00', '2026-01-14 11:13:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('379e4df8-363e-5f0a-ad40-cbd4af065f5c', 'bot-mean-01', 'mean-revert', '035420', 'buy', 3, 211000, 'filled', 95, '2026-01-15 10:19:00', '2026-01-15 10:19:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('52bfee7a-ca84-553f-a2ee-96fa094186da', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 157400, 'filled', 94, '2026-01-16 14:46:00', '2026-01-16 14:46:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('e444474f-59e3-54cc-b121-2a710aa461ea', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 157400, 'filled', 94, '2026-01-16 10:35:00', '2026-01-16 10:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('a58102a1-d531-58a4-9559-6a6313250adc', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 73000, 'filled', 109, '2026-01-20 10:58:00', '2026-01-20 10:58:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('099e304e-14af-502c-8da6-7befa03c19f1', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 72800, 'filled', 109, '2026-01-21 10:26:00', '2026-01-21 10:26:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('17f42fd7-290b-5760-be97-6d3f79e831ba', 'bot-mean-01', 'mean-revert', '000660', 'sell', 4, 160300, 'filled', 96, '2026-01-22 12:14:00', '2026-01-22 12:14:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('39de01f4-c200-5a3f-8f4a-e20af9a62928', 'bot-mean-01', 'mean-revert', '000660', 'buy', 4, 158900, 'filled', 95, '2026-01-27 09:33:00', '2026-01-27 09:33:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('5feba753-a8ce-5a98-a037-bf7601b0dfb0', 'bot-mean-01', 'mean-revert', '035420', 'sell', 3, 224000, 'filled', 101, '2026-01-28 13:37:00', '2026-01-28 13:37:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('6423a060-e617-5705-8320-5e9f64d3b059', 'bot-mean-01', 'mean-revert', '005930', 'sell', 10, 70400, 'filled', 106, '2026-01-28 10:35:00', '2026-01-28 10:35:00');
INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, commission, timestamp, created_at)
VALUES ('31758323-bbd6-5d4d-b012-5a4c506455ca', 'bot-mean-01', 'mean-revert', '005930', 'buy', 10, 70400, 'filled', 106, '2026-01-28 09:58:00', '2026-01-28 09:58:00');

-- ── 포지션 이력 (83건) ──────────────────────
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72400, 0.0, '2025-12-19 10:17:00', '2025-12-19 10:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 72500, -3959, '2025-12-22 10:24:00', '2025-12-22 10:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 213000, 0.0, '2025-12-22 10:54:00', '2025-12-22 10:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 218500, 84400, '2025-12-23 14:21:00', '2025-12-23 14:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 51, 72800, 0.0, '2025-12-23 09:57:00', '2025-12-23 09:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 69, 53800, 0.0, '2025-12-24 09:00:00', '2025-12-24 09:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 51, 72000, -49797, '2025-12-26 10:18:00', '2025-12-26 10:18:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 69, 53100, -57277, '2025-12-26 14:30:00', '2025-12-26 14:30:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 52, 72000, 0.0, '2025-12-26 10:21:00', '2025-12-26 10:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 73, 51100, 0.0, '2025-12-29 09:25:00', '2025-12-29 09:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 215000, 0.0, '2025-12-30 11:42:00', '2025-12-30 11:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 73, 51400, 12707, '2026-01-01 12:21:00', '2026-01-01 12:21:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 72, 51400, 0.0, '2026-01-01 11:29:00', '2026-01-01 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 72, 50300, -88073, '2026-01-02 12:00:00', '2026-01-02 12:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 212000, -59830, '2026-01-05 10:40:00', '2026-01-05 10:40:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 76, 49000, 0.0, '2026-01-05 11:46:00', '2026-01-05 11:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 52, 74200, 104947, '2026-01-06 14:28:00', '2026-01-06 14:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 17, 219000, 0.0, '2026-01-06 09:00:00', '2026-01-06 09:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 76, 48000, -84937, '2026-01-07 12:43:00', '2026-01-07 12:43:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 78, 48000, 0.0, '2026-01-07 11:26:00', '2026-01-07 11:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 17, 217500, -34559, '2026-01-08 15:05:00', '2026-01-08 15:05:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 74600, 0.0, '2026-01-08 11:24:00', '2026-01-08 11:24:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 78, 48600, 37512, '2026-01-09 12:16:00', '2026-01-09 12:16:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 74700, -4150, '2026-01-12 13:22:00', '2026-01-12 13:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 80, 46600, 0.0, '2026-01-12 09:56:00', '2026-01-12 09:56:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 75200, 0.0, '2026-01-13 10:42:00', '2026-01-13 10:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 223500, 0.0, '2026-01-14 09:58:00', '2026-01-14 09:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 80, 48100, 110573, '2026-01-16 15:10:00', '2026-01-16 15:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 74700, -33468, '2026-01-16 13:27:00', '2026-01-16 13:27:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 50, 74700, 0.0, '2026-01-16 10:42:00', '2026-01-16 10:42:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 228000, 63063, '2026-01-20 10:10:00', '2026-01-20 10:10:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 50, 76000, 55690, '2026-01-20 14:32:00', '2026-01-20 14:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 228000, 0.0, '2026-01-20 11:06:00', '2026-01-20 11:06:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 76, 48900, 0.0, '2026-01-21 09:17:00', '2026-01-21 09:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 234500, 94807, '2026-01-23 11:32:00', '2026-01-23 11:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 76, 49800, 59127, '2026-01-23 10:12:00', '2026-01-23 10:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 49, 75700, 0.0, '2026-01-23 09:38:00', '2026-01-23 09:38:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 49, 77600, 83784, '2026-01-26 14:08:00', '2026-01-26 14:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 226500, 0.0, '2026-01-28 10:46:00', '2026-01-28 10:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 79, 47100, 0.0, '2026-01-29 10:25:00', '2026-01-29 10:25:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 48, 77300, 0.0, '2026-02-02 10:44:00', '2026-02-02 10:44:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 228000, 15063, '2026-02-03 15:54:00', '2026-02-03 15:54:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 228000, 0.0, '2026-02-03 09:49:00', '2026-02-03 09:49:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 79, 45200, -158849, '2026-02-04 13:51:00', '2026-02-04 13:51:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 82, 45200, 0.0, '2026-02-04 10:32:00', '2026-02-04 10:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 48, 79400, 91462, '2026-02-05 10:58:00', '2026-02-05 10:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 47, 79400, 0.0, '2026-02-05 11:52:00', '2026-02-05 11:52:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 82, 45750, 35909, '2026-02-09 13:17:00', '2026-02-09 13:17:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 47, 79400, -9143, '2026-02-10 14:57:00', '2026-02-10 14:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 231500, 46925, '2026-02-11 10:01:00', '2026-02-11 10:01:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 231500, 0.0, '2026-02-11 11:08:00', '2026-02-11 11:08:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 47, 79600, 0.0, '2026-02-12 10:55:00', '2026-02-12 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 82, 45250, 0.0, '2026-02-13 10:32:00', '2026-02-13 10:32:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'sell', 16, 223000, -144741, '2026-02-17 13:14:00', '2026-02-17 13:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'sell', 47, 79300, -23231, '2026-02-17 10:55:00', '2026-02-17 10:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '005930', 'buy', 47, 79300, 0.0, '2026-02-17 10:22:00', '2026-02-17 10:22:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'sell', 82, 42000, -274938, '2026-02-18 11:12:00', '2026-02-18 11:12:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035420', 'buy', 16, 224500, 0.0, '2026-02-18 11:59:00', '2026-02-18 11:59:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-momentum-01', '035720', 'buy', 88, 42150, 0.0, '2026-02-19 09:18:00', '2026-02-19 09:18:00');

INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 154400, 0.0, '2025-12-19 11:55:00', '2025-12-19 11:55:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 72400, 0.0, '2025-12-22 10:46:00', '2025-12-22 10:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'buy', 3, 215500, 0.0, '2025-12-23 09:29:00', '2025-12-23 09:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 153000, -7100, '2025-12-25 11:20:00', '2025-12-25 11:20:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 153000, 0.0, '2025-12-25 09:19:00', '2025-12-25 09:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 70600, -19730, '2025-12-26 11:29:00', '2025-12-26 11:29:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 70600, 0.0, '2025-12-26 09:28:00', '2025-12-26 09:28:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 160100, 26831, '2026-01-01 13:50:00', '2026-01-01 13:50:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 71100, 3258, '2026-01-01 11:57:00', '2026-01-01 11:57:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'sell', 3, 219500, 10386, '2026-01-05 12:04:00', '2026-01-05 12:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'buy', 3, 214500, 0.0, '2026-01-06 09:19:00', '2026-01-06 09:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 165700, 0.0, '2026-01-09 10:00:00', '2026-01-09 10:00:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 73600, 0.0, '2026-01-12 11:04:00', '2026-01-12 11:04:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'sell', 3, 216500, 4409, '2026-01-14 11:13:00', '2026-01-14 11:13:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'buy', 3, 211000, 0.0, '2026-01-15 10:19:00', '2026-01-15 10:19:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 157400, -34742, '2026-01-16 14:46:00', '2026-01-16 14:46:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 157400, 0.0, '2026-01-16 10:35:00', '2026-01-16 10:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 73000, -7788, '2026-01-20 10:58:00', '2026-01-20 10:58:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 72800, 0.0, '2026-01-21 10:26:00', '2026-01-21 10:26:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'sell', 4, 160300, 10029, '2026-01-22 12:14:00', '2026-01-22 12:14:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '000660', 'buy', 4, 158900, 0.0, '2026-01-27 09:33:00', '2026-01-27 09:33:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '035420', 'sell', 3, 224000, 37353, '2026-01-28 13:37:00', '2026-01-28 13:37:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'sell', 10, 70400, -25725, '2026-01-28 10:35:00', '2026-01-28 10:35:00');
INSERT INTO position_history (bot_id, symbol, action, quantity, price, pnl, timestamp, created_at)
VALUES ('bot-mean-01', '005930', 'buy', 10, 70400, 0.0, '2026-01-28 09:58:00', '2026-01-28 09:58:00');

-- ── 최종 포지션 (6건) ────────────────────
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '005930', 47, 79300, 0.0, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035420', 16, 224500, 0.0, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-momentum-01', '035720', 88, 42150, 0.0, '2026-02-19 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '000660', 4, 158900, 0.0, '2026-01-29 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '005930', 10, 70400, 0.0, '2026-01-29 15:30:00');
INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, realized_pnl, updated_at)
VALUES ('bot-mean-01', '035420', 0, 0.0, 52148, '2026-01-29 15:30:00');

-- ── 예산 ────────────────────────────────────────────
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-sma-01', 1000000, 1000000, 0.0, 0.0, 0.0);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-momentum-01', 15000000, 0, 0.0, 114629693, 103453217);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-mean-01', 3000000, 316679, 0.0, 8679902, 7336181);
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-err-01', 500000, 500000, 0.0, 0.0, 0.0);

-- ── Treasury 상태 ────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 100000000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 19500000);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 80500000);

-- ── 자금 변동 이력 (87건) ────────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'allocate', 15000000, '초기 할당', '2025-12-19 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'allocate', 3000000, '초기 할당', '2025-12-19 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3692954, '삼성전자 51주 매수', '2025-12-19 10:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -617693, 'SK하이닉스 4주 매수', '2025-12-19 11:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3696945, '삼성전자 51주 매도', '2025-12-22 10:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -724109, '삼성전자 10주 매수', '2025-12-22 10:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3621543, 'NAVER 17주 매수', '2025-12-22 10:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -646597, 'NAVER 3주 매수', '2025-12-23 09:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3713357, '삼성전자 51주 매수', '2025-12-23 09:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3713943, 'NAVER 17주 매도', '2025-12-23 14:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3712757, '카카오 69주 매수', '2025-12-24 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -612092, 'SK하이닉스 4주 매수', '2025-12-25 09:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 611908, 'SK하이닉스 4주 매도', '2025-12-25 11:20:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -706106, '삼성전자 10주 매수', '2025-12-26 09:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3671449, '삼성전자 51주 매도', '2025-12-26 10:18:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3744562, '삼성전자 52주 매수', '2025-12-26 10:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 705894, '삼성전자 10주 매도', '2025-12-26 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3663350, '카카오 69주 매도', '2025-12-26 14:30:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3730860, '카카오 73주 매수', '2025-12-29 09:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3655548, 'NAVER 17주 매수', '2025-12-30 11:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3701355, '카카오 72주 매수', '2026-01-01 11:29:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 710893, '삼성전자 10주 매도', '2026-01-01 11:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3751637, '카카오 73주 매도', '2026-01-01 12:21:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 640304, 'SK하이닉스 4주 매도', '2026-01-01 13:50:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3621057, '카카오 72주 매도', '2026-01-02 12:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3603459, 'NAVER 17주 매도', '2026-01-05 10:40:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3724559, '카카오 76주 매수', '2026-01-05 11:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 658401, 'NAVER 3주 매도', '2026-01-05 12:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3723558, 'NAVER 17주 매수', '2026-01-06 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -643597, 'NAVER 3주 매수', '2026-01-06 09:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3857821, '삼성전자 52주 매도', '2026-01-06 14:28:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3744562, '카카오 78주 매수', '2026-01-07 11:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3647453, '카카오 76주 매도', '2026-01-07 12:43:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3730560, '삼성전자 50주 매수', '2026-01-08 11:24:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3696945, 'NAVER 17주 매도', '2026-01-08 15:05:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -662899, 'SK하이닉스 4주 매수', '2026-01-09 10:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3790231, '카카오 78주 매도', '2026-01-09 12:16:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3728559, '카카오 80주 매수', '2026-01-12 09:56:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -736110, '삼성전자 10주 매수', '2026-01-12 11:04:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3734440, '삼성전자 50주 매도', '2026-01-12 13:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3685353, '삼성전자 49주 매수', '2026-01-13 10:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3576536, 'NAVER 16주 매수', '2026-01-14 09:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 649403, 'NAVER 3주 매도', '2026-01-14 11:13:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -633095, 'NAVER 3주 매수', '2026-01-15 10:19:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -629694, 'SK하이닉스 4주 매수', '2026-01-16 10:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3735560, '삼성전자 50주 매수', '2026-01-16 10:42:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3659751, '삼성전자 49주 매도', '2026-01-16 13:27:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 629506, 'SK하이닉스 4주 매도', '2026-01-16 14:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3847423, '카카오 80주 매도', '2026-01-16 15:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-sma-01', 'allocate', 1000000, '초기 할당', '2026-01-20 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-err-01', 'allocate', 500000, '초기 할당', '2026-01-20 09:00:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3647453, 'NAVER 16주 매도', '2026-01-20 10:10:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 729891, '삼성전자 10주 매도', '2026-01-20 10:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3648547, 'NAVER 16주 매수', '2026-01-20 11:06:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3799430, '삼성전자 50주 매도', '2026-01-20 14:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3716957, '카카오 76주 매수', '2026-01-21 09:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -728109, '삼성전자 10주 매수', '2026-01-21 10:26:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 641104, 'SK하이닉스 4주 매도', '2026-01-22 12:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3709856, '삼성전자 49주 매수', '2026-01-23 09:38:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3784232, '카카오 76주 매도', '2026-01-23 10:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3751437, 'NAVER 16주 매도', '2026-01-23 11:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3801830, '삼성전자 49주 매도', '2026-01-26 14:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -635695, 'SK하이닉스 4주 매수', '2026-01-27 09:33:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', -704106, '삼성전자 10주 매수', '2026-01-28 09:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 703894, '삼성전자 10주 매도', '2026-01-28 10:35:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3624544, 'NAVER 16주 매수', '2026-01-28 10:46:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-mean-01', 'trade', 671899, 'NAVER 3주 매도', '2026-01-28 13:37:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3721458, '카카오 79주 매수', '2026-01-29 10:25:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3710957, '삼성전자 48주 매수', '2026-02-02 10:44:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3648547, 'NAVER 16주 매수', '2026-02-03 09:49:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3647453, 'NAVER 16주 매도', '2026-02-03 15:54:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3706956, '카카오 82주 매수', '2026-02-04 10:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3570264, '카카오 79주 매도', '2026-02-04 13:51:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3810628, '삼성전자 48주 매도', '2026-02-05 10:58:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3732360, '삼성전자 47주 매수', '2026-02-05 11:52:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3750937, '카카오 82주 매도', '2026-02-09 13:17:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3731240, '삼성전자 47주 매도', '2026-02-10 14:57:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3703444, 'NAVER 16주 매도', '2026-02-11 10:01:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3704556, 'NAVER 16주 매수', '2026-02-11 11:08:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3741761, '삼성전자 47주 매수', '2026-02-12 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3711057, '카카오 82주 매수', '2026-02-13 10:32:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3727659, '삼성전자 47주 매수', '2026-02-17 10:22:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3726541, '삼성전자 47주 매도', '2026-02-17 10:55:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3567465, 'NAVER 16주 매도', '2026-02-17 13:14:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', 3443483, '카카오 82주 매도', '2026-02-18 11:12:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3592539, 'NAVER 16주 매수', '2026-02-18 11:59:00');
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-momentum-01', 'trade', -3709756, '카카오 88주 매수', '2026-02-19 09:18:00');

-- ── 이벤트 로그 (20건) ──────────────────
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-001', 'bot.step.success', '2025-12-19 10:17:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-002', 'bot.step.success', '2025-12-24 09:00:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-003', 'bot.step.success', '2025-12-30 11:42:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-004', 'bot.step.success', '2026-01-05 11:46:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-005', 'bot.step.success', '2026-01-08 15:05:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-006', 'bot.step.success', '2026-01-13 10:42:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-007', 'bot.step.success', '2026-01-20 10:10:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-008', 'bot.step.success', '2026-01-23 10:12:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-009', 'bot.step.success', '2026-02-02 10:44:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-010', 'bot.step.success', '2026-02-05 10:58:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-011', 'bot.step.success', '2026-02-11 11:08:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mome-012', 'bot.step.success', '2026-02-17 10:22:00', '{"bot_id": "bot-momentum-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-001', 'bot.step.success', '2025-12-19 11:55:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-002', 'bot.step.success', '2025-12-26 11:29:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-003', 'bot.step.success', '2026-01-06 09:19:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-004', 'bot.step.success', '2026-01-16 14:46:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-005', 'bot.step.success', '2026-01-27 09:33:00', '{"bot_id": "bot-mean-01", "message": "매매 사이클 완료"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-mean-006', 'bot.stopped', '2026-03-18 15:00:00', '{"bot_id": "bot-mean-01", "message": "Bot 중지됨 — 사용자 요청"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-err--001', 'bot.step.error', '2026-03-16 10:00:00', '{"bot_id": "bot-err-01", "message": "전략 로드 실패: ModuleNotFoundError"}');
INSERT INTO event_log (event_id, event_type, timestamp, payload)
VALUES ('ev-bot-err--002', 'bot.step.error', '2026-03-16 10:00:00', '{"bot_id": "bot-err-01", "message": "전략 초기화 실패: invalid config"}');

-- ── 멤버 ────────────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write", "data:read", "backtest:run", "report:write"]', 'datetime(''now'', ''-60 days'')');
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active', '["strategy:write", "data:read", "backtest:run"]', 'datetime(''now'', ''-45 days'')');
