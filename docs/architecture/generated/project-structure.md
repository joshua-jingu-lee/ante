# Ante 프로젝트 디렉토리 구조

> 역할: Agent용 프로젝트 구조 INDEX의 단일 SSOT입니다.
> 생성 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py`
> Check 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py --check`
> 생성 기준: 현재 Git 추적/비무시 파일 트리 (`git ls-files --cached --others --exclude-standard`)
> 마지막 생성 시점: 2026-05-26 (KST)

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
├── README.md                         # 프로젝트 개요
├── CLAUDE.md                         # Claude Code 호환 가이드
└── LICENSE                           # 라이선스
```

## src/ante/ — Python 백엔드

```
src/ante/
├── __main__.py                       # python -m ante 실행 지원
├── main.py                           # asyncio 엔트리포인트 (Composition Root)
├── core/
│   ├── database.py                   # Database — SQLite WAL 연결 관리
│   ├── log/                          # 시스템 로그 인프라 (JSONL 포맷, fingerprint)
│   │   ├── __init__.py
│   │   ├── _record_keys.py           # LogRecord 속성 / Ante 예약 키 단일 소스 (runtime probe)
│   │   ├── formatter.py              # JsonFormatter — JSONL 직렬화
│   │   ├── fingerprint.py            # compute_fingerprint() — 예외 dedup 키
│   │   ├── handlers.py               # DateNamedTimedRotatingFileHandler (KST 자정 no-rename 회전)
│   │   ├── safe_logger.py            # AnteLogger, install_safe_logger() (makeRecord 예약 키 정규화)
│   │   └── setup.py                  # setup_logging() stdout + JSONL 파일 핸들러 구성
│   ├── __init__.py
│   ├── registry.py
│   ├── time.py
│   ├── exchange.py
│   └── market_data_vocab.py
├── config/
│   ├── config.py                     # ConfigService — 설정 로딩 (system.toml + secrets.env)
│   ├── defaults.py                   # 기본 설정값
│   ├── dynamic.py                    # DynamicConfigService — DB 기반 런타임 설정
│   ├── exceptions.py
│   └── __init__.py
├── eventbus/
│   ├── bus.py                        # EventBus — asyncio.Queue 기반 발행/구독
│   ├── events.py                     # 전체 이벤트 dataclass 정의
│   ├── history.py                    # EventHistory — 이벤트 이력 추적
│   └── __init__.py
├── audit/
│   ├── logger.py                     # AuditLogger — 감사 로그 기록 (SQLite)
│   └── __init__.py
├── approval/
│   ├── models.py                     # ApprovalRequest, ApprovalStatus, ApprovalType
│   ├── service.py                    # ApprovalService — 결재 요청 관리 + 자동 실행
│   ├── __init__.py
│   ├── auto_approve.py
│   └── errors.py
├── instrument/
│   ├── models.py                     # Instrument — 종목 메타데이터 (frozen dataclass)
│   ├── service.py                    # InstrumentService — 전체 메모리 캐시 + SQLite
│   └── __init__.py
├── member/
│   ├── auth.py                       # 토큰 생성, 복구 키, 인증 유틸리티
│   ├── models.py                     # Member 데이터 모델 (MemberType 등)
│   ├── service.py                    # MemberService — 멤버 등록·인증·관리
│   ├── __init__.py
│   ├── auth_service.py
│   ├── errors.py
│   ├── recovery_key_manager.py
│   ├── token_manager.py
│   └── scopes.py
├── bot/
│   ├── bot.py                        # Bot — 봇 실행 루프, 전략 실행, 이벤트 발행
│   ├── config.py                     # BotConfig — 봇 설정 (exchange, 자금 한도 등)
│   ├── context_factory.py            # BotContextFactory — 봇 실행 컨텍스트 생성
│   ├── exceptions.py
│   ├── manager.py                    # BotManager — 봇 생명주기 관리
│   ├── signal_channel.py             # SignalChannel — JSON Lines 파이프 기반 양방향 시그널 채널
│   ├── signal_key.py                 # SignalKeyManager — 봇별 시그널 키 발급/관리
│   ├── providers/
│   │   ├── live.py                   # LiveProvider — 실전 봇 데이터 공급
│   │   ├── virtual.py                # VirtualProvider — 가상 실행 봇 데이터 공급
│   │   └── __init__.py
│   ├── __init__.py
│   ├── cold_path.py
│   └── info.py
├── strategy/
│   ├── base.py                       # Strategy ABC, StrategyMeta, TradeHistoryView
│   ├── context.py                    # StrategyContext — 전략 실행 컨텍스트 (파일 접근, 로깅, 거래 이력)
│   ├── exceptions.py
│   ├── indicators.py                 # IndicatorCalculator — pandas-ta 기반 기술 지표 계산 (130+종)
│   ├── snapshot.py                   # StrategySnapshot — 전략 파일 스냅샷 생성/정리
│   ├── loader.py                     # StrategyLoader — 전략 파일 동적 로드
│   ├── registry.py                   # StrategyRegistry — 전략 등록/관리
│   ├── validator.py                  # StrategyValidator — AST 기반 정적 검증
│   └── __init__.py
├── rule/
│   ├── base.py                       # Rule ABC, RuleContext, RuleEvaluation, EvaluationResult
│   ├── engine.py                     # RuleEngine — 전역/전략별 룰 평가
│   ├── exceptions.py
│   ├── global_rules.py               # 전역 룰 정의
│   ├── strategy_rules.py             # 전략별 룰 정의
│   ├── __init__.py
│   ├── manager.py
│   ├── defaults.py
│   └── config_update.py
├── treasury/
│   ├── models.py                     # TreasuryAllocation — 자금 할당 모델
│   ├── treasury.py                   # Treasury — 자금 배분 및 한도 관리
│   ├── exceptions.py
│   ├── __init__.py
│   └── manager.py
├── trade/
│   ├── models.py                     # TradeRecord, PositionSnapshot, PerformanceMetrics
│   ├── recorder.py                   # TradeRecorder — 거래 기록 (SQLite)
│   ├── position.py                   # PositionTracker — 포지션 추적
│   ├── performance.py                # PerformanceCalculator — 성과 산출
│   ├── reconciler.py                 # PositionReconciler — 포지션 정합성 검증 및 자동 보정
│   ├── service.py                    # TradeService — 위 컴포넌트 조합
│   ├── __init__.py
│   └── daily_report.py
├── broker/
│   ├── base.py                       # BrokerAdapter ABC
│   ├── models.py                     # CommissionInfo dataclass
│   ├── kis.py                        # KISAdapter — 한국투자증권 API 구현체
│   ├── kis_stream.py                 # KISStreamClient — KIS WebSocket 실시간 시세/체결 통보
│   ├── circuit_breaker.py            # CircuitBreaker — API 장애 차단
│   ├── error_codes.py                # KIS API 에러 코드 분류 (영구/일시)
│   ├── mock.py                       # MockBroker — 테스트/모의투자용 브로커 구현체
│   ├── order_registry.py             # OrderRegistry — 주문 상태 추적 (SQLite)
│   ├── exceptions.py
│   ├── __init__.py
│   ├── registry.py
│   ├── scheduler.py
│   └── test.py
├── gateway/
│   ├── gateway.py                    # APIGateway — rate limit, 캐시, 이벤트 기반 주문
│   ├── rate_limiter.py               # RateLimiter — 호출 빈도 제한
│   ├── cache.py                      # ResponseCache — TTL 기반 응답 캐시
│   ├── queue.py                      # OrderQueue — 주문 큐 관리
│   ├── data_provider.py              # GatewayDataProvider — 시세 조회 래퍼
│   ├── stop_order.py                 # StopOrderManager — 스탑 주문 에뮬레이션 (KRX 대응)
│   ├── __init__.py
│   └── stream_integration.py
├── data/
│   ├── collector.py                  # DataCollector — 실시간 시세 수집 → Parquet
│   ├── normalizer.py                 # BaseNormalizer ABC + KIS/Yahoo/Default Normalizer, DataNormalizer 파사드
│   ├── retention.py                  # DataRetention — 보존 정책, 외부 이관
│   ├── schemas.py                    # OHLCV 등 데이터 스키마 정의
│   ├── store.py                      # DataStore — Parquet 읽기/쓰기
│   ├── __init__.py
│   └── datasets.py
├── feed/                             # DataFeed — 외부 데이터 수집 파이프라인
│   ├── cli.py                        # ante feed — DataFeed CLI 커맨드 (init/status/inject/config)
│   ├── config.py                     # FeedConfig — DataFeed 설정 관리 (API 키, 경로 등)
│   ├── injector.py                   # FeedInjector — CSV 파일에서 데이터 수동 주입
│   ├── models/
│   │   ├── result.py                 # ValidationResult, CollectionResult — 수집 결과 모델
│   │   └── __init__.py
│   ├── pipeline/
│   │   ├── checkpoint.py             # Checkpoint — 체크포인트 저장 및 복원
│   │   ├── orchestrator.py           # FeedOrchestrator — backfill/daily ETL 파이프라인 오케스트레이션
│   │   ├── scheduler.py              # 날짜 범위 생성 (backfill vs daily 모드)
│   │   ├── __init__.py
│   │   ├── backfill_runner.py
│   │   ├── daily_runner.py
│   │   ├── dart_collector.py
│   │   ├── data_go_kr_collector.py
│   │   └── indicator_calculator.py
│   ├── report/
│   │   ├── generator.py              # ReportGenerator — 수집 리포트 생성
│   │   └── __init__.py
│   ├── sources/
│   │   ├── base.py                   # DataSource Protocol, RateLimiter 기반 클래스
│   │   ├── data_go_kr.py             # DataGoKrSource — data.go.kr 주식시세 API 소스 어댑터
│   │   ├── dart.py                   # DARTSource — DART OpenAPI 소스 어댑터
│   │   └── __init__.py
│   ├── transform/
│   │   ├── validate.py               # 4계층 데이터 검증 (transport/syntax/schema/business)
│   │   └── __init__.py
│   ├── __init__.py
│   ├── cli_output.py
│   └── cli_scheduler.py
├── backtest/
│   ├── context.py                    # BacktestContext — 백테스트 실행 환경
│   ├── data_provider.py              # BacktestDataProvider — Parquet 기반 시세 공급
│   ├── exceptions.py
│   ├── executor.py                   # BacktestExecutor — 전략 실행 루프
│   ├── metrics.py                    # calculate_metrics — 성과 지표 (Sharpe, MDD 등)
│   ├── result.py                     # BacktestResult, BacktestTrade — 결과 모델
│   ├── runner.py                     # BacktestRunner — subprocess 진입점
│   ├── service.py                    # BacktestService — 메인 프로세스 인터페이스
│   ├── __init__.py
│   ├── config.py
│   └── run_store.py
├── report/
│   ├── draft.py                      # ReportDraftGenerator — 백테스트 완료 시 초안 자동 생성 (equity curve 표준화 포함)
│   ├── feedback.py                   # PerformanceFeedback — Agent 피드백용 실전 성과 조회 (equity curve 생성)
│   ├── models.py                     # StrategyReport (get_equity_curve), ReportStatus (DRAFT 포함)
│   ├── store.py                      # ReportStore — 전략 리포트 저장/조회
│   ├── __init__.py
│   └── validation.py
├── notification/
│   ├── base.py                       # NotificationAdapter ABC, NotificationLevel
│   ├── telegram.py                   # TelegramAdapter — 텔레그램 봇 API 구현체
│   ├── telegram_receiver.py          # TelegramReceiver — 텔레그램 명령 수신 (양방향)
│   ├── service.py                    # NotificationService — 이벤트 구독, 라우팅, 필터링, 이력 저장
│   └── __init__.py
├── cli/
│   ├── main.py                       # CLI 루트 그룹 (ante 커맨드)
│   ├── middleware.py                 # 인증 미들웨어 (require_auth, require_scope)
│   ├── formatter.py                  # OutputFormatter — table/json 출력
│   ├── commands/
│   │   ├── _password.py              # generate_password() — CLI용 랜덤 패스워드 유틸
│   │   ├── approval.py               # ante approval approve/audit-types/cancel/cancel-invalid/info/list/reject/reopen/request/review
│   │   ├── audit.py                  # ante audit — 감사 로그 조회
│   │   ├── backtest.py               # ante backtest history/run
│   │   ├── bot.py                    # ante bot create/info/list/positions/remove/signal-key/start/stop/status
│   │   ├── broker.py                 # ante broker balance/positions/reconcile/status
│   │   ├── config.py                 # ante config get/history/set
│   │   ├── data.py                   # ante data list/schema/storage/validate
│   │   ├── init.py                   # ante init — 비대화형 최소 초기 설정 (master + 테스트 계좌)
│   │   ├── instrument.py             # ante instrument list/search/sync/import (--listed-only)
│   │   ├── member.py                 # ante member register/list/info/suspend/revoke/set-emoji/... (bootstrap은 init으로 통합)
│   │   ├── notification.py           # 알림 CLI (public leaf 없음 — 텔레그램 이관)
│   │   ├── report.py                 # ante report schema/submit/list/performance/view
│   │   ├── rule.py                   # ante rule info/list
│   │   ├── signal.py                 # ante signal — 외부 시그널 채널 관리
│   │   ├── strategy.py               # ante strategy validate/submit/list/info/performance
│   │   ├── system.py                 # ante system clear-halt/halt/start/status/stop
│   │   ├── trade.py                  # ante trade info/list
│   │   ├── treasury.py               # ante treasury allocate/deallocate/snapshot/status
│   │   ├── __init__.py
│   │   ├── account.py
│   │   ├── ipc_helpers.py
│   │   └── update.py
│   ├── __init__.py
│   ├── cold_path.py
│   └── _validators.py
├── account/
│   ├── __init__.py
│   ├── crypto.py
│   ├── errors.py
│   ├── models.py
│   ├── presets.py
│   ├── scoping.py
│   ├── service.py
│   └── timezone.py
├── db/
│   ├── versions/
│   │   ├── __init__.py
│   │   ├── v001_baseline.py
│   │   ├── v002_parquet_migration.py
│   │   ├── v003_broker_config.py
│   │   └── v004_strategy_status_simplify.py
│   ├── __init__.py
│   ├── backup.py
│   └── migrations.py
├── ipc/
│   ├── __init__.py
│   ├── client.py
│   ├── exceptions.py
│   ├── protocol.py
│   ├── registry.py
│   └── server.py
├── update/
│   ├── __init__.py
│   ├── checker.py
│   └── executor.py
├── __init__.py
└── contracts/
    ├── __init__.py
    ├── vocab.py
    ├── error_registry.py
    ├── errors.py
    ├── helpers.py
    └── cli_registry.py
