# CHANGELOG

<!-- version list -->

## v0.6.1 (2026-03-19)

### Bug Fixes

- **build**: Pandas-ta 의존성 버전 스펙 수정
  ([`3bf9125`](https://github.com/joshua-jingu-lee/ante/commit/3bf91251c1d9d801ed6314121791c7cc6b247362))


## v0.6.0 (2026-03-19)

### Bug Fixes

- Asyncio.CancelledError 미재발생 버그 수정 (6건) ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- Display.currency_position 기본값 등록으로 설정 페이지 에러 해결
  ([`b62b59a`](https://github.com/joshua-jingu-lee/ante/commit/b62b59a7c454a475a3101ec0f2a04f23906bda69))

- Docker 시드 로딩 및 trade_id UUID 형식 수정
  ([`6dbed88`](https://github.com/joshua-jingu-lee/ante/commit/6dbed887a62512d95057facba6ab94e48a690139))

- 에픽 통합 테스트 실패 수정 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- 전략 성과 API 경로를 실제 라우트와 일치하도록 수정 ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

- **api**: 백테스트 데이터 API 응답 형식·필드 불일치 수정
  ([`6c66b25`](https://github.com/joshua-jingu-lee/ante/commit/6c66b25847f5ee4f9bb8547806f5db6809f25407))

- **api**: 전략 상세 페이지 weekly-summary API 404 해소
  ([`f47ef69`](https://github.com/joshua-jingu-lee/ante/commit/f47ef6912146777a68fff230047b26acc90d3b8a))

- **bot**: 봇 시작 시 전략별 룰 로드, 중지 시 제거 (#498)
  ([#508](https://github.com/joshua-jingu-lee/ante/pull/508),
  [`4760f47`](https://github.com/joshua-jingu-lee/ante/commit/4760f477787622002d514f1e8837f3e8904cc9dd))

- **ci**: Dev 의존성에 httpx 추가
  ([`58431a4`](https://github.com/joshua-jingu-lee/ante/commit/58431a414ccde43bf4aaaa3fa4bf2582eaa0cfb6))

- **dashboard**: ApprovalType 확장에 따른 누락 엔트리 추가
  ([`2c992b3`](https://github.com/joshua-jingu-lee/ante/commit/2c992b3789d7360df046d6ee4a4dc5693e0af663))

- **dashboard**: 멤버 관리 비밀번호 변경 기능 구현
  ([`be46b6c`](https://github.com/joshua-jingu-lee/ante/commit/be46b6cbfeff616157afec907da0c4e68dab2b09))

- **dashboard**: 백테스트 데이터 페이지 CLI 안내 문구를 `ante feed`로 수정
  ([`e923432`](https://github.com/joshua-jingu-lee/ante/commit/e923432152b41f80fa014af2a33448b14c8e6edf))

- **dashboard**: 사이드바 목업 충실도 미세 조정
  ([`14ec6be`](https://github.com/joshua-jingu-lee/ante/commit/14ec6bedc1da7149b45309169d54bc0b060f51a4))

- **dashboard**: 사이드바 버전을 pyproject.toml에서 빌드 타임 주입
  ([`fc4b3dc`](https://github.com/joshua-jingu-lee/ante/commit/fc4b3dc4faccb7cd8d55cc5cf94103cb0208f022))

- **dashboard**: 에이전트 등록 시 member_type 필드 누락 수정
  ([`cdbb90e`](https://github.com/joshua-jingu-lee/ante/commit/cdbb90e48ef61d45b6713ccb6d1414e18ab5800b))

- **instrument**: 부동소수점 동등 비교를 math.isclose()로 교체
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **logging**: Except-pass 7건에 logger.warning 추가
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **main**: NotificationService 초기화 코드 정리
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **member**: Revoke 시 상태 검증 누락 수정 ([#506](https://github.com/joshua-jingu-lee/ante/pull/506),
  [`afeb63d`](https://github.com/joshua-jingu-lee/ante/commit/afeb63de391874c90a1f3983960564f5ac17c178))

- **rule**: ConfigChangedEvent 수신 시 전역/전략 룰 실제 재로드
  ([#507](https://github.com/joshua-jingu-lee/ante/pull/507),
  [`513ccef`](https://github.com/joshua-jingu-lee/ante/commit/513ccef116d73a569878d4ea48b2e1b136fd18b3))

- **scripts**: Click 8.2+ Sentinel.UNSET 호환성 수정
  ([`1a5b6de`](https://github.com/joshua-jingu-lee/ante/commit/1a5b6deb2de8d0960794c1bdd92e5cfe473d15cf))

- **telegram**: /bots 응답 메시지를 스펙(bot.md)에 맞게 수정
  ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **telegram**: /halt 응답 메시지를 스펙에 맞게 수정 (#540)
  ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **test**: CI에서 scripts/ 모듈 import 실패 수정
  ([`c3928c0`](https://github.com/joshua-jingu-lee/ante/commit/c3928c0948d87067332f7c25f451b46656337641))

- **test**: CLI 서브커맨드 docstring 누락 방지 회귀 테스트 추가 (#494)
  ([#511](https://github.com/joshua-jingu-lee/ante/pull/511),
  [`9f9fbe6`](https://github.com/joshua-jingu-lee/ante/commit/9f9fbe65d2b7da19ff0d0b26ef6b07666b1e06eb))

### Documentation

- HTTPException 응답을 OpenAPI 스펙에 문서화 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

### Features

- 각 모듈에 NotificationEvent 발행 추가 (16건) ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **approval**: Suppress_notification 파라미터 추가 (#516)
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **approval**: 결재 executor 8건 등록 ([#463](https://github.com/joshua-jingu-lee/ante/pull/463),
  [`72bbe14`](https://github.com/joshua-jingu-lee/ante/commit/72bbe1477f04d168c51d173702938191a5c26c3e))

- **approval**: 결재 만료 스케줄러 구현 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 사전 검증(validator) 구현 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 실행 실패 상태(EXECUTION_FAILED) 구현
  ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 재상신(reopen) 구현 ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **approval**: 결재 전결(자동 승인) 구현 ([#464](https://github.com/joshua-jingu-lee/ante/pull/464),
  [`3b8aeaf`](https://github.com/joshua-jingu-lee/ante/commit/3b8aeafcb8825e3fe8e99a02681dbc135f9a0061))

- **audit**: 감사 로그 기록 연동 — Web API + CLI ([#478](https://github.com/joshua-jingu-lee/ante/pull/478),
  [`c6e4acc`](https://github.com/joshua-jingu-lee/ante/commit/c6e4acca00a7102dba4affb8e1961821b5bae50c))

- **audit**: 감사 로그 보존 기간 정책(retention) 구현
  ([#478](https://github.com/joshua-jingu-lee/ante/pull/478),
  [`c6e4acc`](https://github.com/joshua-jingu-lee/ante/commit/c6e4acca00a7102dba4affb8e1961821b5bae50c))

- **audit**: 감사 로그 조회 필터 확장 — 날짜 필터 + limit 클램핑
  ([#478](https://github.com/joshua-jingu-lee/ante/pull/478),
  [`c6e4acc`](https://github.com/joshua-jingu-lee/ante/commit/c6e4acca00a7102dba4affb8e1961821b5bae50c))

- **backtest**: 백테스트→리포트 DRAFT 자동 생성 플로우 구현 (#493)
  ([#512](https://github.com/joshua-jingu-lee/ante/pull/512),
  [`6cc068b`](https://github.com/joshua-jingu-lee/ante/commit/6cc068bd06e45d48e749aef0101bf41d32701d9e))

- **bot**: BotManager 전략 배정/변경/재개 메서드 구현 ([#463](https://github.com/joshua-jingu-lee/ante/pull/463),
  [`72bbe14`](https://github.com/joshua-jingu-lee/ante/commit/72bbe1477f04d168c51d173702938191a5c26c3e))

- **bot**: Stop_bot()에 suppress_notification 파라미터 추가 (#518)
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **broker**: Broker.type 설정 기반 KIS ↔ Test 브로커 전환
  ([#454](https://github.com/joshua-jingu-lee/ante/pull/454),
  [`492cc2e`](https://github.com/joshua-jingu-lee/ante/commit/492cc2eb3febfdfaf57806fb8424adc305399045))

- **broker**: PriceSimulator — GBM 기반 가격 시뮬레이션 엔진
  ([#454](https://github.com/joshua-jingu-lee/ante/pull/454),
  [`492cc2e`](https://github.com/joshua-jingu-lee/ante/commit/492cc2eb3febfdfaf57806fb8424adc305399045))

- **broker**: ReconcileScheduler — 주기적 자동 대사 스케줄러 구현
  ([#481](https://github.com/joshua-jingu-lee/ante/pull/481),
  [`4475caa`](https://github.com/joshua-jingu-lee/ante/commit/4475caa22d29bbeb711a5fad3c9f4fbf036543c8))

- **broker**: TestBrokerAdapter — 개발/검증용 테스트 브로커 구현
  ([#454](https://github.com/joshua-jingu-lee/ante/pull/454),
  [`492cc2e`](https://github.com/joshua-jingu-lee/ante/commit/492cc2eb3febfdfaf57806fb8424adc305399045))

- **broker**: 브로커 메타정보(이름, 거래소) 동적 표출 ([#381](https://github.com/joshua-jingu-lee/ante/pull/381),
  [`342cac0`](https://github.com/joshua-jingu-lee/ante/commit/342cac082e9554f49d9dc73eff5752ac5a6d1f30))

- **cli**: `ante strategy submit` 커맨드 구현 (#500)
  ([#510](https://github.com/joshua-jingu-lee/ante/pull/510),
  [`9335331`](https://github.com/joshua-jingu-lee/ante/commit/9335331cc1a278e4763262cb70b198cb7317468b))

- **cli**: Ante strategy list/info/performance 커맨드 구현
  ([#505](https://github.com/joshua-jingu-lee/ante/pull/505),
  [`aba8e18`](https://github.com/joshua-jingu-lee/ante/commit/aba8e189a11e7e883a0bf1187471a3739b7e82f7))

- **cli**: Ante system start/stop — CLI 시스템 시작·종료 커맨드 구현
  ([#482](https://github.com/joshua-jingu-lee/ante/pull/482),
  [`a18af9a`](https://github.com/joshua-jingu-lee/ante/commit/a18af9a4b51376d5a83d05a17657d06fa2172a3a))

- **cli**: Click introspection 기반 CLI 레퍼런스 문서 자동 생성
  ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

- **config**: SystemState.set_state()에 suppress_notification 옵션 추가
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **dashboard**: Feed 상태 및 API 키 현황 UI 추가
  ([#367](https://github.com/joshua-jingu-lee/ante/pull/367),
  [`2306318`](https://github.com/joshua-jingu-lee/ante/commit/2306318260a4783f34e9e13fe5ee49559552a58c))

- **data**: 백테스트 데이터 API에 fundamental 데이터 유형 지원 추가
  ([`aa6ce56`](https://github.com/joshua-jingu-lee/ante/commit/aa6ce560f85de97bcd8f42a6cadda0816eb6758d))

- **eventbus**: SystemStartedEvent 도메인 이벤트 추가
  ([#552](https://github.com/joshua-jingu-lee/ante/pull/552),
  [`732175d`](https://github.com/joshua-jingu-lee/ante/commit/732175d224ac42602e8de65ff9023b0cd75936e9))

- **frontend**: Openapi-typescript 기반 프론트엔드 타입 자동 생성 파이프라인
  ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

- **gateway**: KISStreamClient ↔ APIGateway 실시간 시세 연동
  ([#479](https://github.com/joshua-jingu-lee/ante/pull/479),
  [`90ace1f`](https://github.com/joshua-jingu-lee/ante/commit/90ace1fdae2c29194e9a065ff3543a1a62305be4))

- **gateway**: LiveDataProvider.get_ohlcv() ParquetStore 연동
  ([#480](https://github.com/joshua-jingu-lee/ante/pull/480),
  [`ec1688e`](https://github.com/joshua-jingu-lee/ante/commit/ec1688eaa3f95de193223adb1c4940d00870e106))

- **notification**: Quiet_hours 동적 설정 연동 (#532)
  ([#553](https://github.com/joshua-jingu-lee/ante/pull/553),
  [`0844354`](https://github.com/joshua-jingu-lee/ante/commit/0844354b47edd612cb93913c11c29a877d8ead7d))

- **notification**: Telegram 결재 연동 — 인라인 버튼 + 명령어
  ([#473](https://github.com/joshua-jingu-lee/ante/pull/473),
  [`64d10b7`](https://github.com/joshua-jingu-lee/ante/commit/64d10b7019ac85a2c6f82176c8d4243e83624de4))

- **seed**: Python 시드 데이터 생성기 구현
  ([`4ceb010`](https://github.com/joshua-jingu-lee/ante/commit/4ceb0103094cbce83b02237d655650c90e27dba5))

- **telegram**: /activate 응답 메시지 스펙 적용 ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **telegram**: /balance 응답을 스펙 상세 형식으로 확장
  ([#514](https://github.com/joshua-jingu-lee/ante/pull/514),
  [`aba6679`](https://github.com/joshua-jingu-lee/ante/commit/aba6679c64aec849aaac59227935b823f9cc0706))

- **telegram**: /stop 응답 메시지를 스펙(bot.md) 기준으로 확장
  ([#556](https://github.com/joshua-jingu-lee/ante/pull/556),
  [`2d93a65`](https://github.com/joshua-jingu-lee/ante/commit/2d93a65cafc30c62eb99a10a4e4c1dd89e4eb98d))

- **telegram**: 명령 호출부에 suppress_notification=True 전달 (#519)
  ([#555](https://github.com/joshua-jingu-lee/ante/pull/555),
  [`eafcb29`](https://github.com/joshua-jingu-lee/ante/commit/eafcb29c90ba01be96aac7a956ab8ae34105c9af))

- **trade**: 장 마감 후 일일 성과 요약 알림 스케줄러 구현 (#503)
  ([#513](https://github.com/joshua-jingu-lee/ante/pull/513),
  [`8519a27`](https://github.com/joshua-jingu-lee/ante/commit/8519a275c60610d9250d6d607adc052b0e5145a2))

- **treasury,rule**: Treasury.update_budget() 및 RuleEngine.update_rules() 구현
  ([#463](https://github.com/joshua-jingu-lee/ante/pull/463),
  [`72bbe14`](https://github.com/joshua-jingu-lee/ante/commit/72bbe1477f04d168c51d173702938191a5c26c3e))

- **web**: 전 엔드포인트 response_model 추가 ([#396](https://github.com/joshua-jingu-lee/ante/pull/396),
  [`791be60`](https://github.com/joshua-jingu-lee/ante/commit/791be60a240eb0145410292ff92030177140c6fa))

- **web**: 전 엔드포인트 response_model 추가 및 OpenAPI 스키마 정비
  ([#395](https://github.com/joshua-jingu-lee/ante/pull/395),
  [`eac0340`](https://github.com/joshua-jingu-lee/ante/commit/eac034048f15b8f2066955db5c4a3a1a802eeb44))

### Refactoring

- FeedOrchestrator God Class 분해 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- Main.py Composition Root 분리 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- 문자열 리터럴 상수 추출 (S1192) ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- 불필요한 async 함수 정리 (#418) ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **approval**: Create()/approve() 메서드 분할 및 executor 중복 제거 (#523)
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **broker**: KIS 어댑터 _request() 관심사 분리 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **broker**: Realtime_price_stream/realtime_order_stream 스펙 아웃 제거
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **cli**: Config_get() 인지 복잡도 개선 (CC 13 → 3)
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **cli**: Rule enable/disable 커맨드 제거 ([#509](https://github.com/joshua-jingu-lee/ante/pull/509),
  [`a7a0365`](https://github.com/joshua-jingu-lee/ante/commit/a7a0365d1aba628580a2d0e9cfe2d63cef7668d2))

- **cli**: Strategy_info() 인지 복잡도 감소 (CC 14 → 7)
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **data**: RetentionPolicy.enforce() CC 감소를 위한 메서드 분리
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **data**: Store.write() CC 13→4로 분리 ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **events**: NotificationEvent 필드 재설계 — title/category/buttons 추가
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **feed**: BackfillRunner.run docstring 축소로 함수 50줄 제한 충족
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **feed**: FeedOrchestrator God Class 분해
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **feed**: Validate_business 복잡도 개선 — 검증 규칙별 함수 분리
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **feed**: 스케줄러 루프 및 출력 로직을 독립 모듈로 분리 ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **main**: _init_broker 중첩 깊이 3단계 이하로 축소
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **main**: _init_feed에서 ApprovalService 초기화를 _init_approval로 분리
  ([#544](https://github.com/joshua-jingu-lee/ante/pull/544),
  [`cc5014f`](https://github.com/joshua-jingu-lee/ante/commit/cc5014f54e48b60f3ed370e455e1edeb1cf277ce))

- **main**: Composition Root을 독립 초기화 함수로 분리
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **member**: MemberService 관심사 분리 (AuthService, TokenManager, RecoveryKeyManager)
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))

- **notification**: Notification_history 관련 코드 전량 제거
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **notification**: NotificationService 단일 핸들러 통합
  ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **notification**: 중앙 템플릿 파일 삭제 ([#502](https://github.com/joshua-jingu-lee/ante/pull/502),
  [`7cb6183`](https://github.com/joshua-jingu-lee/ante/commit/7cb6183b94137106c04057f5013708ea7611219e))

- **schemas**: Extra="allow" 주석 추가 및 response_model 정합성 테스트
  ([`8b22160`](https://github.com/joshua-jingu-lee/ante/commit/8b221600ad01b5b338300e1d4e50f2539e0415c2))

- **schemas**: Response model 내부 dict[str, Any]를 구체 Pydantic 모델로 전환
  ([#467](https://github.com/joshua-jingu-lee/ante/pull/467),
  [`adb5dfc`](https://github.com/joshua-jingu-lee/ante/commit/adb5dfcb96d45ea981748e39f7999d647f17bc3f))

- **strategy**: TA-Lib → pandas-ta 전환 및 LiveDataProvider 지표 계산 구현
  ([#457](https://github.com/joshua-jingu-lee/ante/pull/457),
  [`96f9778`](https://github.com/joshua-jingu-lee/ante/commit/96f97787ab764d1ca248ac9b7e91d0b3733b5e5c))

- **web**: 라우트 의존성 주입 전환 + Annotated 타입 힌트 적용
  ([#437](https://github.com/joshua-jingu-lee/ante/pull/437),
  [`3635e7f`](https://github.com/joshua-jingu-lee/ante/commit/3635e7ff230ad570399334c4475586d4d4c831ef))


## v0.4.1 (2026-03-17)

### Bug Fixes

- 미사용 BacktestMetrics 컴포넌트 삭제 및 unused import 제거
  ([`672f7d6`](https://github.com/joshua-jingu-lee/ante/commit/672f7d62749a1faa72b8acca263743d3e0f3576d))


## v0.4.0 (2026-03-17)

### Features

- **봇 관리**: 봇 상세 예산 카드·보유종목 테이블 데이터 연동
  ([`736d492`](https://github.com/joshua-jingu-lee/ante/commit/736d492))
- **봇 관리**: 봇 카드 UI 개선 — 로봇 아이콘 애니메이션, 실행간격 표시
  ([`dc0b438`](https://github.com/joshua-jingu-lee/ante/commit/dc0b438))
- **봇 관리**: 봇 상세 UI 보강 — 뒤로가기, stopped 상태 헤더, 설정 수정 모달
  ([`cfbbd22`](https://github.com/joshua-jingu-lee/ante/commit/cfbbd22))
- **봇 관리**: 봇 생성 모달 개선 — 전략 셀렉트, 힌트 텍스트, 입력 검증
  ([`d886602`](https://github.com/joshua-jingu-lee/ante/commit/d886602))
- **봇 관리**: 봇 중지/삭제 모달 구현 — 보유종목별 분기, 포지션 처리 옵션
  ([`096d8d3`](https://github.com/joshua-jingu-lee/ante/commit/096d8d3))
- **결재함**: 결재 유형 enum을 백엔드/스펙 기준으로 수정
  ([`e0aaa91`](https://github.com/joshua-jingu-lee/ante/commit/e0aaa91))
- **결재함**: 결재함 목록 필터를 목업 기준으로 개선
  ([`722694f`](https://github.com/joshua-jingu-lee/ante/commit/722694f))
- **결재함**: 결재 상세 공통 레이아웃 및 유형별 실행 내용 구현
  ([`71d3069`](https://github.com/joshua-jingu-lee/ante/commit/71d3069))
- **결재함**: 결재 상세 본문 마크다운 렌더링 구현
  ([`c12f164`](https://github.com/joshua-jingu-lee/ante/commit/c12f164))
- **결재함**: 결재 승인/거부 확인 모달 구현
  ([`cb6c646`](https://github.com/joshua-jingu-lee/ante/commit/cb6c646))
- **리포트**: 리포트 상세 페이지 및 API 엔드포인트 구현
  ([`38c8a4f`](https://github.com/joshua-jingu-lee/ante/commit/38c8a4f))
- **자금관리**: Bot 예산 비중 파이 차트 구현
  ([`2a9a390`](https://github.com/joshua-jingu-lee/ante/commit/2a9a390))
- **자금관리**: Bot당 예산 테이블 보강 — 보유종목 데이터 연동, 컬럼 재구성
  ([`6fc5fbb`](https://github.com/joshua-jingu-lee/ante/commit/6fc5fbb))
- **멤버 관리**: Human 멤버 카드 보강 — 역할 뱃지, 왕관 표시, 액션 버튼
  ([`c6b01d4`](https://github.com/joshua-jingu-lee/ante/commit/c6b01d4))
- **멤버 관리**: 멤버 관리 상태 필터 탭 구현 및 소속 필터 위치 수정
  ([`4d25ee6`](https://github.com/joshua-jingu-lee/ante/commit/4d25ee6))
- **설정**: HALTED 정지 시각·사유 표시 및 금액 단위 토글 구현
  ([`b05a25b`](https://github.com/joshua-jingu-lee/ante/commit/b05a25b))
- **KIS**: KIS 계좌 헤더 보강 — 계좌번호, 모의투자 뱃지, 동기화 상태
  ([`e94a451`](https://github.com/joshua-jingu-lee/ante/commit/e94a451))

### Bug Fixes

- **백테스트**: 백테스트 데이터 페이지네이션·용량 정보 레이아웃 수정
  ([`b80d0a2`](https://github.com/joshua-jingu-lee/ante/commit/b80d0a2))
- **백테스트**: 백테스트 데이터 카드 레이아웃·배너·필터 목업 불일치 수정
  ([`f771c5b`](https://github.com/joshua-jingu-lee/ante/commit/f771c5b))
- **백테스트**: 백테스트 데이터 삭제 모달 목업 불일치 수정
  ([`34f8b68`](https://github.com/joshua-jingu-lee/ante/commit/34f8b68))
- **멤버 관리**: 멤버 관리 revoked 스타일 및 상세 브레드크럼 추가
  ([`3347717`](https://github.com/joshua-jingu-lee/ante/commit/3347717))
- **멤버 관리**: 멤버 관리 라우트·타이틀·라벨 목업 불일치 수정
  ([`026be4c`](https://github.com/joshua-jingu-lee/ante/commit/026be4c))
- **자금관리**: 자금 변동 이력 페이지네이션 스타일 및 타이틀 수정
  ([`b0a4a3c`](https://github.com/joshua-jingu-lee/ante/commit/b0a4a3c))
- **설정**: 설정 거래 모드 뱃지 및 거래 설정 버튼 방식 수정
  ([`dfa24ba`](https://github.com/joshua-jingu-lee/ante/commit/dfa24ba))

### Tests

- E2E 시나리오 추가 및 색상 수정 (자금관리, 멤버관리, 백테스트, 설정)
  ([`df165e6`](https://github.com/joshua-jingu-lee/ante/commit/df165e6))
- 봇 관리 E2E 시나리오를 목업 기준으로 보강
  ([`69bedec`](https://github.com/joshua-jingu-lee/ante/commit/69bedec))
- 결재함/리포트 상세 E2E 시나리오 초안 작성
  ([`e43662b`](https://github.com/joshua-jingu-lee/ante/commit/e43662b))


## v0.3.2 (2026-03-17)

### Bug Fixes

- **frontend**: 봇 목록/상세/생성 폼에 name 필드 추가
  ([`001260c`](https://github.com/joshua-jingu-lee/ante/commit/001260c))
- **frontend**: 봇 관리 페이지를 카드 레이아웃으로 변경하고 섹션 구분 추가
  ([`ea4ddcb`](https://github.com/joshua-jingu-lee/ante/commit/ea4ddcb))
- **frontend**: 전략 목록에 제출자 컬럼 및 페이지네이션 추가
  ([`1daffa6`](https://github.com/joshua-jingu-lee/ante/commit/1daffa6))
- **frontend**: 전략 상세 페이지 목업 대비 UI 괴리 개선
  ([`5e0adea`](https://github.com/joshua-jingu-lee/ante/commit/5e0adea))
- **frontend**: 봇 상세 페이지 목업 대비 UI 괴리 개선
  ([`f33b7c2`](https://github.com/joshua-jingu-lee/ante/commit/f33b7c2))
- **frontend**: 결재함 목업 대비 UI 괴리 개선
  ([`74f5194`](https://github.com/joshua-jingu-lee/ante/commit/74f5194))
- **frontend**: 멤버 관리 UI를 목업 기준으로 개선
  ([`570f477`](https://github.com/joshua-jingu-lee/ante/commit/570f477))
- **treasury**: 자금관리 UI를 목업 기준으로 전면 개선
  ([`5a255cc`](https://github.com/joshua-jingu-lee/ante/commit/5a255cc))
- **frontend**: 설정 페이지를 목업 기준으로 개선
  ([`e033ff7`](https://github.com/joshua-jingu-lee/ante/commit/e033ff7))
- **frontend**: 백테스트 데이터 저장소 용량 상세 + 타임프레임 한글 라벨
  ([`34c8738`](https://github.com/joshua-jingu-lee/ante/commit/34c8738))


## v0.3.1 (2026-03-16)

### Bug Fixes

- **frontend**: 전략 상세 페이지 성과 데이터 없을 때 빈 상태 메시지 추가
  ([`ea60387`](https://github.com/joshua-jingu-lee/ante/commit/ea60387b53d17b665790a828fc2ad3ce6d47e511))


## v0.2.0 (2026-03-16)

### Chores

- GitHub Issue 템플릿 추가 (feature, bug, refactor)
  ([`348905c`](https://github.com/joshua-jingu-lee/ante/commit/348905c31ef1006db19ef218330c2517c2bde04f))

### Continuous Integration

- Release 워크플로우에 Docker 이미지 빌드 + ghcr.io push 추가
  ([`08a4b7c`](https://github.com/joshua-jingu-lee/ante/commit/08a4b7c0147176da038bc12a20895c6b389eb1f9))

### Features

- Docker 지원 추가 (multi-stage 빌드 + docker-compose)
  ([`75f950a`](https://github.com/joshua-jingu-lee/ante/commit/75f950a09dbaa41fe0b6849f70ac291097ef3ec5))


## v0.1.0 (2026-03-16)

- Initial Release
