# CHANGELOG

<!-- version list -->

## v0.8.1 (2026-03-29)

### Bug Fixes

- POST /api/reports 500 에러 수정 (#1065) ([#1069](https://github.com/joshua-jingu-lee/ante/pull/1069),
  [`d60e826`](https://github.com/joshua-jingu-lee/ante/commit/d60e82663d6a3fcb5f7ffffed79caedbb5f37c47))

- Rule info 미존재 시 종료 코드 1 반환에 맞춰 유닛 테스트 수정
  ([#1056](https://github.com/joshua-jingu-lee/ante/pull/1056),
  [`f5decef`](https://github.com/joshua-jingu-lee/ante/commit/f5decef32aae42168e4332b847557815ff0b65ed))

- **api**: GET /api/members 에러 핸들링 및 로깅 추가 (#1084)
  ([#1087](https://github.com/joshua-jingu-lee/ante/pull/1087),
  [`b6c979d`](https://github.com/joshua-jingu-lee/ante/commit/b6c979d6b709446fbe78b8e9bfee3c34ce873409))

- **approval**: Strategy_adopt 결재 생성 시 params 검증 추가
  ([#1083](https://github.com/joshua-jingu-lee/ante/pull/1083),
  [`1a259ab`](https://github.com/joshua-jingu-lee/ante/commit/1a259ab90e00936ddc5ef0928cb2d5f2d05a2a68))

- **cli**: Approval 서브커맨드에 @format_option 데코레이터 추가
  ([#1080](https://github.com/joshua-jingu-lee/ante/pull/1080),
  [`d5364f7`](https://github.com/joshua-jingu-lee/ante/commit/d5364f73f29f6c07a7bc16ec9e56df6ef19d14d9))

- **cli**: Backtest run 시작일 > 종료일 입력 검증 추가 (#1066)
  ([#1068](https://github.com/joshua-jingu-lee/ante/pull/1068),
  [`ef5f17b`](https://github.com/joshua-jingu-lee/ante/commit/ef5f17ba72d4d69f21d8ddc8211b4a99ec433bee))

- **tc**: Approval/workflow.feature pending 결재 자체 시딩으로 SKIP 해소
  ([#1077](https://github.com/joshua-jingu-lee/ante/pull/1077),
  [`652ee9a`](https://github.com/joshua-jingu-lee/ante/commit/652ee9a761885e3e8fc5829dbc2b1100d48d6516))

- **tc**: Background 계좌 DELETE 제거 및 전략 필터 Step 변경
  ([#1081](https://github.com/joshua-jingu-lee/ante/pull/1081),
  [`7c8a282`](https://github.com/joshua-jingu-lee/ante/commit/7c8a2820ec8d98eea1e9f399c9f4fda5f68eb33b))

- **tc**: Background에 잔존 데이터 정리 Step 추가하여 반복 실행 안정성 확보
  ([#1075](https://github.com/joshua-jingu-lee/ante/pull/1075),
  [`49bc94c`](https://github.com/joshua-jingu-lee/ante/commit/49bc94c36f26fed091effbfc5e92d5ad702816cd))

- **tc**: Bot/crud.feature 미구현 엔드포인트 참조 수정
  ([#1088](https://github.com/joshua-jingu-lee/ante/pull/1088),
  [`554f038`](https://github.com/joshua-jingu-lee/ante/commit/554f0387d9e7b9946a6313ddd5009c3264d57ed1))

- **tc**: CLI --format json 옵션 위치 수정 및 기대값 불일치 해소 (#1064)
  ([#1067](https://github.com/joshua-jingu-lee/ante/pull/1067),
  [`5c83775`](https://github.com/joshua-jingu-lee/ante/commit/5c837753a253737a58d680f106f1d2ac15eb0208))

- **tc**: QA 기대값 불일치 4건 수정 (#1070) ([#1071](https://github.com/joshua-jingu-lee/ante/pull/1071),
  [`f622546`](https://github.com/joshua-jingu-lee/ante/commit/f622546388e6e50fed309f3c293589f156234cf2))

- **tc**: Rule/query.feature QA 환경 기본 룰 미시딩으로 3건 FAIL (#1086)
  ([#1089](https://github.com/joshua-jingu-lee/ante/pull/1089),
  [`ada94fd`](https://github.com/joshua-jingu-lee/ante/commit/ada94fd4e187c55bccd8c4f1d6793de6095a9075))

- **tc**: TC 스펙/구현체 불일치 4건 수정 + 개선 2건 ([#1053](https://github.com/joshua-jingu-lee/ante/pull/1053),
  [`2dab1da`](https://github.com/joshua-jingu-lee/ante/commit/2dab1da00a6471d569208520872ff091c33ab856))

- **tc**: 전략 조회 TC에 전략 이름을 명시적으로 지정 ([#1076](https://github.com/joshua-jingu-lee/ante/pull/1076),
  [`72397bb`](https://github.com/joshua-jingu-lee/ante/commit/72397bbb4386aebb6c1ed4d214a0b8a4b04c7b5f))

### Testing

- 리스크 룰 조회 TC 추가 (#1043) ([#1056](https://github.com/joshua-jingu-lee/ante/pull/1056),
  [`f5decef`](https://github.com/joshua-jingu-lee/ante/commit/f5decef32aae42168e4332b847557815ff0b65ed))

- 리스크 룰 조회 TC 추가 (rule/query.feature) #1043
  ([#1056](https://github.com/joshua-jingu-lee/ante/pull/1056),
  [`f5decef`](https://github.com/joshua-jingu-lee/ante/commit/f5decef32aae42168e4332b847557815ff0b65ed))

- **approval**: 결재 워크플로우 승인/거부 TC 추가 (#1042)
  ([#1055](https://github.com/joshua-jingu-lee/ante/pull/1055),
  [`91921b4`](https://github.com/joshua-jingu-lee/ante/commit/91921b46c0eac5089fa82d4c17f95e4e0be4b72d))

- **audit**: 감사 로그 조회 및 필터링 TC 추가 (#1046)
  ([#1057](https://github.com/joshua-jingu-lee/ante/pull/1057),
  [`fc9ca46`](https://github.com/joshua-jingu-lee/ante/commit/fc9ca462e5f29c2c549bab0a0d44dafe298df795))

- **backtest**: 백테스트 실행 및 성과 검증 TC 추가 (#1044)
  ([#1058](https://github.com/joshua-jingu-lee/ante/pull/1058),
  [`8074e2d`](https://github.com/joshua-jingu-lee/ante/commit/8074e2d7d3aa82c4622c67a38a6baf65b3ac7dd8))

- **data**: 데이터 피드 및 저장 관리 TC 추가 (feed.feature)
  ([#1061](https://github.com/joshua-jingu-lee/ante/pull/1061),
  [`0a9f183`](https://github.com/joshua-jingu-lee/ante/commit/0a9f183650d3394d23392d71752b138420d69fb5))

- **report**: 리포트 제출 및 조회 TC 추가 (#1045)
  ([#1059](https://github.com/joshua-jingu-lee/ante/pull/1059),
  [`d34adc1`](https://github.com/joshua-jingu-lee/ante/commit/d34adc199aeae7e21e43877f7cbe8bd70d371c07))

- **report**: 성과 집계 조회 TC 추가 (#1048) ([#1060](https://github.com/joshua-jingu-lee/ante/pull/1060),
  [`703d1fd`](https://github.com/joshua-jingu-lee/ante/commit/703d1fd56f405324135bb03b6ded38937b51865d))

- **scenario**: E2E 전체 사이클 TC 추가 (#1050)
  ([#1063](https://github.com/joshua-jingu-lee/ante/pull/1063),
  [`c0f2e4b`](https://github.com/joshua-jingu-lee/ante/commit/c0f2e4b0adcbeb5f13645d21ae37e05f2365868a))

- **trade**: 거래 실행 및 포지션 반영 TC 추가 (#1041)
  ([#1054](https://github.com/joshua-jingu-lee/ante/pull/1054),
  [`b362897`](https://github.com/joshua-jingu-lee/ante/commit/b362897bec06fb5276730fb858f9714d963ce977))

- **trade,config**: Trade/query, config/dynamic TC 시나리오 확장
  ([#1062](https://github.com/joshua-jingu-lee/ante/pull/1062),
  [`5c82e6a`](https://github.com/joshua-jingu-lee/ante/commit/5c82e6a5192dd61d154735208018f967a6527445))


## v0.8.0 (2026-03-25)

### Bug Fixes

- Commission_rate 테스트를 Config 시드 등록(#965) 현행에 맞게 갱신
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- DataProvider.get_ohlcv() 반환 타입을 pl.DataFrame으로 통일 Refs #970
  ([#980](https://github.com/joshua-jingu-lee/ante/pull/980),
  [`6a59db5`](https://github.com/joshua-jingu-lee/ante/commit/6a59db5ea4add15d899ee4dde7f0efc61339fb63))

- Dataset 목록 API 테스트를 row_count=0 반환 현행에 맞게 갱신
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- Strategy_adopt/retire 결재 실행기 ReportStatus enum 전달 Refs #974
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- Strategy_adopt/retire 결재 실행기에 ReportStatus enum 전달
  ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

- 봇 생성 API 필드 불일치 해소 — strategy_name/account_id/budget 지원
  ([#979](https://github.com/joshua-jingu-lee/ante/pull/979),
  [`dc1e8d6`](https://github.com/joshua-jingu-lee/ante/commit/dc1e8d6de86aa0b5a98077cad1b21edad879c989))

- **account**: Is_paper를 Account.broker_config으로 이관 Refs #989
  ([#992](https://github.com/joshua-jingu-lee/ante/pull/992),
  [`ab318e2`](https://github.com/joshua-jingu-lee/ante/commit/ab318e2dcd7773bb40f4bce3185b447c3005d594))

- **api**: Approvals/members 목록 total을 전체 건수로 수정
  ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

- **api**: Datasets 목록 data_type 기본값을 None으로 변경하여 전체 타입 반환
  ([#964](https://github.com/joshua-jingu-lee/ante/pull/964),
  [`d340df7`](https://github.com/joshua-jingu-lee/ante/commit/d340df7f3de787310145f3fdc5d5c5ed6cf60766))

- **api**: 리포트 상세 응답에 config/datasets 필드 추가
  ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **api**: 리포트 상세 응답에 config/datasets 필드 추가 Refs #971
  ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **approval**: CLI에서 ApprovalService.list → list_approvals 호출 누락 수정
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **approval**: ExecutionContent 컴포넌트 삭제 Refs #1010
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **approval**: 결재 승인 시 StrategyRegistry 상태도 함께 전환 Refs #1001
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **backtest**: Get_indicator() stub을 실제 지표 계산으로 교체 Refs #969
  ([#977](https://github.com/joshua-jingu-lee/ante/pull/977),
  [`6368596`](https://github.com/joshua-jingu-lee/ante/commit/6368596e61eeb7f6c261ed554b21f68060c294be))

- **bot**: 봇 생성 모달 전략 셀렉트를 ADOPTED 상태만 필터링 (#1006)
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **broker**: KIS WebSocket approval_key REST URL 유추 로직 반전 수정 Refs #988
  ([`37dcac7`](https://github.com/joshua-jingu-lee/ante/commit/37dcac7bbd21a12013c1e5e7439400cb136ce25b))

- **broker**: KIS WebSocket 모의/실전 포트 번호 반전 수정
  ([#943](https://github.com/joshua-jingu-lee/ante/pull/943),
  [`e8ddc24`](https://github.com/joshua-jingu-lee/ante/commit/e8ddc2405a582f512a80524d55878f80dfc1039d))

- **ci**: Mypy union-attr 오류 및 v004 마이그레이션 테스트 실패 수정
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **ci**: Publish.yml에서 static 디렉토리 생성 추가
  ([`ca5f406`](https://github.com/joshua-jingu-lee/ante/commit/ca5f40653e7f2d7cfd1064ef2a60f79a92e72218))

- **ci**: Test job timeout을 10분에서 15분으로 증가
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **cli**: Broker reconcile 오프라인 폴백에서 불필요한 의존성 제거
  ([#947](https://github.com/joshua-jingu-lee/ante/pull/947),
  [`281e65c`](https://github.com/joshua-jingu-lee/ante/commit/281e65c378518a5ea89a0d1d4ab6a12ba656cf93))

- **cli**: Strategy info에서 rationale/risks 키 누락으로 인한 KeyError 수정
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **cli**: 잔여 mypy 오류 15건 해소 및 overrides 전체 삭제 (#1031)
  ([#1032](https://github.com/joshua-jingu-lee/ante/pull/1032),
  [`41ae2c1`](https://github.com/joshua-jingu-lee/ante/commit/41ae2c1c5fef61b17c3512c140b5651ff634c4a2))

- **data**: DART 체크포인트 키 형식 수정 및 순서 비교 오류 해결
  ([#945](https://github.com/joshua-jingu-lee/ante/pull/945),
  [`1de7442`](https://github.com/joshua-jingu-lee/ante/commit/1de74422622601f7dc43cc9ad174ee4705dc4af5))

- **db**: V003 마이그레이션에서 accounts 테이블 존재 여부 확인
  ([`3f7ecb7`](https://github.com/joshua-jingu-lee/ante/commit/3f7ecb78d0c668926ee20ab352e6da484d33a7a5))

- **frontend**: 데이터셋 목록에서 file_size/row_count 의존 제거
  ([#952](https://github.com/joshua-jingu-lee/ante/pull/952),
  [`dd80412`](https://github.com/joshua-jingu-lee/ante/commit/dd80412db1ec48935609c14010f359a52a741a9b))

- **member**: Agent 기본 scope에서 비표준 approval:create/review를 표준 scope로 수정
  ([#998](https://github.com/joshua-jingu-lee/ante/pull/998),
  [`9015837`](https://github.com/joshua-jingu-lee/ante/commit/90158370f1027794a63a84fe53872271c5d8a8ca))

- **notification**: Telegram_enabled 초기값 전달 및 chat_id 파싱 안전 처리
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **notification**: 텔레그램 명령 수신 설정을 dynamic_config로 통합 Refs #997
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **notification**: 텔레그램 명령 수신 설정을 dynamic_config로 통합 및 allowed_user_ids 제거
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- **scripts**: 앵커 링크 버그 수정 및 미사용 테이블 항목 제거 Refs #987
  ([#991](https://github.com/joshua-jingu-lee/ante/pull/991),
  [`f8bec96`](https://github.com/joshua-jingu-lee/ante/commit/f8bec9662447d4874427d748d53f3a4e16803112))

- **strategy**: 전략 상세 페이지 rationale·risks·params 미노출 수정
  ([#995](https://github.com/joshua-jingu-lee/ante/pull/995),
  [`788a1b8`](https://github.com/joshua-jingu-lee/ante/commit/788a1b862ca906251f79b2fd4bd228d45d3e3d07))

- **test**: CI 기존 테스트 실패 2건 수정 ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **test**: Commission defaults 테스트를 #965 시드 등록에 맞게 수정
  ([#976](https://github.com/joshua-jingu-lee/ante/pull/976),
  [`450368b`](https://github.com/joshua-jingu-lee/ante/commit/450368bca38c370410553965aaeff98088889706))

- **test**: Config 시드 등록·목록 API 최적화에 맞게 테스트 3건 수정
  ([`52fe3e5`](https://github.com/joshua-jingu-lee/ante/commit/52fe3e59d4e6847e34a6fbca5d5e35f7ab410460))

- **test**: StrategyRecord author → author_name/author_id 변경 반영
  ([#985](https://github.com/joshua-jingu-lee/ante/pull/985),
  [`296853d`](https://github.com/joshua-jingu-lee/ante/commit/296853d9af346cabb037c2d3e815f4495f0f81d8))

- **test**: Test_init_account에 Config 주입 누락 수정
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **treasury**: Is_virtual 판정을 Account.trading_mode 기반으로 변경
  ([#993](https://github.com/joshua-jingu-lee/ante/pull/993),
  [`7b158b1`](https://github.com/joshua-jingu-lee/ante/commit/7b158b1cafb0893b100c15faccef50b9bcd8126d))

- **treasury**: Replace private _get_writer() with public fetch_one() in release_budget
  ([#984](https://github.com/joshua-jingu-lee/ante/pull/984),
  [`a658468`](https://github.com/joshua-jingu-lee/ante/commit/a658468d97d372974b019558d30ad6235e26546b))

- **treasury**: 봇 삭제 시 인메모리에 없는 budget도 DB fallback으로 환수 Refs #982
  ([#984](https://github.com/joshua-jingu-lee/ante/pull/984),
  [`a658468`](https://github.com/joshua-jingu-lee/ante/commit/a658468d97d372974b019558d30ad6235e26546b))

- **treasury**: 봇 삭제 시 할당 예산 DB fallback 환수 Refs #982
  ([#984](https://github.com/joshua-jingu-lee/ante/pull/984),
  [`a658468`](https://github.com/joshua-jingu-lee/ante/commit/a658468d97d372974b019558d30ad6235e26546b))

- **typing**: Cli/main.py mypy has-type 오류 18건 inline ignore 처리
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **typing**: Mypy ignore 목록 단순 오류 14건 해소 Refs #1012
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **typing**: Mypy ignore 목록 중간 난이도 오류 27건 해소
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **typing**: Mypy ignore 목록 중복·타입 오류 27건 해소 Refs #1013
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))

- **web**: BotStrategy 타입 author → author_name/author_id 누락 수정 Refs #983
  ([`2a78af8`](https://github.com/joshua-jingu-lee/ante/commit/2a78af8a3d7213538be01ddbdd340deb7dd578a3))

- **web**: 브라우저 탭 타이틀·파비콘 변경 Refs #963 ([#967](https://github.com/joshua-jingu-lee/ante/pull/967),
  [`b1b327e`](https://github.com/joshua-jingu-lee/ante/commit/b1b327ee78c7880b7fd20131c3bb8043d91be0c7))

- **web**: 사이드바 UI 버그 3건 수정 Refs #957 ([#966](https://github.com/joshua-jingu-lee/ante/pull/966),
  [`272055b`](https://github.com/joshua-jingu-lee/ante/commit/272055bc98178b548875bc80c9d00e832005451c))

- **web**: 전략 상세 페이지 파라미터 미표시 및 빈 값 렌더링 수정 Refs #972
  ([#975](https://github.com/joshua-jingu-lee/ante/pull/975),
  [`dbb4894`](https://github.com/joshua-jingu-lee/ante/commit/dbb489407e91ebac07157441c22e6eefd699aa21))

### Chores

- Config/system.toml을 .gitignore에 추가하고 추적 제거
  ([`303f8d1`](https://github.com/joshua-jingu-lee/ante/commit/303f8d153172725544ed581b0e49588a792bf3e6))

- Trigger CI ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

### Continuous Integration

- CI 파이프라인 개선 — 병렬화, 품질 게이트, 중복 실행 방지
  ([`baf6d71`](https://github.com/joshua-jingu-lee/ante/commit/baf6d7195bbbf92e68e5905f7ffe1e265788bff8))

- Test job timeout을 20분으로 증가 ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- Test job timeout을 30분으로 증가 ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- Test timeout 45분, pytest 출력 최소화로 CI 속도 개선
  ([#1009](https://github.com/joshua-jingu-lee/ante/pull/1009),
  [`8f17014`](https://github.com/joshua-jingu-lee/ante/commit/8f17014f9880ff5b5a0a8986accde212f9f48fdb))

- Trigger CI re-run ([#978](https://github.com/joshua-jingu-lee/ante/pull/978),
  [`f02f666`](https://github.com/joshua-jingu-lee/ante/commit/f02f6667bb6169ee49bd6c77c3370cae81be0e91))

### Documentation

- README에 Mermaid 아키텍처 다이어그램 추가
  ([`9899f68`](https://github.com/joshua-jingu-lee/ante/commit/9899f684249a50dac760c1921025996a006e1d7b))

- **guide**: README·getting-started·security 가이드 톤 통일 및 내용 보강
  ([`93e3705`](https://github.com/joshua-jingu-lee/ante/commit/93e37053ad992918f4a9e74b2988c11482709b21))

- **readme**: Mermaid 다이어그램을 SVG 이미지로 교체
  ([`3da6d8e`](https://github.com/joshua-jingu-lee/ante/commit/3da6d8e714b69ba5aecac323a7016add068ab9bf))

- **readme**: README 개선 및 How it works SVG 다이어그램 추가
  ([`9260b3c`](https://github.com/joshua-jingu-lee/ante/commit/9260b3c1c52f242974da0e90cc87ad47438476b7))

- **readme**: 역할별 섹션 보강 및 문서 링크 가이드로 전환
  ([`5cc09dc`](https://github.com/joshua-jingu-lee/ante/commit/5cc09dcd4317d1dad37b6e43cbf9f9e73fb096d8))

### Features

- **cli**: CLI 레퍼런스 문서에 필요 scope·토큰 타입 자동 표시 Refs #981
  ([#986](https://github.com/joshua-jingu-lee/ante/pull/986),
  [`07dc04d`](https://github.com/joshua-jingu-lee/ante/commit/07dc04da94a92e74f2ac6c83c08554f13a0e0d91))

- **config**: 트레이딩/리스크/알림 기본값을 Config 서비스에 시드 등록 Refs #965
  ([#968](https://github.com/joshua-jingu-lee/ante/pull/968),
  [`731bd0e`](https://github.com/joshua-jingu-lee/ante/commit/731bd0e12f41644b68d8f50a8b57dc7f77214803))

- **scripts**: Db-schema.md 자동 생성 스크립트 구현 Refs #987
  ([#991](https://github.com/joshua-jingu-lee/ante/pull/991),
  [`f8bec96`](https://github.com/joshua-jingu-lee/ante/commit/f8bec9662447d4874427d748d53f3a4e16803112))

- **strategy**: 전략 상태 변경 API 및 목록 필터 검증 구현 Refs #1003
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **strategy**: 전략 채택/폐기 executor에 NotificationEvent 발행 추가 Refs #1004
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

### Performance Improvements

- **api**: Cursor 페이지네이션 순회 최적화 ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

- **api**: Datasets 목록 API 이벤트 루프 블로킹 해소 ([#956](https://github.com/joshua-jingu-lee/ante/pull/956),
  [`c71c0bd`](https://github.com/joshua-jingu-lee/ante/commit/c71c0bd9f137e8ba34947cb4ecb867f02b269c40))

- **api**: Strategies 목록 N+1 조회를 asyncio.gather 병렬화 Refs #951
  ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

### Refactoring

- **api**: 전략 상세 봇 탐색 중복 코드를 헬퍼 함수로 통합 ([#962](https://github.com/joshua-jingu-lee/ante/pull/962),
  [`be497cf`](https://github.com/joshua-jingu-lee/ante/commit/be497cfc883e8c477306905aaa334a09e4f94230))

- **strategy**: StrategyMeta author -> author_name/author_id 분리 Refs #983
  ([#985](https://github.com/joshua-jingu-lee/ante/pull/985),
  [`296853d`](https://github.com/joshua-jingu-lee/ante/commit/296853d9af346cabb037c2d3e815f4495f0f81d8))

- **strategy**: StrategyMeta author 필드를 author_name/author_id 2필드로 분리 Refs #983
  ([#985](https://github.com/joshua-jingu-lee/ante/pull/985),
  [`296853d`](https://github.com/joshua-jingu-lee/ante/commit/296853d9af346cabb037c2d3e815f4495f0f81d8))

- **strategy**: StrategyStatus 3단계 간소화 (REGISTERED/ADOPTED/ARCHIVED) Refs #1000
  ([#1040](https://github.com/joshua-jingu-lee/ante/pull/1040),
  [`e47f3b9`](https://github.com/joshua-jingu-lee/ante/commit/e47f3b9a1e0222f4f829b59b38379a50ac0e72a2))

- **types**: Main.py Optional 필드 33건 assert 가드로 해소
  ([#1020](https://github.com/joshua-jingu-lee/ante/pull/1020),
  [`f510e6b`](https://github.com/joshua-jingu-lee/ante/commit/f510e6b2889a17339e42aea1798063c73ceb84ec))


## v0.7.0 (2026-03-24)

### Bug Fixes

- Dockerfile.test 프론트 빌드 및 DynamicConfig default=None 처리 수정
  ([`28f134b`](https://github.com/joshua-jingu-lee/ante/commit/28f134b0ed4fd3bf0f7e703e3834df5c7d0f092c))

- QA 전수 검사에서 발견된 버그 4건 수정
  ([`b3cd466`](https://github.com/joshua-jingu-lee/ante/commit/b3cd466f9828ca5c7ef51ac8182913280ef11678))

- 에픽 통합 시 DDL 누락 컬럼 반영 및 테스트 호환성 수정 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- 인증정보 없는 계좌의 봇 시작 시 422 에러 반환 (#670) ([#676](https://github.com/joshua-jingu-lee/ante/pull/676),
  [`d121eb8`](https://github.com/joshua-jingu-lee/ante/commit/d121eb86a3dbef86f64462150815d45b6bf2db4b))

- **account**: Create()에서 account_id 형식 검증 추가
  ([#789](https://github.com/joshua-jingu-lee/ante/pull/789),
  [`2379f56`](https://github.com/joshua-jingu-lee/ante/commit/2379f567b10e8aeb3640eaa6ff25e718097ccd9d))

- **account**: Create()에서 required_credentials 검증 추가
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **account**: Create()에서 required_credentials 검증 추가 #775
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **account**: Credentials Fernet 암호화 적용 #721
  ([#740](https://github.com/joshua-jingu-lee/ante/pull/740),
  [`8a89127`](https://github.com/joshua-jingu-lee/ante/commit/8a891273311f7ee7de0ca7fe5896142090d8f049))

- **account**: Credentials Fernet 암호화 적용 — 평문 DB 저장 제거
  ([#740](https://github.com/joshua-jingu-lee/ante/pull/740),
  [`8a89127`](https://github.com/joshua-jingu-lee/ante/commit/8a891273311f7ee7de0ca7fe5896142090d8f049))

- **account**: Delete()에서 이벤트 발행 및 CLI IPC 전환
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **account**: Delete()에서 이벤트 발행 및 CLI IPC 전환 #717
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **account**: DELETED 계좌 suspend/delete 상태 전이 가드 추가 #718
  ([#725](https://github.com/joshua-jingu-lee/ante/pull/725),
  [`9309429`](https://github.com/joshua-jingu-lee/ante/commit/9309429cddb91dd42bd4713849d8b07ef72f212d))

- **account**: DELETED 계좌에 suspend/delete 상태 전이 가드 추가
  ([#725](https://github.com/joshua-jingu-lee/ante/pull/725),
  [`9309429`](https://github.com/joshua-jingu-lee/ante/commit/9309429cddb91dd42bd4713849d8b07ef72f212d))

- **account**: Kis-overseas 프리셋 제거 — 미구현 브로커 타입 생성 차단 #770
  ([#780](https://github.com/joshua-jingu-lee/ante/pull/780),
  [`f5c58c7`](https://github.com/joshua-jingu-lee/ante/commit/f5c58c7d0f4fdb693cc322f4702b38f2e67123cc))

- **account**: MissingCredentialsError를 422로 매핑 Refs #848
  ([#850](https://github.com/joshua-jingu-lee/ante/pull/850),
  [`93a26af`](https://github.com/joshua-jingu-lee/ante/commit/93a26afde7d58e8db9791cbaa3c27d547b5bcd8c))

- **account**: Soft-delete된 계좌 ID 충돌 시 409 반환
  ([#680](https://github.com/joshua-jingu-lee/ante/pull/680),
  [`e0efb2c`](https://github.com/joshua-jingu-lee/ante/commit/e0efb2c5262f952cfb1d19adc755c6ccc2d2cf28))

- **account**: Test 브로커 required_credentials 추가
  ([#656](https://github.com/joshua-jingu-lee/ante/pull/656),
  [`2d7da9a`](https://github.com/joshua-jingu-lee/ante/commit/2d7da9a2e0527f96a221f21e200343712e967d8d))

- **account**: Update()에서 미인식 필드 전달 시 ValueError 발생 (#748)
  ([#756](https://github.com/joshua-jingu-lee/ante/pull/756),
  [`193762c`](https://github.com/joshua-jingu-lee/ante/commit/193762c85d624f6812ab42c8414806bb40bc4962))

- **account**: 불변 필드(exchange, currency, trading_mode, broker_type) 수정 차단 (#690)
  ([#691](https://github.com/joshua-jingu-lee/ante/pull/691),
  [`0a32f1d`](https://github.com/joshua-jingu-lee/ante/commit/0a32f1d0cf4fb0fcefc90235647b4cf06c88420d))

- **account**: 삭제된 계좌 활성화 시 409 반환 (#660)
  ([#666](https://github.com/joshua-jingu-lee/ante/pull/666),
  [`94c8ab9`](https://github.com/joshua-jingu-lee/ante/commit/94c8ab99fc3f2d5791a8e4689753de50f3910ff0))

- **account**: 이미 정지된 계좌 재정지 시 409 반환 ([#655](https://github.com/joshua-jingu-lee/ante/pull/655),
  [`cf234dd`](https://github.com/joshua-jingu-lee/ante/commit/cf234dd168490902797228c28c8bce1d5b24b225))

- **api**: Body 없는 POST /accounts/{id}/suspend 422 해결
  ([#646](https://github.com/joshua-jingu-lee/ante/pull/646),
  [`ea4305c`](https://github.com/joshua-jingu-lee/ante/commit/ea4305c38a6f0d378425b94676e2162b91baca4d))

- **api**: 전략 상세 응답에 root-level status 필드 추가 (#672)
  ([#674](https://github.com/joshua-jingu-lee/ante/pull/674),
  [`1f752df`](https://github.com/joshua-jingu-lee/ante/commit/1f752df5260c58e02884d37769f780cde542888d))

- **bot**: Bot 생성 시 Account 상태(active) 검증 추가 #736
  ([#746](https://github.com/joshua-jingu-lee/ante/pull/746),
  [`352917c`](https://github.com/joshua-jingu-lee/ante/commit/352917c480c3fc43a80b7ed8c6f2384ef1bcb83e))

- **bot**: Bot.stop()에서 ERROR→STOPPED 상태 전이 허용
  ([#809](https://github.com/joshua-jingu-lee/ante/pull/809),
  [`e26ca99`](https://github.com/joshua-jingu-lee/ante/commit/e26ca99019b317721462349baa7a324659e3b660))

- **bot**: BotConfig.paper_initial_balance 필드 제거 #747
  ([#766](https://github.com/joshua-jingu-lee/ante/pull/766),
  [`b5c5d41`](https://github.com/joshua-jingu-lee/ante/commit/b5c5d4149fb44b818f8cdca9bed966e36737a05d))

- **bot**: Get_info()에 trading_mode, exchange, currency 필드 추가 #750
  ([#761](https://github.com/joshua-jingu-lee/ante/pull/761),
  [`3d42939`](https://github.com/joshua-jingu-lee/ante/commit/3d42939e8237d80d167b540e6d4376e92a3792e6))

- **bot**: PUT /api/bots/{id} budget 수정 시 TreasuryError를 422로 반환
  ([#853](https://github.com/joshua-jingu-lee/ante/pull/853),
  [`9aebeca`](https://github.com/joshua-jingu-lee/ante/commit/9aebecaa076547c5ac4734e2adf32715d2a5062d))

- **bot**: SignalChannel에 OrderCancelFailedEvent 구독 추가 #779
  ([#816](https://github.com/joshua-jingu-lee/ante/pull/816),
  [`bdabbc6`](https://github.com/joshua-jingu-lee/ante/commit/bdabbc69af18d9c39057d08c61c41bca42abbc8f))

- **bot**: 계좌 상태 검증을 strategy meta 조건에서 분리
  ([#746](https://github.com/joshua-jingu-lee/ante/pull/746),
  [`352917c`](https://github.com/joshua-jingu-lee/ante/commit/352917c480c3fc43a80b7ed8c6f2384ef1bcb83e))

- **bot**: 연속 타임아웃 초과 시 ERROR 상태 전이 및 BotErrorEvent 발행 #793
  ([#811](https://github.com/joshua-jingu-lee/ante/pull/811),
  [`c89b952`](https://github.com/joshua-jingu-lee/ante/commit/c89b9527f2fd03c12ae630e153bbc749e0d3b298))

- **bot**: 정지된 계좌에서 봇 생성 시 409 반환 ([#654](https://github.com/joshua-jingu-lee/ante/pull/654),
  [`77efd2c`](https://github.com/joshua-jingu-lee/ante/commit/77efd2cf8ac5e55d177207f6becd50ff16519e54))

- **broker**: AccountService.get_broker()에 is_paper 주입 — KIS 모의투자 모드 수정
  ([#897](https://github.com/joshua-jingu-lee/ante/pull/897),
  [`e5ad5b8`](https://github.com/joshua-jingu-lee/ante/commit/e5ad5b8f82ed3206af0e6cbb1db316c62f65fffe))

- **cli**: Broker CLI IPC 우선 전환으로 토큰 재발급 방지
  ([#898](https://github.com/joshua-jingu-lee/ante/pull/898),
  [`272cccb`](https://github.com/joshua-jingu-lee/ante/commit/272cccba4d3fa213466e5eba79dc78886ab749dd))

- **cli**: Config set JSON 출력에 status 필드 복원 #705
  ([#707](https://github.com/joshua-jingu-lee/ante/pull/707),
  [`4b0d7aa`](https://github.com/joshua-jingu-lee/ante/commit/4b0d7aaffc4e4de445e39fe13bcd3d442cd24109))

- **cli**: DART API 키 프롬프트 EOF 수신 시 Abort 대신 기본값 처리 (#673)
  ([#675](https://github.com/joshua-jingu-lee/ante/pull/675),
  [`3739108`](https://github.com/joshua-jingu-lee/ante/commit/3739108276744f5661fab1440130f5e55e37ee14))

- **cli**: Trade CLI hang 해결 — 서비스 생성자 인자 수정
  ([#649](https://github.com/joshua-jingu-lee/ante/pull/649),
  [`1ba6321`](https://github.com/joshua-jingu-lee/ante/commit/1ba6321fafd799bca10289f0fb9ef6e9bdd61fcc))

- **config**: 웹 대시보드 기본 포트를 8000에서 3982로 변경
  ([#600](https://github.com/joshua-jingu-lee/ante/pull/600),
  [`3f194ae`](https://github.com/joshua-jingu-lee/ante/commit/3f194aea4b69df11959a112d5ecfc2f011c40c86))

- **event**: BotRestartExhaustedEvent에 account_id 필드 추가
  ([#757](https://github.com/joshua-jingu-lee/ante/pull/757),
  [`bf8997d`](https://github.com/joshua-jingu-lee/ante/commit/bf8997da15d102f3e0f63c8bd0c43f4acaafe143))

- **event**: BotRestartExhaustedEvent에 account_id 필드 추가 #749
  ([#757](https://github.com/joshua-jingu-lee/ante/pull/757),
  [`bf8997d`](https://github.com/joshua-jingu-lee/ante/commit/bf8997da15d102f3e0f63c8bd0c43f4acaafe143))

- **frontend**: BotEditModal 전략 변경이 서버에 전송되지 않는 버그 수정
  ([#899](https://github.com/joshua-jingu-lee/ante/pull/899),
  [`94590c3`](https://github.com/joshua-jingu-lee/ante/commit/94590c385d8118576422148991eb79f1cb24ae09))

- **frontend**: Revoked 에이전트 목록 숨김 및 suspended 아바타 dimmed 적용
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 결재 승인 완료 시 positive 배너 추가
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 디자인 토큰 위반 일괄 수정 — 시맨틱 토큰으로 치환
  ([#873](https://github.com/joshua-jingu-lee/ante/pull/873),
  [`b4904a3`](https://github.com/joshua-jingu-lee/ante/commit/b4904a394bdbd581cc2918dcd83a2319f0cdc1d5))

- **frontend**: 리포트 rejected 라벨 '미채택'으로 변경 및 수행자 ID 병기
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 설정 페이지 필드 누락 및 리스크 규칙 레이아웃 구분
  ([#909](https://github.com/joshua-jingu-lee/ante/pull/909),
  [`f5d1314`](https://github.com/joshua-jingu-lee/ante/commit/f5d1314f5a418d8685cf3f5b625e3034c50d86c2))

- **frontend**: 에이전트 등록 폼 개선 및 상태 버튼 상세 전용 전환
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 에이전트 등록 폼 소속 자유입력 및 Agent ID 정규식 검증 추가
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 에이전트 상태 전환 버튼을 카드에서 제거하여 상세 페이지에서만 노출
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 유저스토리 라벨·문구 스펙 불일치 5건 수정 (#900)
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **frontend**: 전략 상태 뱃지 archived 라벨 '보관됨' → '보관' 수정
  ([#901](https://github.com/joshua-jingu-lee/ante/pull/901),
  [`ce49851`](https://github.com/joshua-jingu-lee/ante/commit/ce49851f561039b8bf68da7c7e44c19ea3ac1fce))

- **member**: Reactivate()에 MemberReactivatedEvent 발행 추가 #797
  ([#813](https://github.com/joshua-jingu-lee/ante/pull/813),
  [`f281fb0`](https://github.com/joshua-jingu-lee/ante/commit/f281fb02db1ccc0d21ad6d0af414175f9992fed1))

- **member**: RecoveryKeyManager 인증 실패 시 NotificationEvent 발행 추가 #807
  ([#814](https://github.com/joshua-jingu-lee/ante/pull/814),
  [`c08fe22`](https://github.com/joshua-jingu-lee/ante/commit/c08fe22089efe977807d725e9c80afdcaa5edaae))

- **member**: Register/update_scopes master 권한 검증 추가
  ([#763](https://github.com/joshua-jingu-lee/ante/pull/763),
  [`58ed8bd`](https://github.com/joshua-jingu-lee/ante/commit/58ed8bdd49233bf502c8d4540fd460823748b004))

- **member**: Register/update_scopes에 master 권한 검증 추가 #739
  ([#763](https://github.com/joshua-jingu-lee/ante/pull/763),
  [`58ed8bd`](https://github.com/joshua-jingu-lee/ante/commit/58ed8bdd49233bf502c8d4540fd460823748b004))

- **member**: 패스워드 변경/리셋 시 NotificationEvent 발행 추가
  ([#787](https://github.com/joshua-jingu-lee/ante/pull/787),
  [`4b3f1df`](https://github.com/joshua-jingu-lee/ante/commit/4b3f1df6bc1ff55bac2ce1b2cef746e96f95b876))

- **member**: 패스워드 변경/리셋 시 기존 토큰 무효화 추가 ([#784](https://github.com/joshua-jingu-lee/ante/pull/784),
  [`d97dce1`](https://github.com/joshua-jingu-lee/ante/commit/d97dce10dc4b83fc70d15946173c7a5c5362c0da))

- **qa**: Docker exec 시 CLI 토큰 파일 폴백으로 인증 실패 해결 Refs #854
  ([#858](https://github.com/joshua-jingu-lee/ante/pull/858),
  [`d3c1894`](https://github.com/joshua-jingu-lee/ante/commit/d3c18948b1b18874a7a648a224f9c991a9f66f8d))

- **qa**: QA TC 환경 결함 5건 수정 — 토큰·credentials·allocation·데이터셋·룰 params
  ([#868](https://github.com/joshua-jingu-lee/ante/pull/868),
  [`055f578`](https://github.com/joshua-jingu-lee/ante/commit/055f578b8af2564ea1b0111f6af0b0a6a227ed16))

- **qa**: QA 엔트리포인트에 risk.test_qa_key 동적 설정 시드 등록
  ([#638](https://github.com/joshua-jingu-lee/ante/pull/638),
  [`0f9daec`](https://github.com/joshua-jingu-lee/ante/commit/0f9daec0cde9e552ce23e94baebb3726cf2af10d))

- **qa**: QA 전략 레지스트리 시딩 구현 ([#657](https://github.com/joshua-jingu-lee/ante/pull/657),
  [`5ae41ac`](https://github.com/joshua-jingu-lee/ante/commit/5ae41ac3230bc0622af809e80468259127112d7f))

- **qa**: QA 컨테이너에 ANTE_MEMBER_TOKEN 설정 — CLI TC 인증 실패 해결
  ([#849](https://github.com/joshua-jingu-lee/ante/pull/849),
  [`4cfe4ff`](https://github.com/joshua-jingu-lee/ante/commit/4cfe4ff46874f4ffa05c851d7974fa6cf2868a6b))

- **qa**: QA 환경에 qa_sample.py 전략 파일 추가 ([#637](https://github.com/joshua-jingu-lee/ante/pull/637),
  [`4d123eb`](https://github.com/joshua-jingu-lee/ante/commit/4d123eb6e4b8f41fe5b52fd0eef016e888b600fa))

- **qa**: Treasury 503 — get_treasury fallback 및 QA 시드 계좌 추가
  ([#648](https://github.com/joshua-jingu-lee/ante/pull/648),
  [`14bf435`](https://github.com/joshua-jingu-lee/ante/commit/14bf435e9c7813735b7496e0697ed0b0f988a2c6))

- **qa**: 전략 시딩 스크립트 모듈 수준 변수 참조 지원
  ([`d222323`](https://github.com/joshua-jingu-lee/ante/commit/d222323b55c9b4f0507b1f0c8cd7680800e7c56d))

- **rule**: DailyLossLimitRule 손실률 분모를 전일 총 자산으로 수정
  ([#712](https://github.com/joshua-jingu-lee/ante/pull/712),
  [`89bb965`](https://github.com/joshua-jingu-lee/ante/commit/89bb965017bb23f5272b36c48bcd65febdbdb92e))

- **rule**: DailyLossLimitRule/TotalExposureLimitRule 매도(손절) 허용 및 알림 전환
  ([#716](https://github.com/joshua-jingu-lee/ante/pull/716),
  [`c912271`](https://github.com/joshua-jingu-lee/ante/commit/c912271b8a6fa58ffe3f89481662caf9a7e8ff38))

- **rule**: PositionSizeRule 분모를 봇 할당 예산으로 수정 (#771)
  ([#782](https://github.com/joshua-jingu-lee/ante/pull/782),
  [`cc51989`](https://github.com/joshua-jingu-lee/ante/commit/cc5198940019e17c094c875f301fc0825438946f))

- **rule**: RuleEngine.start() sync 시그니처 확인 및 회귀 테스트 추가 #742
  ([#760](https://github.com/joshua-jingu-lee/ante/pull/760),
  [`26bfbf5`](https://github.com/joshua-jingu-lee/ante/commit/26bfbf517c6ee0d273e0bac4f590c18f94de16a5))

- **rule**: TotalExposureLimitRule 노출률을 전 봇 합산/총 자산으로 수정
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **rule**: TotalExposureLimitRule 노출률을 전 봇 합산/총 자산으로 수정 #710
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **rule**: TradingHoursRule이 Account의 거래시간을 RuleContext 경유로 사용 #781
  ([#818](https://github.com/joshua-jingu-lee/ante/pull/818),
  [`be6ec32`](https://github.com/joshua-jingu-lee/ante/commit/be6ec32fbe351c2e204b30a00ff2ed32c1821e2f))

- **rule**: UnrealizedLossLimitRule metadata 경유 제거 및 데이터 주입 구현 #783
  ([#810](https://github.com/joshua-jingu-lee/ante/pull/810),
  [`47590a1`](https://github.com/joshua-jingu-lee/ante/commit/47590a13b9757c16cf1b5c461381abb49e4d7629))

- **rule**: 계좌 리스크 룰 config validation 추가 — 음수 값 거부
  ([#851](https://github.com/joshua-jingu-lee/ante/pull/851),
  [`3942c2a`](https://github.com/joshua-jingu-lee/ante/commit/3942c2abf6b86e63003a5a93233997a2a4a8dfd4))

- **strategy**: 전략 성과 조회 500 에러 수정 (#659)
  ([#665](https://github.com/joshua-jingu-lee/ante/pull/665),
  [`eba47a3`](https://github.com/joshua-jingu-lee/ante/commit/eba47a3a7b707231f7a40ab8399fbf6a90f5021c))

- **tc**: Account create 대화형 테스트에 인증정보 입력 추가
  ([`b2f6e42`](https://github.com/joshua-jingu-lee/ante/commit/b2f6e42add84da157c44c1a54b54248ad3b5a6bf))

- **tc**: Account/rules TC 재실행 시 409 Conflict 실패 수정
  ([#861](https://github.com/joshua-jingu-lee/ante/pull/861),
  [`ed3daff`](https://github.com/joshua-jingu-lee/ante/commit/ed3daff0138ed0444045c1517cd99689b4992785))

- **tc**: Allocation.feature 멱등성 확보 — 봇 삭제 후 재생성 방식
  ([`fb1aa0f`](https://github.com/joshua-jingu-lee/ante/commit/fb1aa0fd1d512d3f7d2ebffcdb62f67b76cc5448))

- **tc**: Allocation.feature 봇 생성에 bot_id 필드 추가
  ([`de96a76`](https://github.com/joshua-jingu-lee/ante/commit/de96a76aa0d0ee33b9e39e8de58dbc3701c244f1))

- **tc**: Allocation.feature 봇 생성에 strategy_id 누락 수정
  ([`ed09b08`](https://github.com/joshua-jingu-lee/ante/commit/ed09b089b04f23e750bb325544a5814ac9103895))

- **tc**: Broker_type mock → test로 일괄 변경 ([#636](https://github.com/joshua-jingu-lee/ante/pull/636),
  [`f22562d`](https://github.com/joshua-jingu-lee/ante/commit/f22562dad19f7c1dba79d522a92795ec2c5cde30))

- **tc**: Credentials.feature broker_type 재설계 (#662)
  ([#669](https://github.com/joshua-jingu-lee/ante/pull/669),
  [`58d3259`](https://github.com/joshua-jingu-lee/ante/commit/58d325982d5f86dcadbf5def08ab79c42f7939e3))

- **tc**: Credentials.feature 멱등성 확보 — 계좌/봇 생성 시 409 허용
  ([`92f25fa`](https://github.com/joshua-jingu-lee/ante/commit/92f25fa8f9934d9a125e2d7311a079eba0930148))

- **tc**: Init.feature CLI 시스템 상태 필드명 수정
  ([`9698c97`](https://github.com/joshua-jingu-lee/ante/commit/9698c976e3cdc1cf03a28e30f6199f4c62efc4f1))

- **tc**: Init.feature 응답 구조 및 환경값 불일치 수정 (#661)
  ([#668](https://github.com/joshua-jingu-lee/ante/pull/668),
  [`8a905a5`](https://github.com/joshua-jingu-lee/ante/commit/8a905a52b6635cfeb768adc0243a872b4da5ab2f))

- **tc**: Install.feature DART 프롬프트 입력 추가 및 allocation.feature 멱등성 보강
  ([`363798c`](https://github.com/joshua-jingu-lee/ante/commit/363798c5e902a9b3c1ddc88248d5cb6e02f66cf3))

- **tc**: TC 데이터 보완 — DELETE 204, 봇 필수필드, 비밀번호 불일치
  ([#647](https://github.com/joshua-jingu-lee/ante/pull/647),
  [`82eedf2`](https://github.com/joshua-jingu-lee/ante/commit/82eedf2e6b7620920135ce246eb5197a304cb962))

- **tc**: Treasury TC credentials API 404 수정 및 allocation 정리 추가
  ([#859](https://github.com/joshua-jingu-lee/ante/pull/859),
  [`a8620ae`](https://github.com/joshua-jingu-lee/ante/commit/a8620ae9f3d4ae1fa5807607e82a872b31c8703d))

- **test**: _on_restart_exhausted 호출에 account_id 파라미터 추가
  ([#757](https://github.com/joshua-jingu-lee/ante/pull/757),
  [`bf8997d`](https://github.com/joshua-jingu-lee/ante/commit/bf8997da15d102f3e0f63c8bd0c43f4acaafe143))

- **test**: Account delete 테스트 mock 대상을 IPC로 전환
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **test**: Account 생성 시 credentials 누락된 테스트 일괄 수정 #803
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **test**: BacktestConfig 테스트에서 commission_rate를 buy/sell로 분리 반영 #734
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **test**: FakeTreasury에 get_latest_snapshot 메서드 추가
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **test**: IPC 핸들러 등록 테스트 기대값 15 → 16으로 수정
  ([#720](https://github.com/joshua-jingu-lee/ante/pull/720),
  [`dd45dc1`](https://github.com/joshua-jingu-lee/ante/commit/dd45dc128214aeabbf1bb3ca2164639c54e1acbc))

- **test**: Portfolio history 존재하지 않는 account_id 테스트 기대값을 404로 수정
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **test**: PortfolioHistoryResponse 테스트 mock 데이터를 현행 모델에 맞게 갱신
  ([#714](https://github.com/joshua-jingu-lee/ante/pull/714),
  [`5c20546`](https://github.com/joshua-jingu-lee/ante/commit/5c20546479b8cce36c6ac6978860eb2566c29399))

- **test**: Replace private _handlers access with public get_handlers() API
  ([#758](https://github.com/joshua-jingu-lee/ante/pull/758),
  [`946a7ed`](https://github.com/joshua-jingu-lee/ante/commit/946a7edcaffea13703d5ca5083a6a6ade2810cd2))

- **test**: Test_config_path를 대화형 init 흐름에 맞게 수정
  ([`9636743`](https://github.com/joshua-jingu-lee/ante/commit/9636743c01c257d5b23e6a90e0cc3dc2e5c570b5))

- **test**: Test_consecutive_timeout_stops_bot를 ERROR 전이 검증으로 수정 #793
  ([#811](https://github.com/joshua-jingu-lee/ante/pull/811),
  [`c89b952`](https://github.com/joshua-jingu-lee/ante/commit/c89b9527f2fd03c12ae630e153bbc749e0d3b298))

- **test**: Test_register_sets_expiry에 master 조회 mock 추가
  ([#763](https://github.com/joshua-jingu-lee/ante/pull/763),
  [`58ed8bd`](https://github.com/joshua-jingu-lee/ante/commit/58ed8bdd49233bf502c8d4540fd460823748b004))

- **test**: TestBotManagerExchangeValidation에 credentials 추가 #803
  ([#803](https://github.com/joshua-jingu-lee/ante/pull/803),
  [`67e228c`](https://github.com/joshua-jingu-lee/ante/commit/67e228c4a08b0bb6d3f3e3f90525eedf0e987904))

- **test**: 에픽 브랜치 통합 후 테스트 수정 ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **trade**: Force_update() 후 인메모리 캐시 갱신 누락 수정
  ([#754](https://github.com/joshua-jingu-lee/ante/pull/754),
  [`0742e38`](https://github.com/joshua-jingu-lee/ante/commit/0742e382cb138ee0a66dac4e4180a45eb09c2157))

- **trade**: INSERT문에 exchange 컬럼 누락 수정 (#737)
  ([#764](https://github.com/joshua-jingu-lee/ante/pull/764),
  [`0830c1d`](https://github.com/joshua-jingu-lee/ante/commit/0830c1ddac6d645efd9db99813c6187cd5d89a7c))

- **trade**: MDD 비율 계산을 equity curve 기반으로 전환 #788
  ([#815](https://github.com/joshua-jingu-lee/ante/pull/815),
  [`bd9aed3`](https://github.com/joshua-jingu-lee/ante/commit/bd9aed30b0441bac702c14cfedd83de963af187c))

- **trade**: PerformanceTracker JOIN 조건을 trade_id FK 기반으로 변경 #785
  ([#817](https://github.com/joshua-jingu-lee/ante/pull/817),
  [`1519d14`](https://github.com/joshua-jingu-lee/ante/commit/1519d1415ee2747ba7e097488fbacdc24781dcce))

- **trade**: PerformanceTracker.calculate()에서 account_id 필수 검증 추가
  ([#805](https://github.com/joshua-jingu-lee/ante/pull/805),
  [`d49117c`](https://github.com/joshua-jingu-lee/ante/commit/d49117cf84d8801cb15160b91d031b7442d01f72))

- **trade**: QA 시드 데이터 trade_id UUID 파싱 실패 수정 Refs #865
  ([#867](https://github.com/joshua-jingu-lee/ante/pull/867),
  [`06afba0`](https://github.com/joshua-jingu-lee/ante/commit/06afba02e3e5646c2a452f3e74b7143e4221a30a))

- **trade**: 체결 알림에 누적 수량/평단가/손익 추가 #777 ([#819](https://github.com/joshua-jingu-lee/ante/pull/819),
  [`3aec7b7`](https://github.com/joshua-jingu-lee/ante/commit/3aec7b70b5773247b85d680cc43b1dd2ab2cc798))

- **trade**: 초과 매도 시 보유 수량 기준으로 PnL 계산 #769
  ([#778](https://github.com/joshua-jingu-lee/ante/pull/778),
  [`a686bd0`](https://github.com/joshua-jingu-lee/ante/commit/a686bd064472aa2c6630534ac59d1dd54d4c3d15))

- **treasury**: DailyReportEvent 구독 priority 70→80 통일
  ([#758](https://github.com/joshua-jingu-lee/ante/pull/758),
  [`946a7ed`](https://github.com/joshua-jingu-lee/ante/commit/946a7edcaffea13703d5ca5083a6a6ade2810cd2))

- **treasury**: DailyReportEvent 구독 priority 70→80 통일 #751
  ([#758](https://github.com/joshua-jingu-lee/ante/pull/758),
  [`946a7ed`](https://github.com/joshua-jingu-lee/ante/commit/946a7edcaffea13703d5ca5083a6a6ade2810cd2))

- **treasury**: Reserve_for_order()에 amount <= 0 입력 검증 추가
  ([#808](https://github.com/joshua-jingu-lee/ante/pull/808),
  [`ff56e99`](https://github.com/joshua-jingu-lee/ante/commit/ff56e99598ccc0e290aaf6ec6b3da8e3b4ce9ec3))

- **treasury**: Take_snapshot()이 스냅샷 dict를 반환하도록 수정 #752
  ([#759](https://github.com/joshua-jingu-lee/ante/pull/759),
  [`cba10bb`](https://github.com/joshua-jingu-lee/ante/commit/cba10bbbd0c39561a92dde94a7a35de1f7a06f8e))

- **treasury**: Total_asset 산식을 ante_eval_amount + unallocated로 수정
  ([#755](https://github.com/joshua-jingu-lee/ante/pull/755),
  [`54201f9`](https://github.com/joshua-jingu-lee/ante/commit/54201f9ff20106aa9ae35d350815a3ac1e5e1900))

- **treasury**: Treasury_state 테이블에 누락 필드 추가하여 재시작 시 평가액 데이터 복원
  ([#765](https://github.com/joshua-jingu-lee/ante/pull/765),
  [`9e5e2de`](https://github.com/joshua-jingu-lee/ante/commit/9e5e2de31b6551399994cc7c9956e254d6959edf))

- **treasury**: Treasury_transactions account_id DEFAULT 제거, NOT NULL 강제
  ([#812](https://github.com/joshua-jingu-lee/ante/pull/812),
  [`c411495`](https://github.com/joshua-jingu-lee/ante/commit/c411495acb75f4cf82cecc83ff674230d10054a1))

- **treasury**: 봇 삭제 시 Treasury budget 환수 및 정리
  ([#679](https://github.com/joshua-jingu-lee/ante/pull/679),
  [`273c9ea`](https://github.com/joshua-jingu-lee/ante/commit/273c9eae93972dae445598ae6e565760ae11d3a8))

- **treasury**: 존재하지 않는 봇 예산 할당 시 404 반환 (#658)
  ([#664](https://github.com/joshua-jingu-lee/ante/pull/664),
  [`bd6caf8`](https://github.com/joshua-jingu-lee/ante/commit/bd6caf8b7a8c92b20efca64124550b47e0916b4f))

- **ui**: 타이포그래피 위반 22건 + 인라인 스타일 1건 수정 ([#872](https://github.com/joshua-jingu-lee/ante/pull/872),
  [`0960bd2`](https://github.com/joshua-jingu-lee/ante/commit/0960bd2bb9c10522f64f1fbe896a37761157547f))

- **web**: /api/auth/me 엔드포인트에 Bearer 토큰 인증 지원 추가 #704
  ([#706](https://github.com/joshua-jingu-lee/ante/pull/706),
  [`170babe`](https://github.com/joshua-jingu-lee/ante/commit/170babef129a8b8f68f283815d4b0ac58d3b5351))

- **web**: PR #688 리뷰 지적 사항 반영 — 하위 호환성 및 response_model 추가
  ([#688](https://github.com/joshua-jingu-lee/ante/pull/688),
  [`272857f`](https://github.com/joshua-jingu-lee/ante/commit/272857fd62a75f077483b5311413cf8b0cd6685d))

- **web**: 멤버 API 라우트 caller_id를 request.state.member_id에서 취득 #767
  ([#768](https://github.com/joshua-jingu-lee/ante/pull/768),
  [`c63f094`](https://github.com/joshua-jingu-lee/ante/commit/c63f0940e733f5b08baf46022677bde2b6b6ef26))

### Chores

- .claude/ 전체 gitignore 처리
  ([`2a1d9fd`](https://github.com/joshua-jingu-lee/ante/commit/2a1d9fd580af869ead7d66245cb561c813a8de8a))

- Dockerfile 테스트 시드 제거 및 대시보드 기본 활성화
  ([`62eb08a`](https://github.com/joshua-jingu-lee/ante/commit/62eb08adad3dcdb29691f7aad9dc1ff1df834e53))

- Trigger CI ([#740](https://github.com/joshua-jingu-lee/ante/pull/740),
  [`8a89127`](https://github.com/joshua-jingu-lee/ante/commit/8a891273311f7ee7de0ca7fe5896142090d8f049))

- 스킬 파일 정리 및 QA 환경 설정 보완
  ([`e40f507`](https://github.com/joshua-jingu-lee/ante/commit/e40f5079885fea6a6e4187c2a13bbfc43e5554a2))

- **ci**: CI/QA에 ANTE_DB_ENCRYPTION_KEY 환경변수 추가
  ([#744](https://github.com/joshua-jingu-lee/ante/pull/744),
  [`3d7a5be`](https://github.com/joshua-jingu-lee/ante/commit/3d7a5bee325b0e25e31b7120dd76321b97c965ca))

- **deps**: Add cryptography package for Fernet encryption
  ([#735](https://github.com/joshua-jingu-lee/ante/pull/735),
  [`fe219a0`](https://github.com/joshua-jingu-lee/ante/commit/fe219a0cf85dfbf7621b0d5549507c296e332ea5))

- **tc**: Credentials.feature 사전 정리 단계 추가 — API+DB 2단계 클린업
  ([`b138c20`](https://github.com/joshua-jingu-lee/ante/commit/b138c206215c619395fb319d49562a3995cc2a7c))

### Code Style

- Pyproject.toml 섹션 간 빈 줄 추가 ([#609](https://github.com/joshua-jingu-lee/ante/pull/609),
  [`1072c26`](https://github.com/joshua-jingu-lee/ante/commit/1072c262bd7e170aefff20f3b8f4a75d8305a183))

### Continuous Integration

- PyPI 배포 워크플로우 추가 Refs #919 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- Semantic-release에서 Docker 빌드·push 단계 제거
  ([`4e146a4`](https://github.com/joshua-jingu-lee/ante/commit/4e146a44c81b260fcefb2154ffc8af9d9e1b812b))

### Documentation

- Getting Started 가이드 작성 및 ante init 스펙 갱신
  ([`76ec15a`](https://github.com/joshua-jingu-lee/ante/commit/76ec15a60fa5d6bdfd142c4871b0b4c4f6dbd38c))

- README.md 간결화 및 태그라인 수정
  ([`8bef8c9`](https://github.com/joshua-jingu-lee/ante/commit/8bef8c93b3098b3e9e9b024ec68e5578882ffa64))

- 공개용 사용자 가이드 디렉토리 초기 구조 생성
  ([`2ddaddd`](https://github.com/joshua-jingu-lee/ante/commit/2ddaddd056c77206a739492d538b4d157bfe2831))

- **account**: Suspend/delete docstring에 AccountDeletedException 누락 보완
  ([#725](https://github.com/joshua-jingu-lee/ante/pull/725),
  [`9309429`](https://github.com/joshua-jingu-lee/ante/commit/9309429cddb91dd42bd4713849d8b07ef72f212d))

- **cli**: 헤더를 사용자 친화적 소개 문구로 변경
  ([`141eb4f`](https://github.com/joshua-jingu-lee/ante/commit/141eb4f16f57b4efe685087f806df3c16c6b7b06))

- **guide**: Account 모델 반영하여 가이드 문서 업데이트 (#576)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **guide**: Docker 설치 섹션 제거 및 플랫폼 요구사항 명시
  ([`078a405`](https://github.com/joshua-jingu-lee/ante/commit/078a405a7dee2e4c5c7874fbf5495a32637ae1c0))

- **guide**: Treasury snapshot 커맨드를 cli.md에 등록
  ([#687](https://github.com/joshua-jingu-lee/ante/pull/687),
  [`057283b`](https://github.com/joshua-jingu-lee/ante/commit/057283ba662fde219b17f0231ac7a7fee483227d))

- **guide**: 대시보드·보안 가이드 포트 번호 수정 (8000 → 3982)
  ([`119797b`](https://github.com/joshua-jingu-lee/ante/commit/119797ba497e716b1b793a0bdde6f8ac7da926c7))

- **guide**: 대시보드·보안·전략 가이드 문서 작성
  ([`a2a2356`](https://github.com/joshua-jingu-lee/ante/commit/a2a235674f906347d8967935d19c1a95ae078769))

- **tc**: Gherkin TC 컨벤션 가이드 작성 ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

### Features

- 결재함 서버사이드 검색 + 스토리지 유형별 용량 표시 (#905) ([#906](https://github.com/joshua-jingu-lee/ante/pull/906),
  [`ca4a0da`](https://github.com/joshua-jingu-lee/ante/commit/ca4a0da81cc483696ff2be404c44b63d8a888cb8))

- 자금 거래내역 날짜 필터, 데이터셋 파일크기/미리보기, 검색 debounce
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- 프로젝트 에이전트 6종 추가 (.claude/agents/)
  ([`ee67b52`](https://github.com/joshua-jingu-lee/ante/commit/ee67b526b9dc4b21d03474129e04f5cbc209fe1c))

- **account**: Account 모델·서비스·DB 스키마 생성 (#560)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **approval**: GET /api/approvals에 search 쿼리 파라미터 추가 #794
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **approval**: 결재함 제목 검색을 서버사이드로 전환 ([#906](https://github.com/joshua-jingu-lee/ante/pull/906),
  [`ca4a0da`](https://github.com/joshua-jingu-lee/ante/commit/ca4a0da81cc483696ff2be404c44b63d8a888cb8))

- **backtest**: _validate_config() -> BacktestConfig 통합 + 수수료 분리 #727
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **backtest**: BacktestConfig/DatasetInfo 데이터클래스 생성 Refs #722
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **backtest**: BacktestDataProvider에 loaded_datasets 이력 기록 Refs #726
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **backtest**: BacktestResult에 config/datasets 필드 추가 Refs #723
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **bot**: BotConfig에 account_id 추가, bot_type·exchange 제거 (#564)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **bot**: BotStepCompletedEvent 추가 및 봇 실행 로그 API #786
  ([#821](https://github.com/joshua-jingu-lee/ante/pull/821),
  [`d5b6ba6`](https://github.com/joshua-jingu-lee/ante/commit/d5b6ba6263283193c8d3bb12d223a1836d965d7e))

- **bot**: DELETE /api/bots/{id}에 handle_positions 옵션 추가 #796
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **bot**: GET /api/bots 응답에 strategy_name, strategy_author_name 추가 #792
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **bot**: PUT /api/bots/{bot_id} 봇 설정 수정 API #795
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **cli**: Ante account 명령어 그룹 구현 (#571) ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: Ante init 대화형 통합 초기 설정 ([#557](https://github.com/joshua-jingu-lee/ante/pull/557),
  [`cc3c301`](https://github.com/joshua-jingu-lee/ante/commit/cc3c301d04ddf663009bd26f334d0a431fc92d73))

- **cli**: Ante update --format json 지원 Refs #920
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **cli**: Ante update 명령 구현 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **cli**: CLI 레퍼런스 문서에 자동 목차 생성 추가
  ([`0f9adb7`](https://github.com/joshua-jingu-lee/ante/commit/0f9adb7b1ef82c2931692384bdda9953b9f90a9e))

- **cli**: CLI 버전을 importlib.metadata에서 자동 읽기 Refs #911
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **cli**: CLI 전 커맨드에 --format json 서브커맨드 옵션 추가 (#632)
  ([#639](https://github.com/joshua-jingu-lee/ante/pull/639),
  [`4e4151a`](https://github.com/joshua-jingu-lee/ante/commit/4e4151a93da2b008e7b96400ccd196c9fc0a4516))

- **cli**: System status --format json 옵션 추가 (#663)
  ([#667](https://github.com/joshua-jingu-lee/ante/pull/667),
  [`a900322`](https://github.com/joshua-jingu-lee/ante/commit/a900322109a46de7e7d74ebb15c72df21c392575))

- **cli**: Treasury snapshot 커맨드 구현 ([#687](https://github.com/joshua-jingu-lee/ante/pull/687),
  [`057283b`](https://github.com/joshua-jingu-lee/ante/commit/057283ba662fde219b17f0231ac7a7fee483227d))

- **cli**: 기존 CLI 명령어에 --account 옵션 추가 (#573)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: 서버 실행 중 확인 유틸 함수 추가 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **dashboard**: 결재함·에이전트·백테스트·리포트 보완 (Phase 5) Refs #838
  ([#845](https://github.com/joshua-jingu-lee/ante/pull/845),
  [`e5423ae`](https://github.com/joshua-jingu-lee/ante/commit/e5423aef16462f6cbd53e5050fbdec16302292a3))

- **dashboard**: 리포트 상세 페이지 자산 커브 차트 연동 #838
  ([#864](https://github.com/joshua-jingu-lee/ante/pull/864),
  [`e529169`](https://github.com/joshua-jingu-lee/ante/commit/e5291692ffa1fc4ad81398fc491ee98222979906))

- **dashboard**: 봇 관리 실행 설정·수정·삭제 API 연동 (Phase 3b) #835
  ([#862](https://github.com/joshua-jingu-lee/ante/pull/862),
  [`2a2bcbe`](https://github.com/joshua-jingu-lee/ante/commit/2a2bcbe528a62ee49a0492e0510f1f36601c2365))

- **dashboard**: 전략 목록 UI 보강 — PAGE_SIZE 15, 검색, 보관 탭, 더보기 링크 #836
  ([#843](https://github.com/joshua-jingu-lee/ante/pull/843),
  [`585dfcf`](https://github.com/joshua-jingu-lee/ante/commit/585dfcfd4f25a4f4ebe2d1646ee3228f46384361))

- **dashboard**: 전략과 성과 Phase 4b — 차트·성과·필터·상태 전환 Refs #837
  ([#863](https://github.com/joshua-jingu-lee/ante/pull/863),
  [`96c1993`](https://github.com/joshua-jingu-lee/ante/commit/96c19939e02c1d32beaf2fa81fb10164570a42db))

- **data**: Parquet 경로에 exchange 차원 추가 (#577)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **data**: ParquetStore.resolve_path() public 노출
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **data**: 데이터셋 파일 크기 연동 및 미리보기 구현 ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **data**: 스토리지 현황에 유형별(OHLCV/Fundamental) 용량 표시 추가
  ([#906](https://github.com/joshua-jingu-lee/ante/pull/906),
  [`ca4a0da`](https://github.com/joshua-jingu-lee/ante/commit/ca4a0da81cc483696ff2be404c44b63d8a888cb8))

- **db**: Database 트랜잭션 컨텍스트 매니저 추가 Refs #912
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **db**: Parquet 마이그레이션을 중앙 러너에 통합 Refs #924
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **db**: Schema_version 테이블 + 중앙 마이그레이션 러너 Refs #913
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **eventbus**: Account 이벤트 3종 추가 및 기존 이벤트 account_id 확장 (#562)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **frontend**: 데이터셋 파일크기/미리보기 UI 및 종목 검색 debounce 적용
  ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **frontend**: 로그인 스펙 정합성 보완 (Phase 1) Refs #832
  ([#841](https://github.com/joshua-jingu-lee/ante/pull/841),
  [`fd7e389`](https://github.com/joshua-jingu-lee/ante/commit/fd7e389ab122999a95795ed27daa2b029631e8ac))

- **frontend**: 리포트 상세 듀얼 차트·마크다운·수익률% 병기 Refs #892
  ([#909](https://github.com/joshua-jingu-lee/ante/pull/909),
  [`f5d1314`](https://github.com/joshua-jingu-lee/ante/commit/f5d1314f5a418d8685cf3f5b625e3034c50d86c2))

- **frontend**: 봇 관리 카드·UI 정리 (Phase 3a) Refs #834
  ([#844](https://github.com/joshua-jingu-lee/ante/pull/844),
  [`e1f8a35`](https://github.com/joshua-jingu-lee/ante/commit/e1f8a35e58d1adb4187a58f60a479cb28f8f4283))

- **frontend**: 자금관리 Phase 2 — 가상 거래 배너 + 자산 추이 차트 + 예산 가드
  ([#842](https://github.com/joshua-jingu-lee/ante/pull/842),
  [`98c01af`](https://github.com/joshua-jingu-lee/ante/commit/98c01af86042150aeabf731c8cce9fa417e4ba41))

- **infra**: 백엔드 전용 QA Docker 이미지 작성 (#606)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **ipc**: IPC 인프라 구축 — ServiceRegistry, 프로토콜, IPCServer/Client #695
  ([#700](https://github.com/joshua-jingu-lee/ante/pull/700),
  [`3002f10`](https://github.com/joshua-jingu-lee/ante/commit/3002f10f4dc691954cd948081dc61f95a6a17021))

- **qa**: QA 데이터셋 시드 스크립트 추가 Refs #856 ([#860](https://github.com/joshua-jingu-lee/ante/pull/860),
  [`262f33b`](https://github.com/joshua-jingu-lee/ante/commit/262f33bcc6a40bc7c7165c023cc17c7cb9a8be72))

- **qa**: QA 서버 설정 및 엔트리포인트 작성 (#607) ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **qa**: 자동 버그 리포팅 및 --fix 수정 연동, night-mode QA 통합 (#618)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **rule**: RuleContext 자산/노출 필드 추가 및 Treasury 조회 헬퍼 추출
  ([#713](https://github.com/joshua-jingu-lee/ante/pull/713),
  [`639bfc9`](https://github.com/joshua-jingu-lee/ante/commit/639bfc9d1ba2ec3513ff556e1e7c1f86a676058a))

- **skill**: QA 테스트 에이전트 스킬 작성 (.claude/skills/qa-tester/)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **strategy**: Exchange 호환성 검증 추가 (#570)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **system**: 서버 시작 시 최신 버전 확인 로그 Refs #923
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **tc**: 대화형 설치 프로세스 검증 TC 추가 (install.feature)
  ([`8de7a59`](https://github.com/joshua-jingu-lee/ante/commit/8de7a59661e15255df08ce88deba95cecbad7f77))

- **tc**: 최초 설치 검증 TC 및 QA 환경 가이드 추가
  ([`8a673ff`](https://github.com/joshua-jingu-lee/ante/commit/8a673ff204295452aa48c2dfaea3cb2ad848330e))

- **trade**: DailyReportScheduler Account 기반 실행 시각 + DailyReportEvent 신설
  ([#683](https://github.com/joshua-jingu-lee/ante/pull/683),
  [`ffd7a68`](https://github.com/joshua-jingu-lee/ante/commit/ffd7a68e20da579626119815a54935e2974c1645))

- **trade**: TradeRecord·PositionSnapshot에 account_id, currency 필드 추가
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **treasury**: Treasury 계좌별 인스턴스 전환 및 TreasuryManager 도입
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **treasury**: Virtual 모드 자산 평가 동기화 — Trade DB 기반 계산 (#692)
  ([#693](https://github.com/joshua-jingu-lee/ante/pull/693),
  [`d4b3e7d`](https://github.com/joshua-jingu-lee/ante/commit/d4b3e7d9a1bf31cead4b345ac258095e2407bc08))

- **treasury**: 일별 자산 스냅샷 확장 — 성과 필드, 범위 조회, 자동 삭제 (#682)
  ([#686](https://github.com/joshua-jingu-lee/ante/pull/686),
  [`16c5788`](https://github.com/joshua-jingu-lee/ante/commit/16c57887ed7bd250c284424bbedc0ffaebd6aac0))

- **treasury**: 자금 거래내역 기간(날짜) 필터 추가 ([#904](https://github.com/joshua-jingu-lee/ante/pull/904),
  [`cd2f469`](https://github.com/joshua-jingu-lee/ante/commit/cd2f469d5de218bcafbfe75324b8477e0a0189ba))

- **update**: DB 안전 백업 함수 구현 Refs #916 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **update**: 디스크 공간 사전 검사 Refs #922 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **update**: 마이그레이션 실패 시 자동 롤백 Refs #918
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **update**: 업데이트 전 의존성 스냅샷 저장 Refs #921
  ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **web**: Account CRUD REST API 엔드포인트 추가 (#574)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **web**: Agent 토큰 인증 시 last_active_at 갱신 (5분 스로틀링)
  ([#604](https://github.com/joshua-jingu-lee/ante/pull/604),
  [`4a48b97`](https://github.com/joshua-jingu-lee/ante/commit/4a48b976275dbcc1c382390378d977698f4f0090))

- **web**: Agent 토큰 인증 시 last_active_at 갱신 미들웨어 추가
  ([#604](https://github.com/joshua-jingu-lee/ante/pull/604),
  [`4a48b97`](https://github.com/joshua-jingu-lee/ante/commit/4a48b976275dbcc1c382390378d977698f4f0090))

- **web**: GET /api/data/datasets/{dataset_id} 데이터셋 상세 API #799
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: GET /api/strategies 응답에 cumulative_return 추가 #800
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: GET /api/strategies/{id} 응답에 params, rationale, risks 추가 #802
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: GET/PUT /api/accounts/{id}/rules 리스크 룰 조회·수정 API #798
  ([#830](https://github.com/joshua-jingu-lee/ante/pull/830),
  [`4319fe6`](https://github.com/joshua-jingu-lee/ante/commit/4319fe6768222600fc56da96da97415f8b598c02))

- **web**: 기존 API 엔드포인트에 account_id 필터 및 응답 필드 추가 (#575)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **web**: 일별 자산 스냅샷 Web API 엔드포인트 (#684)
  ([#688](https://github.com/joshua-jingu-lee/ante/pull/688),
  [`272857f`](https://github.com/joshua-jingu-lee/ante/commit/272857fd62a75f077483b5311413cf8b0cd6685d))

- **web**: 일별 자산 스냅샷 Web API 엔드포인트 구현 ([#688](https://github.com/joshua-jingu-lee/ante/pull/688),
  [`272857f`](https://github.com/joshua-jingu-lee/ante/commit/272857fd62a75f077483b5311413cf8b0cd6685d))

### Performance Improvements

- **backtest**: Equity_curve 일봉 리샘플링으로 detail_json 저장 최적화 #741
  ([#762](https://github.com/joshua-jingu-lee/ante/pull/762),
  [`d5d96c5`](https://github.com/joshua-jingu-lee/ante/commit/d5d96c5d11632c629ed82597fe0814a6bc78f53e))

### Refactoring

- CLI 레퍼런스 출력 경로를 guide/cli.md로 일원화
  ([`3d17074`](https://github.com/joshua-jingu-lee/ante/commit/3d17074ad90a8aaf205eb82d2e0972646936e2dc))

- **account**: Account 모델에 broker_config 필드 추가
  ([#941](https://github.com/joshua-jingu-lee/ante/pull/941),
  [`ce4f312`](https://github.com/joshua-jingu-lee/ante/commit/ce4f312f77a56aea3e94a18a00cc9f862fce6d9e))

- **broker**: KISAdapter → KISBaseAdapter + KISDomesticAdapter 분리 (#561)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: Ante init 흐름에서 KIS 연동을 Account 등록으로 교체
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **cli**: Bot/Treasury 커맨드 IPC 전환 #697 ([#702](https://github.com/joshua-jingu-lee/ante/pull/702),
  [`bc7316b`](https://github.com/joshua-jingu-lee/ante/commit/bc7316b0d809cedeceb71b1a898bd76f73910a86))

- **cli**: CLI 레퍼런스 정렬을 알파벳순에서 등록순으로 변경
  ([`2d5fb24`](https://github.com/joshua-jingu-lee/ante/commit/2d5fb24a60d2605a9b1155fd5fd85ba3a7d56e63))

- **cli**: Config/Approval/Broker 커맨드 IPC 전환 및 IPC 헬퍼 통합 #698
  ([#703](https://github.com/joshua-jingu-lee/ante/pull/703),
  [`a61fc8c`](https://github.com/joshua-jingu-lee/ante/commit/a61fc8c8c16dca4a04ccfe5dd563a89f83452513))

- **cli**: System/Account 커맨드 IPC 전환 #696
  ([#701](https://github.com/joshua-jingu-lee/ante/pull/701),
  [`1449a20`](https://github.com/joshua-jingu-lee/ante/commit/1449a2030691b28a25edced7d5e7d422f174788c))

- **config**: Account 모델로 이관되는 broker 설정 키 제거
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **core**: SystemState 제거 및 Kill Switch를 Account.status 기반으로 일원화 (#568)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **db**: 기존 분산 _migrate_*() 메서드 제거 ([#940](https://github.com/joshua-jingu-lee/ante/pull/940),
  [`6958fd8`](https://github.com/joshua-jingu-lee/ante/commit/6958fd854787db2e6bf8c3ee8bcb0021d7276ae8))

- **frontend**: BacktestData 페이지 데이터 흐름 컨벤션 준수 (api → hooks → pages)
  ([#882](https://github.com/joshua-jingu-lee/ante/pull/882),
  [`3bbe5a8`](https://github.com/joshua-jingu-lee/ante/commit/3bbe5a8c331084546607e7ec7336ac9737b31de0))

- **frontend**: 라우팅·사이드바·대시보드 정리 (Phase 0) Refs #831
  ([#840](https://github.com/joshua-jingu-lee/ante/pull/840),
  [`8e95cf1`](https://github.com/joshua-jingu-lee/ante/commit/8e95cf1c25e48c88a3802188693612fd44edabc9))

- **gateway**: APIGateway 계좌 라우팅 전환 (#567)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **main**: Account 중심 Composition Root 재구성 (#578)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **rule**: Rule Engine 계좌별 인스턴스 전환 (#566)
  ([#598](https://github.com/joshua-jingu-lee/ante/pull/598),
  [`6ddd4c6`](https://github.com/joshua-jingu-lee/ante/commit/6ddd4c6fdb7aa5d753bd5f217c402cacd1989b41))

- **test**: E2E/Integration 테스트 인프라 및 Docker 테스트 설정 제거
  ([#609](https://github.com/joshua-jingu-lee/ante/pull/609),
  [`1072c26`](https://github.com/joshua-jingu-lee/ante/commit/1072c262bd7e170aefff20f3b8f4a75d8305a183))

- **test**: E2E/Integration 테스트 인프라 제거 ([#609](https://github.com/joshua-jingu-lee/ante/pull/609),
  [`1072c26`](https://github.com/joshua-jingu-lee/ante/commit/1072c262bd7e170aefff20f3b8f4a75d8305a183))

- **web**: Portfolio API에서 daily_pnl_pct 하위호환 필드 제거
  ([#689](https://github.com/joshua-jingu-lee/ante/pull/689),
  [`fbd6b3c`](https://github.com/joshua-jingu-lee/ante/commit/fbd6b3c3a9b4ba0a2007ef359a75afe524e58b14))

- **web**: 토큰 인증 last_active_at 갱신에 5분 스로틀링 추가
  ([#604](https://github.com/joshua-jingu-lee/ante/pull/604),
  [`4a48b97`](https://github.com/joshua-jingu-lee/ante/commit/4a48b976275dbcc1c382390378d977698f4f0090))

### Testing

- QA 테스트 케이스 추가 (approval, bot, data)
  ([`038d7e2`](https://github.com/joshua-jingu-lee/ante/commit/038d7e2ac5620e57fcdc5f414a8aefde38d66a38))

- **backtest**: Run() 실행 후 config/datasets 주입 검증 테스트 추가
  ([#734](https://github.com/joshua-jingu-lee/ante/pull/734),
  [`91c7e4e`](https://github.com/joshua-jingu-lee/ante/commit/91c7e4e1fbd56cc0f571a16df027c761bd1f209a))

- **bot**: _resolve_paper_balance 정상/KeyError 경로 테스트 추가
  ([#766](https://github.com/joshua-jingu-lee/ante/pull/766),
  [`b5c5d41`](https://github.com/joshua-jingu-lee/ante/commit/b5c5d4149fb44b818f8cdca9bed966e36737a05d))

- **rule**: RuleEngine WARN 결과 경로 단위 테스트 추가 #806
  ([#820](https://github.com/joshua-jingu-lee/ante/pull/820),
  [`730231e`](https://github.com/joshua-jingu-lee/ante/commit/730231ecb11612f27cbc8aa8bb577d9fdc8e8969))

- **tc**: Account 모듈 TC 확장 — lifecycle + credentials (#612)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: Member 모듈 TC 작성 (auth + management)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: Strategy + Config + Trade 모듈 TC 작성
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: Treasury 모듈 TC 작성 (balance + allocation) (#615)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))

- **tc**: 계좌 CRUD 파일럿 TC 작성 (account/crud.feature)
  ([#631](https://github.com/joshua-jingu-lee/ante/pull/631),
  [`e83058d`](https://github.com/joshua-jingu-lee/ante/commit/e83058df9e9dd151441f078f7b431f6178f9f57f))


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