```

## tests/ — 테스트

```
tests/
├── conftest.py                       # 공통 pytest fixture
├── fixtures/
│   └── __init__.py
├── unit/                             # 단위 테스트 (pytest + pytest-asyncio)
│   ├── test_account_runtime_init_order.py # _init_account의 mark_runtime_started 호출 순서 (#1144)
│   ├── test_approval.py
│   ├── test_audit.py                 # 감사 로그(AuditLogger) 테스트
│   ├── test_backtest.py
│   ├── test_backtest_metrics.py      # 성과 지표 (Sharpe, MDD, PnL 추정)
│   ├── test_backtest_progress.py     # 백테스트 진행률 콜백
│   ├── test_bot_create_params.py     # bot create --param 파라미터 오버라이드
│   ├── test_bot_providers.py
│   ├── test_bot_restart.py
│   ├── test_bot_stop_release.py
│   ├── test_bot.py
│   ├── test_broker.py
│   ├── test_cli_auth.py
│   ├── test_cli_config.py
│   ├── test_cli_init.py              # ante init (비대화형) CLI 테스트
│   ├── test_cli_live.py
│   ├── test_cli_password.py          # generate_password() 유틸 테스트
│   ├── test_cli.py
│   ├── test_commission.py
│   ├── test_config.py
│   ├── test_config_path.py           # Config 경로 탐색 및 ante init 테스트
│   ├── test_data_pipeline.py
│   ├── test_database.py
│   ├── test_dynamic_config.py
│   ├── test_event_history.py
│   ├── test_eventbus.py
│   ├── test_equity_curve.py          # 자산 곡선 기능 (표준화, 리포트 추출, 피드백 생성)
│   ├── test_external_signal_subscription.py # 외부 시그널 구독
│   ├── test_external_signals.py      # 외부 시그널 처리
│   ├── test_gateway_stop_routing.py  # Gateway 스탑 주문 라우팅
│   ├── test_gateway.py
│   ├── test_instrument_cache_ttl.py  # InstrumentService 캐시 TTL
│   ├── test_instrument_import.py     # 종목 데이터 CSV/JSON import
│   ├── test_instrument_sync.py       # KIS API 종목 동기화
│   ├── test_instrument.py
│   ├── test_ipc_error_code_mapping.py # IPCServer가 예외 code 속성을 안정 코드로 노출 (#1144)
│   ├── test_kis_error_handling.py
│   ├── test_kis_stream.py            # KIS WebSocket 스트리밍
│   ├── test_listed_only.py           # --listed-only 필터
│   ├── test_member.py
│   ├── test_mock_broker.py           # MockBroker 테스트
│   ├── test_notification_dedup.py    # 알림 중복 억제
│   ├── test_notification.py
│   ├── test_parquet_validation.py    # Parquet 파일 검증
│   ├── test_performance_summary.py   # 일간/월간 성과 요약
│   ├── test_reconciler.py            # PositionReconciler 테스트
│   ├── test_report_draft.py          # 백테스트 초안 자동 생성
│   ├── test_report.py
│   ├── test_rule.py
│   ├── test_signal_channel.py        # SignalChannel 파이프 통신
│   ├── test_signal_key.py            # 시그널 키 발급/관리
│   ├── test_stop_order.py            # 스탑 주문 에뮬레이션
│   ├── test_indicators.py            # TA-Lib 기술 지표 계산기
│   ├── test_normalizer_classes.py    # BaseNormalizer ABC + 소스별 Normalizer
│   ├── test_rule_modify.py           # 주문 정정 룰 검증
│   ├── test_strategy.py
│   ├── test_strategy_snapshot.py     # 전략 파일 스냅샷
│   ├── test_telegram_receiver.py
│   ├── test_token_expiry.py          # API 토큰 만료 정책
│   ├── test_trade.py
│   ├── test_trade_history_view.py    # TradeHistoryView ABC
│   ├── test_treasury_sync.py
│   ├── test_treasury.py
│   ├── test_bot_guard.py             # 봇 런타임 가드
│   ├── test_dynamic_log_level.py     # 동적 로그 레벨
│   ├── test_config_audit.py          # 설정 감사
│   ├── feed/                         # DataFeed 모듈 단위 테스트
│   │   ├── test_checkpoint.py        # 체크포인트 저장/복원
│   │   ├── test_cli_init.py          # ante feed CLI 초기화
│   │   ├── test_cli_run.py           # ante feed run CLI 테스트
│   │   ├── test_cli_status.py        # ante feed status CLI 테스트
│   │   ├── test_config.py            # FeedConfig 설정 관리
│   │   ├── test_dart.py              # DART 소스 어댑터
│   │   ├── test_data_go_kr.py        # data.go.kr 소스 어댑터
│   │   ├── test_injector.py          # FeedInjector 데이터 주입
│   │   ├── test_orchestrator.py      # FeedOrchestrator ETL 파이프라인
│   │   ├── test_report.py            # 수집 리포트 생성
│   │   ├── test_scheduler.py         # 날짜 범위 생성
│   │   ├── test_validate.py          # 4계층 데이터 검증
│   │   ├── __init__.py
│   │   ├── test_dart_collector.py
│   │   ├── test_cli_backfill_date_validation.py
│   │   ├── test_cli_config_set.py
│   │   ├── test_backfill_since_clean_reject.py
│   │   └── test_cli_backfill_until_removed.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── test_version.py
│   │   ├── test_authenticated_group.py
│   │   ├── test_auth_format_json.py
│   │   ├── test_bot_create_exit_code.py
│   │   ├── test_broker_missing_account.py
│   │   ├── test_usage_error_json.py
│   │   └── test_instrument_exchange_validation.py
│   ├── ipc/
│   │   ├── __init__.py
│   │   ├── test_protocol.py
│   │   ├── test_registry.py
│   │   ├── test_server_client.py
│   │   └── test_service_registry.py
│   ├── specs/
│   │   ├── __init__.py
│   │   ├── test_cold_path_terminology.py
│   │   └── test_virtual_mode_terminology.py
│   ├── __init__.py
│   ├── test_account.py
│   ├── test_account_cli.py
│   ├── test_account_crypto.py
│   ├── test_account_delete_events.py
│   ├── test_account_immutable_fields.py
│   ├── test_account_scoping.py
│   ├── test_approval_executors.py
│   ├── test_approval_strategy_adopt_validator.py
│   ├── test_approval_strategy_lifecycle.py
│   ├── test_auto_approve.py
│   ├── test_backtest_complete_event.py
│   ├── test_backtest_config.py
│   ├── test_backtest_run_store.py
│   ├── test_backup.py
│   ├── test_bot_account_status.py
│   ├── test_bot_cold_path.py
│   ├── test_bot_delete_budget.py
│   ├── test_bot_delete_positions.py
│   ├── test_bot_manager_methods.py
│   ├── test_bot_rule_init.py
│   ├── test_bot_timeout_error.py
│   ├── test_broker_adapter_split.py
│   ├── test_broker_reconcile_offline.py
│   ├── test_broker_type_switch.py
│   ├── test_cache.py
│   ├── test_cli_account_integration.py
│   ├── test_cli_approval_format_option.py
│   ├── test_cli_backtest_date_validation.py
│   ├── test_cli_backtest_report.py
│   ├── test_cli_bot_treasury_ipc.py
│   ├── test_cli_config_approval_broker_ipc.py
│   ├── test_cli_config_dir_propagation.py
│   ├── test_cli_format_option.py
│   ├── test_cli_ipc_commands.py
│   ├── test_cli_main_db_path.py
│   ├── test_cli_member_non_interactive.py
│   ├── test_cli_resolve_token.py
│   ├── test_cli_strategy.py
│   ├── test_cli_system.py
│   ├── test_cli_system_status.py
│   ├── test_cli_treasury_snapshot.py
│   ├── test_cli_update.py
│   ├── test_config_defaults_seed.py
│   ├── test_daily_report.py
│   ├── test_daily_snapshot.py
│   ├── test_disk_space_check.py
│   ├── test_draft_upsert.py
│   ├── test_eventbus_account_events.py
│   ├── test_generate_cli_reference.py
│   ├── test_generate_db_schema.py
│   ├── test_is_paper_migration.py
│   ├── test_kis_websocket_url.py
│   ├── test_log_fingerprint.py
│   ├── test_log_formatter.py
│   ├── test_log_handlers.py
│   ├── test_log_safe_logger.py
│   ├── test_log_setup.py
│   ├── test_main_init_notification.py
│   ├── test_main_shutdown_ordering.py
│   ├── test_main_startup_ordering.py
│   ├── test_migrations.py
│   ├── test_module_notification_events.py
│   ├── test_parquet_exchange.py
│   ├── test_password_change_notification.py
│   ├── test_password_token_invalidation.py
│   ├── test_price_simulator.py
│   ├── test_reconcile_scheduler.py
│   ├── test_recovery_auth_notification.py
│   ├── test_runtime_paths.py
│   ├── test_strategy_notification.py
│   ├── test_strategy_submit.py
│   ├── test_stream_integration.py
│   ├── test_telegram_approval.py
│   ├── test_test_broker.py
│   ├── test_trade_exchange_column.py
│   ├── test_trade_id_fk.py
│   ├── test_trade_id_uuid_parsing.py
│   ├── test_treasury_manager.py
│   ├── test_update.py
│   ├── test_update_rollback.py
│   ├── test_update_snapshot.py
│   ├── test_update_startup_check.py
│   ├── test_check_import_path.py
│   ├── test_approval_invalid_type.py
│   ├── test_approval_invalid_type_approve.py
│   ├── test_approval_invalid_type_cleanup.py
│   ├── test_bot_manager_modify_subscription.py
│   ├── test_bot_manager_stop_subscription.py
│   ├── test_bot_manager_update_bot_atomicity.py
│   ├── test_bot_manager_update_budget.py
│   ├── test_bot_on_order_update_stop_events.py
│   ├── test_bot_publish_actions_modify.py
│   ├── test_cli_approval_invalid_type_cleanup.py
│   ├── test_cli_approval_list_filters.py
│   ├── test_cli_dependency_isolation.py
│   ├── test_cli_report_list_filters.py
│   ├── test_cli_report_submit_invariant.py
│   ├── test_cli_strategy_list_invalid_status.py
│   ├── test_format_utc.py
│   ├── test_gateway_cancel_failed.py
│   ├── test_gateway_modify.py
│   ├── test_ipc_approval_cancel_invalid.py
│   ├── test_kis_error_codes_igw00022.py
│   ├── test_kis_handle_response_business_error.py
│   ├── test_member_scope_drift.py
│   ├── test_member_service.py
│   ├── test_member_service_master_guard.py
│   ├── test_rule_defaults.py
│   ├── test_rule_engine_modify.py
│   ├── test_signal_channel_modify.py
│   ├── test_signal_channel_stop_events.py
│   ├── test_stop_order_events_account_id.py
│   ├── test_stop_order_manager_account_propagation.py
│   ├── test_strategy_report_invariant.py
│   ├── test_treasury_buy_stop_no_reserve.py
│   ├── test_treasury_set_balance_invariant.py
│   ├── test_treasury_transaction_vocabulary.py
│   ├── test_virtual_provider_stop_guard.py
│   ├── test_cli_approval_expires_in.py
│   ├── test_cli_approval_params_shape.py
│   ├── test_cli_date_validation.py
│   ├── test_cli_instrument_import_exit.py
│   ├── test_cli_missing_resource_exit.py
│   ├── test_cli_pagination_validation.py
│   ├── test_cli_treasury_amount_validation.py
│   ├── test_cli_member_master_only.py
│   ├── test_backtest_exchange_plumbing.py
│   ├── test_backtest_programmatic_vocab_validation.py
│   ├── test_cli_account_id_construction_lifecycle.py
│   ├── test_cli_account_id_invalid_contract.py
│   ├── test_cli_backtest_exchange_validation.py
│   ├── test_cli_backtest_symbol_timeframe_validation.py
│   ├── test_cli_data_validate_symbol_timeframe_validation.py
│   ├── test_cli_e_bucket_mutating_ipc_account_id.py
│   ├── test_cli_feed_inject_symbol_timeframe_validation.py
│   ├── test_cli_inverted_date_range.py
│   ├── test_cli_report_performance_period_options.py
│   ├── test_core_exchange_vocabulary.py
│   ├── test_data_collector_ingress_validation.py
│   ├── test_exchange_vocabulary_contract.py
│   ├── test_market_data_vocab.py
│   ├── test_store_path_safety.py
│   ├── strategy/
│   │   └── __init__.py
│   ├── test_cli_notification_hidden.py
│   ├── test_cli_signal_connect.py
│   ├── test_bot_info.py
│   ├── test_cli_bot_lifecycle.py
│   ├── test_ipc_bot_lifecycle.py
│   ├── test_cli_init_secret_leak.py
│   ├── test_cli_account_crypto_error.py
│   ├── test_cli_account_reserve_buffer_validation.py
│   ├── test_cli_validators.py
│   ├── test_cli_account_invalid_id_ingress.py
│   ├── test_cli_treasury_account_not_found.py
│   ├── test_cli_rule_account_not_found.py
│   ├── test_cli_broker_account_not_found.py
│   ├── test_cli_init_no_web_section.py
│   ├── test_cli_backtest_run_json_single_document.py
│   ├── test_cli_fresh_init_read_contract.py
│   ├── test_cli_ipc_click_exception_json_envelope.py
│   ├── test_cli_report_approval_db_cleanup.py
│   ├── test_cli_strategy_submit_meta_shape.py
│   ├── test_cli_system_start_json_stdout.py
│   ├── test_cli_treasury_read_account_not_found.py
│   ├── test_bot_lifecycle_state_conflict.py
│   ├── test_bot_create_signal_key_auto.py
│   ├── test_cli_bot_signal_key_rotate_external_gate.py
│   ├── test_cli_error_code_naming_sweep.py
│   ├── test_cli_envelope_typed_codes_group_a_sweep.py
│   ├── test_cli_approval_args_key_alignment.py
│   ├── test_cli_bot_create_active_account_cleanup.py
│   ├── test_cli_group_p_missing_resource_sweep.py
│   ├── test_cli_group_q_state_conflict_sweep.py
│   ├── test_cli_group_r_member_duplicate_validation_sweep.py
│   ├── test_cli_group_s_treasury_typed_reject.py
│   ├── test_ipc_treasury_allocate_missing_bot.py
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── helpers.py
│   │   ├── test_helpers.py
│   │   ├── test_error_helpers.py
│   │   ├── error_drift_allowlist.yaml
│   │   ├── test_auth_middleware_code_policy.py
│   │   ├── test_error_drift.py
│   │   ├── test_cli_registry_leaf_coverage.py
│   │   ├── test_cli_registry_shell.py
│   │   └── test_cli_registry_auth_drift.py
│   ├── test_account_cli_ipc_error_equivalence.py
│   ├── test_member_cli_ipc_error_equivalence.py
│   ├── test_approval_cli_ipc_error_equivalence.py
│   ├── test_bot_cli_ipc_error_equivalence.py
│   ├── test_treasury_cli_ipc_error_equivalence.py
│   ├── test_broker_cli_ipc_error_equivalence.py
│   ├── test_broker_external_code_separation.py
│   ├── test_config_cli_ipc_error_equivalence.py
│   ├── test_rule_cli_ipc_error_equivalence.py
│   └── test_strategy_cli_ipc_error_equivalence.py
└── __init__.py
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
├── _template.py                      # 새 전략 작성용 최소 템플릿
└── _examples/                        # Agent 참고용 예제 전략
    ├── ma_crossover.py               # 이동평균 크로스오버 예제
    ├── rsi_mean_reversion.py         # RSI 평균회귀 예제
    └── volume_breakout.py            # 거래량 돌파 예제
