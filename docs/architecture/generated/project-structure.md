# Ante 프로젝트 디렉토리 구조

> 역할: Agent용 프로젝트 구조 INDEX의 단일 SSOT입니다.
> 생성 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py`
> Check 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py --check`
> 생성 기준: 현재 Git 추적/비무시 파일 트리 (`git ls-files --cached --others --exclude-standard`)
> 마지막 생성 시점: 2026-11-25 (KST)

## 최상위 구조

```
ante/
├── src/ante/                         # Python 백엔드 패키지
├── tests/                            # 단위·통합·E2E 테스트
├── guide/                            # 사용자·운용 가이드 문서
├── docs/                             # 설계 문서
├── deploy/                           # 서비스 배포 파일 (systemd, launchd)
├── scripts/                          # 설치·운영·문서 생성 스크립트
├── strategies/                       # 전략 템플릿과 예제
├── config/                           # 런타임 설정 예시와 의존성 스냅샷
├── .agent/                           # 에이전트 정의/명령/스킬
├── .claude/                          # Claude Code 설정 + .agent 호환 링크
├── .github/                          # GitHub 워크플로/이슈 템플릿/로컬 인증 파일
├── Dockerfile                        # 프로덕션 Docker 이미지
├── docker-compose.yml                # 프로덕션 Docker Compose (ante-logs named volume 포함)
├── AGENTS.md                         # 개발 Agent 마스터 가이드
├── CHANGELOG.md                      # 변경 이력
├── CONTRIBUTING.md                   # 외부 기여 계약
├── README.md                         # 프로젝트 개요
├── CLAUDE.md                         # Claude Code 호환 가이드
├── LICENSE                           # 라이선스
└── SECURITY.md                       # 보안 취약점 신고 정책
```

## src/ante/ — Python 백엔드

```
src/ante/
├── account/
│   ├── __init__.py
│   ├── crypto.py
│   ├── errors.py
│   ├── gate.py
│   ├── models.py
│   ├── presets.py
│   ├── readiness.py
│   ├── scoping.py
│   ├── service.py
│   └── timezone.py
├── approval/
│   ├── __init__.py
│   ├── auto_approve.py
│   ├── errors.py
│   ├── handlers.py
│   ├── models.py                     # ApprovalRequest, ApprovalStatus, ApprovalType
│   └── service.py                    # ApprovalService — 결재 요청 관리 + 자동 실행
├── audit/
│   ├── __init__.py
│   └── logger.py                     # AuditLogger — 감사 로그 기록 (SQLite)
├── backtest/
│   ├── __init__.py
│   ├── config.py
│   ├── context.py                    # BacktestContext — 백테스트 실행 환경
│   ├── data_provider.py              # BacktestDataProvider — Parquet 기반 시세 공급
│   ├── exceptions.py
│   ├── executor.py                   # BacktestExecutor — 전략 실행 루프
│   ├── metrics.py                    # calculate_metrics — 성과 지표 (Sharpe, MDD 등)
│   ├── result.py                     # BacktestResult, BacktestTrade — 결과 모델
│   ├── run_store.py
│   ├── runner.py                     # BacktestRunner — subprocess 진입점
│   └── service.py                    # BacktestService — 메인 프로세스 인터페이스
├── bot/
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── live.py                   # LiveProvider — 실전 봇 데이터 공급
│   │   └── virtual.py                # VirtualProvider — 가상 실행 봇 데이터 공급
│   ├── __init__.py
│   ├── bot.py                        # Bot — 봇 실행 루프, 전략 실행, 이벤트 발행
│   ├── cold_path.py
│   ├── config.py                     # BotConfig — 봇 설정 (exchange, 자금 한도 등)
│   ├── context_factory.py            # BotContextFactory — 봇 실행 컨텍스트 생성
│   ├── exceptions.py
│   ├── info.py
│   ├── manager.py                    # BotManager — 봇 생명주기 관리
│   ├── reconcile_scheduler.py
│   ├── signal_channel.py             # SignalChannel — JSON Lines 파이프 기반 양방향 시그널 채널
│   ├── signal_channel_registry.py
│   └── signal_key.py                 # SignalKeyManager — 봇별 시그널 키 발급/관리
├── broker/
│   ├── __init__.py
│   ├── base.py                       # BrokerAdapter ABC
│   ├── circuit_breaker.py            # CircuitBreaker — API 장애 차단
│   ├── error_codes.py                # KIS API 에러 코드 분류 (영구/일시)
│   ├── exceptions.py
│   ├── fill_scheduler.py
│   ├── kis.py                        # KISAdapter — 한국투자증권 API 구현체
│   ├── kis_stream.py                 # KISStreamClient — KIS WebSocket 실시간 시세/체결 통보
│   ├── mock.py                       # MockBroker — 테스트/모의투자용 브로커 구현체
│   ├── models.py                     # CommissionInfo dataclass
│   ├── order_registry.py             # OrderRegistry — 주문 상태 추적 (SQLite)
│   ├── registry.py
│   └── test.py
├── cli/
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── _password.py              # generate_password() — CLI용 랜덤 패스워드 유틸
│   │   ├── account.py
│   │   ├── approval.py               # ante approval approve/audit-types/cancel/cancel-invalid/info/list/reject/reopen/request/review
│   │   ├── audit.py                  # ante audit — 감사 로그 조회
│   │   ├── backtest.py               # ante backtest history/run
│   │   ├── bot.py                    # ante bot create/info/list/positions/remove/signal-key/start/stop/status
│   │   ├── broker.py                 # ante broker balance/positions/reconcile/status
│   │   ├── config.py                 # ante config get/history/set
│   │   ├── data.py                   # ante data list/schema/storage/validate
│   │   ├── feed.py                   # ante feed — DataFeed CLI 커맨드 (init/status/inject/config)
│   │   ├── init.py                   # ante init — 비대화형 최소 초기 설정 (master + 테스트 계좌)
│   │   ├── instrument.py             # ante instrument list/search/sync/import (--listed-only)
│   │   ├── ipc_helpers.py
│   │   ├── member.py                 # ante member register/list/info/suspend/revoke/set-emoji/... (bootstrap은 init으로 통합)
│   │   ├── notification.py           # 알림 CLI (public leaf 없음 — 텔레그램 이관)
│   │   ├── report.py                 # ante report schema/submit/list/performance/view
│   │   ├── rule.py                   # ante rule info/list
│   │   ├── signal.py                 # ante signal — 외부 시그널 채널 관리
│   │   ├── strategy.py               # ante strategy validate/submit/list/info/performance
│   │   ├── system.py                 # ante system clear-halt/halt/start/status/stop
│   │   ├── trade.py                  # ante trade info/list
│   │   ├── treasury.py               # ante treasury allocate/deallocate/snapshot/status
│   │   └── update.py
│   ├── __init__.py
│   ├── _data_path.py
│   ├── _validators.py
│   ├── cold_path.py
│   ├── db_context.py
│   ├── formatter.py                  # OutputFormatter — table/json 출력
│   ├── main.py                       # CLI 루트 그룹 (ante 커맨드)
│   └── middleware.py                 # 인증 미들웨어 (require_auth, require_scope)
├── config/
│   ├── __init__.py
│   ├── config.py                     # ConfigService — 설정 로딩 (system.toml + secrets.env)
│   ├── defaults.py                   # 기본 설정값
│   ├── dynamic.py                    # DynamicConfigService — DB 기반 런타임 설정
│   └── exceptions.py
├── contracts/
│   ├── __init__.py
│   ├── cli_errors.py
│   ├── cli_registry.py
│   ├── error_registry.py
│   ├── errors.py
│   ├── helpers.py
│   ├── ipc_client_errors.py
│   ├── request_errors.py
│   └── vocab.py
├── core/
│   ├── log/                          # 시스템 로그 인프라 (JSONL 포맷, fingerprint)
│   │   ├── __init__.py
│   │   ├── _record_keys.py           # LogRecord 속성 / Ante 예약 키 단일 소스 (runtime probe)
│   │   ├── fingerprint.py            # compute_fingerprint() — 예외 dedup 키
│   │   ├── formatter.py              # JsonFormatter — JSONL 직렬화
│   │   ├── handlers.py               # DateNamedTimedRotatingFileHandler (KST 자정 no-rename 회전)
│   │   ├── safe_logger.py            # AnteLogger, install_safe_logger() (makeRecord 예약 키 정규화)
│   │   └── setup.py                  # setup_logging() stdout + JSONL 파일 핸들러 구성
│   ├── __init__.py
│   ├── account_id.py
│   ├── clock.py
│   ├── database.py                   # Database — SQLite WAL 연결 관리
│   ├── exchange.py
│   ├── market_data_vocab.py
│   ├── price.py
│   ├── registry.py
│   └── time.py
├── data/
│   ├── __init__.py
│   ├── collector.py                  # DataCollector — 실시간 시세 수집 → Parquet
│   ├── datasets.py
│   ├── normalizer.py                 # BaseNormalizer ABC + KIS/Yahoo/Default Normalizer, DataNormalizer 파사드
│   ├── retention.py                  # DataRetention — 보존 정책, 외부 이관
│   ├── schemas.py                    # OHLCV 등 데이터 스키마 정의
│   └── store.py                      # DataStore — Parquet 읽기/쓰기
├── db/
│   ├── versions/
│   │   ├── __init__.py
│   │   ├── v001_baseline.py
│   │   ├── v002_parquet_migration.py
│   │   ├── v003_broker_config.py
│   │   ├── v004_strategy_status_simplify.py
│   │   ├── v005_trades_timestamp_isoformat.py
│   │   ├── v006_order_tracker_order_price.py
│   │   └── v007_order_tracker_exchange.py
│   ├── __init__.py
│   ├── backup.py
│   └── migrations.py
├── eventbus/
│   ├── __init__.py
│   ├── bus.py                        # EventBus — asyncio.Queue 기반 발행/구독
│   ├── events.py                     # 전체 이벤트 dataclass 정의
│   ├── fill_dedup_guard.py
│   └── history.py                    # EventHistory — 이벤트 이력 추적
├── feed/                             # DataFeed — 외부 데이터 수집 파이프라인
│   ├── models/
│   │   ├── __init__.py
│   │   └── result.py                 # ValidationResult, CollectionResult — 수집 결과 모델
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── backfill_runner.py
│   │   ├── checkpoint.py             # Checkpoint — 체크포인트 저장 및 복원
│   │   ├── daily_runner.py
│   │   ├── dart_collector.py
│   │   ├── data_go_kr_collector.py
│   │   ├── indicator_calculator.py
│   │   ├── orchestrator.py           # FeedOrchestrator — backfill/daily ETL 파이프라인 오케스트레이션
│   │   └── scheduler.py              # 날짜 범위 생성 (backfill vs daily 모드)
│   ├── report/
│   │   ├── __init__.py
│   │   └── generator.py              # ReportGenerator — 수집 리포트 생성
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py                   # DataSource Protocol, RateLimiter 기반 클래스
│   │   ├── dart.py                   # DARTSource — DART OpenAPI 소스 어댑터
│   │   └── data_go_kr.py             # DataGoKrSource — data.go.kr 주식시세 API 소스 어댑터
│   ├── transform/
│   │   ├── __init__.py
│   │   └── validate.py               # 4계층 데이터 검증 (transport/syntax/schema/business)
│   ├── __init__.py
│   ├── cli_output.py
│   ├── cli_scheduler.py
│   ├── config.py                     # FeedConfig — DataFeed 설정 관리 (API 키, 경로 등)
│   └── injector.py                   # FeedInjector — CSV 파일에서 데이터 수동 주입
├── gateway/
│   ├── __init__.py
│   ├── cache.py                      # ResponseCache — TTL 기반 응답 캐시
│   ├── data_provider.py              # GatewayDataProvider — 시세 조회 래퍼
│   ├── gateway.py                    # APIGateway — rate limit, 캐시, 이벤트 기반 주문
│   ├── queue.py                      # OrderQueue — 주문 큐 관리
│   ├── rate_limiter.py               # RateLimiter — 호출 빈도 제한
│   ├── stop_order.py                 # StopOrderManager — 스탑 주문 에뮬레이션 (KRX 대응)
│   └── stream_integration.py
├── instrument/
│   ├── __init__.py
│   ├── models.py                     # Instrument — 종목 메타데이터 (frozen dataclass)
│   └── service.py                    # InstrumentService — 전체 메모리 캐시 + SQLite
├── ipc/
│   ├── __init__.py
│   ├── client.py
│   ├── exceptions.py
│   ├── protocol.py
│   ├── registry.py
│   ├── requests.py
│   └── server.py
├── member/
│   ├── __init__.py
│   ├── auth.py                       # 토큰 생성, 복구 키, 인증 유틸리티
│   ├── auth_service.py
│   ├── errors.py
│   ├── models.py                     # Member 데이터 모델 (MemberType 등)
│   ├── recovery_key_manager.py
│   ├── scopes.py
│   ├── service.py                    # MemberService — 멤버 등록·인증·관리
│   └── token_manager.py
├── notification/
│   ├── __init__.py
│   ├── base.py                       # NotificationAdapter ABC, NotificationLevel
│   ├── service.py                    # NotificationService — 이벤트 구독, 라우팅, 필터링, 이력 저장
│   ├── telegram.py                   # TelegramAdapter — 텔레그램 봇 API 구현체
│   └── telegram_receiver.py          # TelegramReceiver — 텔레그램 명령 수신 (양방향)
├── report/
│   ├── __init__.py
│   ├── draft.py                      # ReportDraftGenerator — 백테스트 완료 시 초안 자동 생성 (equity curve 표준화 포함)
│   ├── feedback.py                   # PerformanceFeedback — Agent 피드백용 실전 성과 조회 (equity curve 생성)
│   ├── models.py                     # StrategyReport (get_equity_curve), ReportStatus (DRAFT 포함)
│   ├── store.py                      # ReportStore — 전략 리포트 저장/조회
│   └── validation.py
├── rule/
│   ├── __init__.py
│   ├── base.py                       # Rule ABC, RuleContext, RuleEvaluation, EvaluationResult
│   ├── config_update.py
│   ├── defaults.py
│   ├── engine.py                     # RuleEngine — 전역/전략별 룰 평가
│   ├── exceptions.py
│   ├── global_rules.py               # 전역 룰 정의
│   ├── manager.py
│   └── strategy_rules.py             # 전략별 룰 정의
├── strategy/
│   ├── __init__.py
│   ├── base.py                       # Strategy ABC, StrategyMeta, TradeHistoryView
│   ├── context.py                    # StrategyContext — 전략 실행 컨텍스트 (파일 접근, 로깅, 거래 이력)
│   ├── exceptions.py
│   ├── file_access.py
│   ├── indicators.py                 # IndicatorCalculator — pandas-ta 기반 기술 지표 계산 (130+종)
│   ├── loader.py                     # StrategyLoader — 전략 파일 동적 로드
│   ├── registry.py                   # StrategyRegistry — 전략 등록/관리
│   ├── snapshot.py                   # StrategySnapshot — 전략 파일 스냅샷 생성/정리
│   └── validator.py                  # StrategyValidator — AST 기반 정적 검증
├── trade/
│   ├── __init__.py
│   ├── daily_report.py
│   ├── fill_applier.py
│   ├── fill_outbox.py
│   ├── models.py                     # TradeRecord, PositionSnapshot, PerformanceMetrics
│   ├── order_tracker.py
│   ├── performance.py                # PerformanceCalculator — 성과 산출
│   ├── position.py                   # PositionTracker — 포지션 추적
│   ├── reconciler.py                 # PositionReconciler — 포지션 정합성 검증 및 자동 보정
│   ├── recorder.py                   # TradeRecorder — 거래 기록 (SQLite)
│   └── service.py                    # TradeService — 위 컴포넌트 조합
├── treasury/
│   ├── __init__.py
│   ├── exceptions.py
│   ├── manager.py
│   ├── models.py                     # TreasuryAllocation — 자금 할당 모델
│   └── treasury.py                   # Treasury — 자금 배분 및 한도 관리
├── update/
│   ├── __init__.py
│   ├── checker.py
│   └── executor.py
├── __init__.py
├── __main__.py                       # python -m ante 실행 지원
└── main.py                           # asyncio 엔트리포인트 (Composition Root)
```