```

## scripts/ — 설치·운영·문서 생성 스크립트

```
scripts/
├── generate_cli_reference.py         # CLI 레퍼런스 문서 자동 생성 (Click introspection)
├── install-service.sh                # OS 감지 후 systemd/launchd 서비스 설치
├── uninstall-service.sh              # 서비스 제거
├── verify-install.py                 # 설치 검증 스크립트
├── ai_review.py
├── generate_db_schema.py             # DB 스키마 문서 자동 생성
├── generate_project_structure.py     # 프로젝트 구조 Agent INDEX 생성/check
├── run_ai_review.sh
├── setup_actions_runners.sh
└── check_import_path.py              # 현재 worktree import sanity check
```

## docs/ — 설계 문서

```
docs/
├── architecture/                     # 시스템 아키텍처 문서 묶음
│   ├── README.md                     # 아키텍처 인덱스 + 기술 스택
│   ├── system-diagram.md             # 시스템 구성도, 데이터/통신 흐름
│   ├── module-map.md                 # 모듈 책임, 확장성, 배포 산출물
│   └── generated/                    # 소스에서 생성된 문서
│       ├── db-schema.md              # SQLite 스키마 전체 목록
│       └── project-structure.md      # 이 문서 — 프로젝트 디렉토리 구조
├── decisions/                        # 설계 결정 이력 디렉토리
│   ├── README.md                     # 설계 결정 인덱스
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
│   └── D-018-core-interface-cli-ipc.md
├── references/                       # 외부 참조 문서
│   └── external-apis/
│       ├── dart-openapi.md
│       ├── data-go-kr-stock-price-api.md
│       └── README.md
├── runbooks/                         # 운영 절차서
│   ├── 00-issue-management.md        # 이슈 등록, 분류, 추적
│   ├── 01-development-process.md
│   ├── 02-agent-structure.md         # 에이전트 구조
│   ├── 03-git-workflow.md
│   ├── 04-ci-cd.md                   # CI/CD와 리뷰 게이트
│   ├── 05-testing.md
│   ├── 06-release.md                 # 릴리스 정책
│   ├── README.md
│   ├── 07-member-invalid-role-cleanup.md
│   └── 08-legacy-invalid-approval-cleanup.md
├── specs/                            # 모듈별 세부 설계
│   ├── README.md
│   ├── account/
│   │   ├── README.md
│   │   ├── account.md
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-data-model.md
│   │   ├── 04-account-service.md
│   │   ├── 05-eventbus-integration.md
│   │   ├── 06-database-schema.md
│   │   ├── 07-account-layout-v1.md
│   │   ├── 08-config-migration.md
│   │   ├── 09-cli.md
│   │   ├── 11-scope-out.md
│   │   ├── 13-cross-module-notes.md
│   │   └── 14-account-id-contract.md
│   ├── approval/
│   │   ├── README.md
│   │   ├── approval.md
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-enums.md
│   │   ├── 04-approval-request-model.md
│   │   ├── 05-approval-types.md
│   │   ├── 06-status-flow.md
│   │   ├── 07-database-schema.md
│   │   ├── 08-approval-service.md
│   │   ├── 09-cli.md
│   │   ├── 10-eventbus-integration.md
│   │   ├── 11-notification-events.md
│   │   └── 12-cross-module-notes.md
│   ├── api-gateway/
│   │   └── api-gateway.md
│   ├── audit/
│   │   └── audit.md
│   ├── backtest/
│   │   ├── README.md
│   │   ├── backtest.md
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-cli-usage.md
│   │   └── 05-cross-module-notes.md
│   ├── bot/
│   │   ├── README.md
│   │   ├── bot.md
│   │   ├── 01-overview.md
│   │   ├── 02-reference-implementations.md
│   │   ├── 03-design-decisions.md
│   │   ├── 04-eventbus-integration.md
│   │   ├── 05-notification-events.md
│   │   ├── 06-cli-usage.md
│   │   ├── 07-testing.md
│   │   └── 08-cross-module-notes.md
│   ├── broker-adapter/
│   │   ├── README.md
│   │   ├── broker-adapter.md
│   │   ├── 01-overview.md
│   │   ├── 02-reference-implementations.md
│   │   ├── 03-adapter-layer.md
│   │   ├── 04-broker-adapter-interface.md
│   │   ├── 05-broker-registry.md
│   │   ├── 06-broker-presets.md
│   │   ├── 07-kis-base-adapter.md
│   │   ├── 08-kis-domestic-adapter.md
│   │   ├── 09-kis-overseas-adapter.md
│   │   ├── 10-commission-info.md
│   │   ├── 11-order-flow.md
│   │   ├── 12-test-broker-adapter.md
│   │   ├── 13-setup-and-initialization.md
│   │   ├── 14-cli.md
│   │   ├── 15-reconciliation.md
│   │   ├── 16-eventbus-integration.md
│   │   ├── 17-notification-events.md
│   │   └── 19-scope-out.md
│   ├── cli/
│   │   ├── README.md
│   │   ├── cli.md
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-commands.md
│   │   ├── 04-agent-workflows.md
│   │   └── 06-cross-module-notes.md
│   ├── config/
│   │   ├── README.md
│   │   ├── config.md
│   │   ├── 01-overview.md
│   │   ├── 02-reference-implementations.md
│   │   ├── 03-design-decisions.md
│   │   ├── 04-system-initialization.md
│   │   ├── 05-broker-to-account-migration.md
│   │   └── 07-cross-module-notes.md
│   ├── core/
│   │   └── core.md
│   ├── data-feed/
│   │   ├── README.md
│   │   ├── data-feed.md
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-collection-scope.md
│   │   ├── 04-schema.md
│   │   ├── 05-data-sources.md
│   │   ├── 06-cli.md
│   │   ├── 07-execution-modes.md
│   │   ├── 08-resource-protection.md
│   │   ├── 09-failure-recovery.md
│   │   ├── 10-checkpoints-and-reports.md
│   │   ├── 11-module-structure.md
│   │   └── 13-cross-module-notes.md
│   ├── data-pipeline/
│   │   ├── README.md
│   │   ├── data-pipeline.md
│   │   ├── 01-overview.md
│   │   ├── 02-write-ownership.md
│   │   ├── 03-design-decisions.md
│   │   ├── 04-dependencies.md
│   │   ├── 05-datafeed-relationship.md
│   │   └── 07-cross-module-notes.md
│   ├── eventbus/
│   │   └── eventbus.md
│   ├── instrument/
│   │   └── instrument.md
│   ├── ipc/
│   │   └── ipc.md
│   ├── member/
│   │   ├── README.md
│   │   ├── member.md
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-member-model.md
│   │   ├── 04-database-schema.md
│   │   ├── 05-member-service.md
│   │   ├── 06-cli.md
│   │   ├── 07-eventbus-integration.md
│   │   ├── 08-module-impact.md
│   │   └── 09-notification-events.md
│   ├── notification/
│   │   └── notification.md
│   ├── report-store/
│   │   └── report-store.md
│   ├── rule-engine/
│   │   ├── README.md
│   │   ├── rule-engine.md
│   │   ├── 01-overview.md
│   │   ├── 02-reference-implementations.md
│   │   ├── 03-two-layer-evaluation.md
│   │   ├── 04-rule-interface.md
│   │   ├── 05-rule-context.md
│   │   ├── 06-rule-catalog.md
│   │   ├── 07-rule-engine-core.md
│   │   ├── 08-notification-events.md
│   │   ├── 09-rule-management.md
│   │   ├── 10-rule-engine-manager.md
│   │   ├── 12-cli.md
│   │   └── 14-cross-module-notes.md
│   ├── strategy/
│   │   ├── README.md
│   │   ├── strategy.md
│   │   ├── 01-overview.md
│   │   ├── 02-reference-implementations.md
│   │   ├── 03-01-strategy-interface.md
│   │   ├── 03-02-signal-fields.md
│   │   ├── 03-03-order-action-fields.md
│   │   ├── 03-04-provider-and-views.md
│   │   ├── 03-05-strategy-context.md
│   │   ├── 03-06-indicator-calculator.md
│   │   ├── 03-07-strategy-snapshot.md
│   │   ├── 03-08-dynamic-loading.md
│   │   ├── 03-09-strategy-validator.md
│   │   ├── 03-10-strategy-registry.md
│   │   ├── 03-11-registration-flow.md
│   │   ├── 03-12-runtime-model.md
│   │   ├── 03-13-bot-execution-flow.md
│   │   ├── 03-14-performance-scoping.md
│   │   ├── 03-15-backtest-relationship.md
│   │   ├── 03-design-decisions.md
│   │   ├── 04-examples.md
│   │   ├── 05-testing.md
│   │   └── 07-cross-module-notes.md
│   ├── trade/
│   │   ├── README.md
│   │   ├── trade.md
│   │   ├── 01-overview.md
│   │   ├── 02-reference-implementations.md
│   │   ├── 03-01-trade-record.md
│   │   ├── 03-02-trade-recorder.md
│   │   ├── 03-03-position-history.md
│   │   ├── 03-04-performance-tracker.md
│   │   ├── 03-05-sqlite-schema.md
│   │   ├── 03-06-trade-service.md
│   │   ├── 03-07-position-reconciler.md
│   │   ├── 03-design-decisions.md
│   │   ├── 04-eventbus-integration.md
│   │   ├── 05-cli-usage.md
│   │   ├── 06-testing.md
│   │   ├── 07-notification-events.md
│   │   └── 09-cross-module-notes.md
│   ├── treasury/
│   │   ├── README.md
│   │   ├── treasury.md
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-treasury-model.md
│   │   ├── 04-treasury-interface.md
│   │   ├── 05-treasury-manager.md
│   │   ├── 06-database-schema.md
│   │   ├── 07-cli.md
│   │   ├── 08-daily-asset-snapshots.md
│   │   ├── 09-virtual-asset-sync.md
│   │   └── 11-cross-module-notes.md
│   ├── logging/
│   │   ├── 01-overview.md
│   │   ├── 02-design-decisions.md
│   │   ├── 03-json-schema.md
│   │   ├── 04-fingerprint.md
│   │   ├── 05-handlers-and-rotation.md
│   │   ├── 06-context-fields.md
│   │   ├── 07-implementation.md
│   │   ├── logging.md
│   │   └── README.md
│   └── contracts/
│       ├── envelopes.md
│       ├── README.md
│       └── error-taxonomy.md
├── temp/                             # 임시 작업 문서
│   └── 05-issue-processing-process-map.md
└── superpowers/
    └── specs/
        └── 2026-04-17-staging-environment-design.md
```

## guide/ — 사용자·운용 가이드

```
guide/
├── agent.md                          # AI Agent 온보딩 가이드
├── cli.md                            # CLI 레퍼런스 (자동 생성)
├── getting-started.md                # 설치·초기 설정 가이드
├── security.md                       # 보안 가이드
├── strategy.md                       # 전략 개발 가이드
└── assets/                           # 가이드 이미지·SVG
    └── how-it-works.svg              # 시스템 구조 도식
```