## tests/ — 테스트

```
tests/
├── e2e/
│   ├── netguard/
│   └── strategies/
├── fixtures/
├── integration/
└── unit/                             # 단위 테스트 (pytest + pytest-asyncio)
    ├── cli/
    ├── contracts/
    ├── feed/                         # DataFeed 모듈 단위 테스트
    ├── ipc/
    ├── property/
    ├── specs/
    └── strategy/
```

## deploy/ — 서비스 배포

```
deploy/
├── ante.service                      # Linux systemd 유닛 파일
└── com.ante.plist                    # macOS launchd plist 파일
```

## strategies/ — 전략 템플릿과 예제

```
strategies/
├── _examples/                        # Agent 참고용 예제 전략
│   ├── ma_crossover.py               # 이동평균 크로스오버 예제
│   ├── rsi_mean_reversion.py         # RSI 평균회귀 예제
│   └── volume_breakout.py            # 거래량 돌파 예제
└── _template.py                      # 새 전략 작성용 최소 템플릿
```

## scripts/ — 설치·운영·문서 생성 스크립트

```
scripts/
├── check_comments.py
├── check_entry_ratchet.py
├── check_import_path.py              # 현재 worktree import sanity check
├── check_imports.py
├── check_lint_ratchet.py
├── check_prose_budget.py
├── check_review_scope.py
├── check_spec_code_blocks.py
├── check_test_shards.py
├── collect_autopilot_queue.py
├── comment_baseline.json
├── entry_ratchet_baseline.json
├── generate_cli_reference.py         # CLI 레퍼런스 문서 자동 생성 (Click introspection)
├── generate_db_schema.py             # DB 스키마 문서 자동 생성
├── generate_error_codes.py           # 에러 코드 문서 자동 생성
├── generate_ipc_commands.py          # IPC 명령 문서 자동 생성
├── generate_project_structure.py     # 프로젝트 구조 Agent INDEX 생성/check
├── import_baseline.json
├── install-service.sh                # OS 감지 후 systemd/launchd 서비스 설치
├── lint_baseline.json
├── render_e2e_records.py
├── scan_create_services_anti_pattern.py
├── spec_code_block_baseline.json
├── uninstall-service.sh              # 서비스 제거
├── update_test_shard_durations.py
└── verify-install.py                 # 설치 검증 스크립트
```

## docs/ — 설계 문서

```
docs/
├── architecture/                     # 시스템 아키텍처 문서 묶음
│   ├── generated/                    # 소스에서 생성된 문서
│   │   ├── db-schema.md              # SQLite 스키마 전체 목록
│   │   ├── error-codes.md            # 에러 코드와 예외 매핑 목록
│   │   ├── ipc-commands.md           # IPC 명령과 요청 모델 목록
│   │   └── project-structure.md      # 이 문서 — 프로젝트 디렉토리 구조
│   ├── module-map.md                 # 모듈 책임, 확장성, 배포 산출물
│   ├── README.md                     # 아키텍처 인덱스 + 기술 스택
│   └── system-diagram.md             # 시스템 구성도, 데이터/통신 흐름
├── decisions/                        # 설계 결정 이력 디렉토리
│   ├── D-001.md
│   ├── D-002.md
│   ├── D-003.md
│   ├── D-004.md
│   ├── D-005.md
│   ├── D-006.md
│   ├── D-007.md
│   ├── D-008.md
│   ├── D-009.md
│   ├── D-010.md
│   ├── D-011.md
│   ├── D-012.md
│   ├── D-013.md
│   ├── D-014.md
│   ├── D-015-default-deny-auth-gate.md
│   ├── D-016-canonical-exchange-vocabulary.md
│   ├── D-017-canonical-symbol-timeframe-vocabulary.md
│   ├── D-018-core-interface-cli-ipc.md
│   ├── D-019-review-gate-redesign.md
│   ├── D-020-tool-neutral-contribution-governance.md
│   ├── D-021-trust-pyramid-governance.md
│   └── README.md                     # 설계 결정 인덱스
├── references/                       # 외부 참조 문서
│   └── external-apis/
│       ├── dart-openapi.md
│       └── data-go-kr-stock-price-api.md
├── runbooks/                         # 운영 절차서
│   ├── archive/
│   │   ├── 07-member-invalid-role-cleanup.md
│   │   └── 08-legacy-invalid-approval-cleanup.md
│   ├── 00-issue-management.md        # 이슈 등록, 분류, 추적
│   ├── 01-development-process.md
│   ├── 02-agent-structure.md         # 에이전트 구조
│   ├── 03-git-workflow.md
│   ├── 04-ci-cd.md                   # CI/CD와 리뷰 게이트
│   ├── 05-testing.md
│   ├── 06-release.md                 # 릴리스 정책
│   └── README.md
└── specs/                            # 모듈별 세부 설계
    ├── account/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-data-model.md
    │   ├── 04-account-service.md
    │   ├── 05-eventbus-integration.md
    │   ├── 06-database-schema.md
    │   ├── 08-config-migration.md
    │   ├── 09-cli.md
    │   ├── 11-scope-out.md
    │   ├── 13-cross-module-notes.md
    │   ├── 14-account-id-contract.md
    │   ├── account.md
    │   └── README.md
    ├── api-gateway/
    │   └── api-gateway.md
    ├── approval/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-enums.md
    │   ├── 04-approval-request-model.md
    │   ├── 05-approval-types.md
    │   ├── 06-status-flow.md
    │   ├── 07-database-schema.md
    │   ├── 08-approval-service.md
    │   ├── 09-cli.md
    │   ├── 10-eventbus-integration.md
    │   ├── 11-notification-events.md
    │   ├── 12-cross-module-notes.md
    │   ├── approval.md
    │   └── README.md
    ├── audit/
    │   └── audit.md
    ├── backtest/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-cli-usage.md
    │   ├── 05-cross-module-notes.md
    │   ├── backtest.md
    │   └── README.md
    ├── bot/
    │   ├── 01-overview.md
    │   ├── 02-reference-implementations.md
    │   ├── 03-design-decisions.md
    │   ├── 04-eventbus-integration.md
    │   ├── 05-notification-events.md
    │   ├── 06-cli-usage.md
    │   ├── 07-testing.md
    │   ├── 08-cross-module-notes.md
    │   ├── bot.md
    │   └── README.md
    ├── broker-adapter/
    │   ├── 01-overview.md
    │   ├── 02-reference-implementations.md
    │   ├── 03-adapter-layer.md
    │   ├── 04-broker-adapter-interface.md
    │   ├── 05-broker-registry.md
    │   ├── 06-broker-presets.md
    │   ├── 07-kis-base-adapter.md
    │   ├── 08-kis-domestic-adapter.md
    │   ├── 09-kis-overseas-adapter.md
    │   ├── 10-commission-info.md
    │   ├── 11-order-flow.md
    │   ├── 12-test-broker-adapter.md
    │   ├── 13-setup-and-initialization.md
    │   ├── 14-cli.md
    │   ├── 15-reconciliation.md
    │   ├── 16-eventbus-integration.md
    │   ├── 17-notification-events.md
    │   ├── 18-fill-recovery.md
    │   ├── 19-scope-out.md
    │   ├── broker-adapter.md
    │   └── README.md
    ├── cli/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-commands.md
    │   ├── 04-agent-workflows.md
    │   ├── 06-cross-module-notes.md
    │   ├── cli.md
    │   └── README.md
    ├── config/
    │   ├── 01-overview.md
    │   ├── 02-reference-implementations.md
    │   ├── 03-design-decisions.md
    │   ├── 04-system-initialization.md
    │   ├── 05-broker-to-account-migration.md
    │   ├── 07-cross-module-notes.md
    │   ├── config.md
    │   └── README.md
    ├── contracts/
    │   ├── envelopes.md
    │   ├── error-taxonomy.md
    │   ├── offline-factory.md
    │   └── README.md
    ├── core/
    │   └── core.md
    ├── data-feed/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-collection-scope.md
    │   ├── 04-schema.md
    │   ├── 05-data-sources.md
    │   ├── 06-cli.md
    │   ├── 07-execution-modes.md
    │   ├── 08-resource-protection.md
    │   ├── 09-failure-recovery.md
    │   ├── 10-checkpoints-and-reports.md
    │   ├── 11-module-structure.md
    │   ├── 13-cross-module-notes.md
    │   ├── data-feed.md
    │   └── README.md
    ├── data-pipeline/
    │   ├── 01-overview.md
    │   ├── 02-write-ownership.md
    │   ├── 03-design-decisions.md
    │   ├── 04-dependencies.md
    │   ├── 05-datafeed-relationship.md
    │   ├── 07-cross-module-notes.md
    │   ├── data-pipeline.md
    │   └── README.md
    ├── eventbus/
    │   └── eventbus.md
    ├── instrument/
    │   └── instrument.md
    ├── ipc/
    │   └── ipc.md
    ├── logging/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-json-schema.md
    │   ├── 04-fingerprint.md
    │   ├── 05-handlers-and-rotation.md
    │   ├── 06-context-fields.md
    │   ├── 07-implementation.md
    │   ├── logging.md
    │   └── README.md
    ├── member/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-member-model.md
    │   ├── 04-database-schema.md
    │   ├── 05-member-service.md
    │   ├── 06-cli.md
    │   ├── 07-eventbus-integration.md
    │   ├── 08-module-impact.md
    │   ├── 09-notification-events.md
    │   ├── member.md
    │   └── README.md
    ├── notification/
    │   └── notification.md
    ├── report-store/
    │   └── report-store.md
    ├── rule-engine/
    │   ├── 01-overview.md
    │   ├── 02-reference-implementations.md
    │   ├── 03-two-layer-evaluation.md
    │   ├── 04-rule-interface.md
    │   ├── 05-rule-context.md
    │   ├── 06-rule-catalog.md
    │   ├── 07-rule-engine-core.md
    │   ├── 08-notification-events.md
    │   ├── 09-rule-management.md
    │   ├── 10-rule-engine-manager.md
    │   ├── 12-cli.md
    │   ├── 14-cross-module-notes.md
    │   ├── README.md
    │   └── rule-engine.md
    ├── strategy/
    │   ├── 01-overview.md
    │   ├── 02-reference-implementations.md
    │   ├── 03-01-strategy-interface.md
    │   ├── 03-02-signal-fields.md
    │   ├── 03-03-order-action-fields.md
    │   ├── 03-04-provider-and-views.md
    │   ├── 03-05-strategy-context.md
    │   ├── 03-06-indicator-calculator.md
    │   ├── 03-07-strategy-snapshot.md
    │   ├── 03-08-dynamic-loading.md
    │   ├── 03-09-strategy-validator.md
    │   ├── 03-10-strategy-registry.md
    │   ├── 03-11-registration-flow.md
    │   ├── 03-12-runtime-model.md
    │   ├── 03-13-bot-execution-flow.md
    │   ├── 03-14-performance-scoping.md
    │   ├── 03-15-backtest-relationship.md
    │   ├── 03-design-decisions.md
    │   ├── 04-examples.md
    │   ├── 05-testing.md
    │   ├── 07-cross-module-notes.md
    │   ├── README.md
    │   └── strategy.md
    ├── trade/
    │   ├── 01-overview.md
    │   ├── 02-reference-implementations.md
    │   ├── 03-01-trade-record.md
    │   ├── 03-02-trade-recorder.md
    │   ├── 03-03-position-history.md
    │   ├── 03-04-performance-tracker.md
    │   ├── 03-05-sqlite-schema.md
    │   ├── 03-06-trade-service.md
    │   ├── 03-07-position-reconciler.md
    │   ├── 03-08-fill-recovery.md
    │   ├── 03-design-decisions.md
    │   ├── 04-eventbus-integration.md
    │   ├── 05-cli-usage.md
    │   ├── 06-testing.md
    │   ├── 07-notification-events.md
    │   ├── 09-cross-module-notes.md
    │   ├── README.md
    │   └── trade.md
    ├── treasury/
    │   ├── 01-overview.md
    │   ├── 02-design-decisions.md
    │   ├── 03-treasury-model.md
    │   ├── 04-treasury-interface.md
    │   ├── 05-treasury-manager.md
    │   ├── 06-database-schema.md
    │   ├── 07-cli.md
    │   ├── 08-daily-asset-snapshots.md
    │   ├── 09-virtual-asset-sync.md
    │   ├── 11-cross-module-notes.md
    │   ├── README.md
    │   └── treasury.md
    └── README.md
```

## guide/ — 사용자·운용 가이드

```
guide/
├── assets/                           # 가이드 이미지·SVG
│   ├── concept-account-map.svg
│   ├── concept-order-flow.svg
│   ├── concept-strategy-lifecycle.svg
│   └── how-it-works.svg              # 시스템 구조 도식
├── agent.md                          # AI Agent 온보딩 가이드
├── cli.md                            # CLI 레퍼런스 (자동 생성)
├── concepts.md
├── getting-started.md                # 설치·초기 설정 가이드
├── migration.md
├── modules.md
├── security.md                       # 보안 가이드
└── strategy.md                       # 전략 개발 가이드
```
