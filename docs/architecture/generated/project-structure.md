# Ante 프로젝트 디렉토리 구조

> 이 문서는 실제 소스 트리에서 생성된 문서입니다.
> 새 모듈/파일 추가 시 이 문서도 함께 최신화해 주세요.
>
> 마지막 갱신: 2026-03-25

## 최상위 구조

```
ante/
├── src/ante/            # Python 백엔드 패키지
├── tests/               # 단위·통합·E2E 테스트
├── frontend/            # React 대시보드 (Vite + TypeScript)
├── guide/               # 사용자·운용 가이드 문서
├── docs/                # 설계 문서
├── deploy/              # 서비스 배포 파일 (systemd, launchd)
├── scripts/             # 설치·운영·문서 생성 스크립트
├── .agent/              # 에이전트 정의/명령/스킬
├── .claude/             # Claude Code 설정 + .agent 호환 링크
├── Dockerfile           # 프로덕션 Docker 이미지
├── Dockerfile.qa        # QA 테스트 Docker 이미지
├── docker-compose.yml        # 프로덕션 Docker Compose (ante-logs named volume 포함)
├── docker-compose.qa.yml     # QA 테스트용 Docker Compose
├── docker-compose.staging.yml # Staging override (JSONL 로그 bind mount, ANTE_ENV/ANTE_LOG_JSONL)
├── AGENTS.md            # 개발 Agent 마스터 가이드
└── CHANGELOG.md         # 변경 이력
```

## src/ante/ — Python 백엔드

```
src/ante/
├── __main__.py                  # python -m ante 실행 지원
├── main.py                      # asyncio 엔트리포인트 (Composition Root)
│
├── core/
│   ├── database.py              # Database — SQLite WAL 연결 관리
│   └── log/                     # 시스템 로그 인프라 (JSONL 포맷, fingerprint)
│       ├── __init__.py
│       ├── _record_keys.py      # LogRecord 속성 / Ante 예약 키 단일 소스 (runtime probe)
│       ├── formatter.py         # JsonFormatter — JSONL 직렬화
│       ├── fingerprint.py       # compute_fingerprint() — 예외 dedup 키
│       ├── handlers.py          # DateNamedTimedRotatingFileHandler (KST 자정 no-rename 회전)
│       ├── safe_logger.py       # AnteLogger, install_safe_logger() (makeRecord 예약 키 정규화)
│       └── setup.py             # setup_logging() stdout + JSONL 파일 핸들러 구성
│
├── config/
│   ├── config.py                # ConfigService — 설정 로딩 (system.toml + secrets.env)
│   ├── defaults.py              # 기본 설정값
│   ├── dynamic.py               # DynamicConfigService — DB 기반 런타임 설정
│   ├── exceptions.py
│   └── system_state.py          # SystemState — 시스템 상태 (active/halted)
│
├── eventbus/
│   ├── bus.py                   # EventBus — asyncio.Queue 기반 발행/구독
│   ├── events.py                # 전체 이벤트 dataclass 정의
│   └── history.py               # EventHistory — 이벤트 이력 추적
│
├── audit/
│   └── logger.py                # AuditLogger — 감사 로그 기록 (SQLite)
│
├── approval/
│   ├── models.py                # ApprovalRequest, ApprovalStatus, ApprovalType
│   └── service.py               # ApprovalService — 결재 요청 관리 + 자동 실행
│
├── instrument/
│   ├── models.py                # Instrument — 종목 메타데이터 (frozen dataclass)
│   └── service.py               # InstrumentService — 전체 메모리 캐시 + SQLite
│
├── member/
│   ├── auth.py                  # 토큰 생성, 복구 키, 인증 유틸리티
│   ├── models.py                # Member 데이터 모델 (MemberType 등)
│   └── service.py               # MemberService — 멤버 등록·인증·관리
│
├── bot/
│   ├── bot.py                   # Bot — 봇 실행 루프, 전략 실행, 이벤트 발행
│   ├── config.py                # BotConfig — 봇 설정 (exchange, 자금 한도 등)
│   ├── context_factory.py       # BotContextFactory — 봇 실행 컨텍스트 생성
│   ├── exceptions.py
│   ├── manager.py               # BotManager — 봇 생명주기 관리
│   ├── signal_channel.py        # SignalChannel — JSON Lines 파이프 기반 양방향 시그널 채널
│   ├── signal_key.py            # SignalKeyManager — 봇별 시그널 키 발급/관리
│   └── providers/
│       ├── live.py              # LiveProvider — 실전 봇 데이터 공급
│       └── paper.py             # PaperProvider — 모의 봇 데이터 공급
│
├── strategy/
│   ├── base.py                  # Strategy ABC, StrategyMeta, TradeHistoryView
│   ├── context.py               # StrategyContext — 전략 실행 컨텍스트 (파일 접근, 로깅, 거래 이력)
│   ├── exceptions.py
│   ├── indicators.py            # IndicatorCalculator — pandas-ta 기반 기술 지표 계산 (130+종)
│   ├── snapshot.py              # StrategySnapshot — 전략 파일 스냅샷 생성/정리
│   ├── loader.py                # StrategyLoader — 전략 파일 동적 로드
│   ├── registry.py              # StrategyRegistry — 전략 등록/관리
│   └── validator.py             # StrategyValidator — AST 기반 정적 검증
│
├── rule/
│   ├── base.py                  # Rule ABC, RuleContext, RuleEvaluation, EvaluationResult
│   ├── engine.py                # RuleEngine — 전역/전략별 룰 평가
│   ├── exceptions.py
│   ├── global_rules.py          # 전역 룰 정의
│   └── strategy_rules.py        # 전략별 룰 정의
│
├── treasury/
│   ├── models.py                # TreasuryAllocation — 자금 할당 모델
│   ├── treasury.py              # Treasury — 자금 배분 및 한도 관리
│   └── exceptions.py
│
├── trade/
│   ├── models.py                # TradeRecord, PositionSnapshot, PerformanceMetrics
│   ├── recorder.py              # TradeRecorder — 거래 기록 (SQLite)
│   ├── position.py              # PositionTracker — 포지션 추적
│   ├── performance.py           # PerformanceCalculator — 성과 산출
│   ├── reconciler.py            # PositionReconciler — 포지션 정합성 검증 및 자동 보정
│   └── service.py               # TradeService — 위 컴포넌트 조합
│
├── broker/
│   ├── base.py                  # BrokerAdapter ABC
│   ├── models.py                # CommissionInfo dataclass
│   ├── kis.py                   # KISAdapter — 한국투자증권 API 구현체
│   ├── kis_stream.py            # KISStreamClient — KIS WebSocket 실시간 시세/체결 통보
│   ├── circuit_breaker.py       # CircuitBreaker — API 장애 차단
│   ├── error_codes.py           # KIS API 에러 코드 분류 (영구/일시)
│   ├── mock.py                  # MockBroker — 테스트/모의투자용 브로커 구현체
│   ├── order_registry.py        # OrderRegistry — 주문 상태 추적 (SQLite)
│   └── exceptions.py
│
├── gateway/
│   ├── gateway.py               # APIGateway — rate limit, 캐시, 이벤트 기반 주문
│   ├── rate_limiter.py          # RateLimiter — 호출 빈도 제한
│   ├── cache.py                 # ResponseCache — TTL 기반 응답 캐시
│   ├── queue.py                 # OrderQueue — 주문 큐 관리
│   ├── data_provider.py         # GatewayDataProvider — 시세 조회 래퍼
│   └── stop_order.py            # StopOrderManager — 스탑 주문 에뮬레이션 (KRX 대응)
│
├── data/
│   ├── collector.py             # DataCollector — 실시간 시세 수집 → Parquet
│   ├── normalizer.py            # BaseNormalizer ABC + KIS/Yahoo/Default Normalizer, DataNormalizer 파사드
│   ├── retention.py             # DataRetention — 보존 정책, 외부 이관
│   ├── schemas.py               # OHLCV 등 데이터 스키마 정의
│   └── store.py                 # DataStore — Parquet 읽기/쓰기
│
├── feed/                            # DataFeed — 외부 데이터 수집 파이프라인
│   ├── cli.py                   # ante feed — DataFeed CLI 커맨드 (init/status/inject/config)
│   ├── config.py                # FeedConfig — DataFeed 설정 관리 (API 키, 경로 등)
│   ├── injector.py              # FeedInjector — CSV 파일에서 데이터 수동 주입
│   ├── models/
│   │   └── result.py            # ValidationResult, CollectionResult — 수집 결과 모델
│   ├── pipeline/
│   │   ├── checkpoint.py        # Checkpoint — 체크포인트 저장 및 복원
│   │   ├── orchestrator.py      # FeedOrchestrator — backfill/daily ETL 파이프라인 오케스트레이션
│   │   └── scheduler.py         # 날짜 범위 생성 (backfill vs daily 모드)
│   ├── report/
│   │   └── generator.py         # ReportGenerator — 수집 리포트 생성
│   ├── sources/
│   │   ├── base.py              # DataSource Protocol, RateLimiter 기반 클래스
│   │   ├── data_go_kr.py        # DataGoKrSource — data.go.kr 주식시세 API 소스 어댑터
│   │   └── dart.py              # DARTSource — DART OpenAPI 소스 어댑터
│   └── transform/
│       └── validate.py          # 4계층 데이터 검증 (transport/syntax/schema/business)
│
├── backtest/
│   ├── context.py               # BacktestContext — 백테스트 실행 환경
│   ├── data_provider.py         # BacktestDataProvider — Parquet 기반 시세 공급
│   ├── exceptions.py
│   ├── executor.py              # BacktestExecutor — 전략 실행 루프
│   ├── metrics.py               # calculate_metrics — 성과 지표 (Sharpe, MDD 등)
│   ├── result.py                # BacktestResult, BacktestTrade — 결과 모델
│   ├── runner.py                # BacktestRunner — subprocess 진입점
│   └── service.py               # BacktestService — 메인 프로세스 인터페이스
│
├── report/
│   ├── draft.py                 # ReportDraftGenerator — 백테스트 완료 시 초안 자동 생성 (equity curve 표준화 포함)
│   ├── feedback.py              # PerformanceFeedback — Agent 피드백용 실전 성과 조회 (equity curve 생성)
│   ├── models.py                # StrategyReport (get_equity_curve), ReportStatus (DRAFT 포함)
│   └── store.py                 # ReportStore — 전략 리포트 저장/조회
│
├── notification/
│   ├── base.py                  # NotificationAdapter ABC, NotificationLevel
│   ├── telegram.py              # TelegramAdapter — 텔레그램 봇 API 구현체
│   ├── telegram_receiver.py     # TelegramReceiver — 텔레그램 명령 수신 (양방향)
│   ├── templates.py             # 알림 메시지 템플릿 상수 (str.format 호환)
│   └── service.py               # NotificationService — 이벤트 구독, 라우팅, 필터링, 이력 저장
│
├── web/
│   ├── app.py                   # FastAPI app 생성
│   ├── errors.py                # RFC 7807 에러 핸들러
│   ├── pagination.py            # cursor 기반 페이지네이션 유틸리티
│   ├── schemas.py               # Pydantic 요청/응답 스키마
│   ├── session.py               # SessionStore — SQLite 기반 서버사이드 세션 관리
│   └── routes/
│       ├── approvals.py         # /api/approvals 라우트 (목록/상세/승인·거부)
│       ├── audit.py             # /api/audit 라우트 (감사 로그 조회)
│       ├── auth.py              # /api/auth 라우트 (세션 기반 로그인/로그아웃)
│       ├── bots.py              # /api/bots 라우트 (cursor 페이지네이션)
│       ├── config.py            # /api/config 라우트 (동적 설정 조회/변경)
│       ├── data.py              # /api/data 라우트
│       ├── members.py           # /api/members 라우트 (멤버 관리)
│       ├── notifications.py     # /api/notifications 라우트 (cursor 페이지네이션)
│       ├── portfolio.py         # /api/portfolio 라우트 (자산 가치/추이)
│       ├── reports.py           # /api/reports 라우트 (cursor 페이지네이션)
│       ├── strategies.py        # /api/strategies 라우트
│       ├── system.py            # /api/system 라우트
│       ├── test_seed.py          # /api/test 시드 데이터 주입 (테스트 모드 전용)
│       ├── trades.py            # /api/trades 라우트 (cursor 페이지네이션)
│       └── treasury.py          # /api/treasury 라우트 (자금 관리)
│
└── cli/
    ├── main.py                  # CLI 루트 그룹 (ante 커맨드)
    ├── middleware.py             # 인증 미들웨어 (require_auth, require_scope)
    ├── formatter.py             # OutputFormatter — table/json 출력
    └── commands/
        ├── approval.py          # ante approval request/list/info/review/cancel/approve/reject
        ├── audit.py             # ante audit — 감사 로그 조회
        ├── backtest.py          # ante backtest run (진행률 바, 성과 지표 테이블 포함)
        ├── bot.py               # ante bot create/list/start/stop/info (--param 전략 파라미터 오버라이드)
        ├── broker.py            # ante broker 명령
        ├── config.py            # ante config 명령
        ├── data.py              # ante data list/schema/inject/validate
        ├── init.py              # ante init — 설정 디렉토리 초기화
        ├── instrument.py        # ante instrument list/search/sync/import (--listed-only)
        ├── member.py            # ante member bootstrap/register/list/info/suspend/revoke/set-emoji/...
        ├── notification.py      # ante notification history
        ├── report.py            # ante report list/show/schema/performance/view
        ├── rule.py              # ante rule 명령
        ├── signal.py            # ante signal — 외부 시그널 채널 관리
        ├── strategy.py          # ante strategy list/validate/load
        ├── system.py            # ante system 명령
        ├── trade.py             # ante trade 명령
        └── treasury.py          # ante treasury 명령
```

## tests/ — 테스트

```
tests/
├── conftest.py                  # 공통 pytest fixture
├── fixtures/
│   └── seed/
│       ├── daily_fixed_buy.py   # 일일 고정 매수 시드 데이터
│       ├── generate_ohlcv.py    # OHLCV 테스트 데이터 생성
│       ├── generate_scenario.py # 시나리오별 시드 SQL 생성기
│       ├── seed.sql             # 통합 시드 SQL
│       ├── seeder.py            # 시드 데이터 실행기
│       ├── generators/          # Python 시드 데이터 생성기
│       │   ├── price.py         # GBM 기반 가상 주가 생성기
│       │   ├── trading.py       # 매매 시뮬레이션 (trades, positions 생성)
│       │   ├── treasury.py      # 자금 흐름 계산 (treasury 데이터 생성)
│       │   └── writer.py        # SQL INSERT 문 출력기
│       ├── strategies/          # E2E 테스트용 더미 전략
│       │   └── sma_cross.py     # SMA 크로스 전략
│       └── scenarios/           # E2E 시나리오별 시드 데이터
│           ├── _base.sql              # 공통 기반 데이터
│           ├── approvals.sql          # 결재 시나리오
│           ├── backtest-data.sql      # 백테스트 데이터 시나리오
│           ├── bot-management.sql     # 봇 관리 시나리오
│           ├── login-dashboard.sql    # 로그인/대시보드 시나리오
│           ├── member-management.sql  # 멤버 관리 시나리오
│           ├── settings.sql           # 설정 시나리오
│           ├── strategy-browse.sql    # 전략 탐색 시나리오
│           ├── treasury.sql           # 자금 관리 시나리오
│           ├── action-agent-lifecycle.sql  # 에이전트 생명주기 액션 시나리오
│           ├── action-approval-review.sql # 결재 검토 액션 시나리오
│           ├── action-bot-lifecycle.sql   # 봇 생명주기 액션 시나리오
│           ├── action-budget.sql          # 예산 관리 액션 시나리오
│           └── action-settings.sql        # 설정 액션 시나리오
├── e2e/                         # E2E 테스트
│   ├── conftest.py              # E2E 테스트 fixture
│   ├── pages/                   # Page Object 패턴
│   │   ├── common.py            # 공통 페이지 유틸리티
│   │   ├── header.py            # 헤더 Page Object
│   │   ├── login_page.py        # 로그인 Page Object
│   │   └── sidebar.py           # 사이드바 Page Object
│   ├── test_api_endpoints.py    # API 엔드포인트 E2E 테스트
│   ├── test_dashboard_pages.py  # 대시보드 페이지 E2E 테스트
│   ├── test_flow_approvals.py   # 결재 승인/거부 플로우
│   ├── test_flow_backtest_data.py # 백테스트 데이터 관리 플로우
│   ├── test_flow_bot_management.py # 봇 생명주기 플로우
│   ├── test_flow_login_dashboard.py # 로그인 → 대시보드 플로우
│   ├── test_flow_member_management.py # 멤버 관리 플로우
│   ├── test_flow_settings.py    # 설정 변경 플로우
│   ├── test_flow_strategy_browse.py # 전략 탐색 플로우
│   ├── test_flow_treasury.py    # 자금 관리 플로우
│   ├── test_action_agent_lifecycle.py  # 에이전트 생명주기 액션 테스트
│   ├── test_action_approval_review.py # 결재 검토 액션 테스트
│   ├── test_action_bot_lifecycle.py   # 봇 생명주기 액션 테스트
│   ├── test_action_budget.py    # 예산 관리 액션 테스트
│   ├── test_action_settings.py  # 설정 액션 테스트
│   ├── test_full_scenario.py    # 전체 시나리오 E2E 테스트
│   ├── test_visual_verification.py # 시각적 검증 테스트
│   └── visual_checker.py        # 시각적 검증 유틸리티
├── unit/                        # 단위 테스트 (pytest + pytest-asyncio)
│   ├── test_api_pagination.py   # Web API cursor 페이지네이션
│   ├── test_approval.py
│   ├── test_approval_api.py     # 결재 API 테스트
│   ├── test_audit.py            # 감사 로그(AuditLogger) 테스트
│   ├── test_backtest.py
│   ├── test_backtest_metrics.py # 성과 지표 (Sharpe, MDD, PnL 추정)
│   ├── test_backtest_progress.py # 백테스트 진행률 콜백
│   ├── test_bot_create_params.py # bot create --param 파라미터 오버라이드
│   ├── test_bot_providers.py
│   ├── test_bot_restart.py
│   ├── test_bot_stop_release.py
│   ├── test_bot.py
│   ├── test_bot_api.py          # 봇 CRUD API 테스트
│   ├── test_broker_meta_api.py # 브로커 메타 정보 API 테스트
│   ├── test_broker.py
│   ├── test_cli_auth.py
│   ├── test_cli_config.py
│   ├── test_cli_live.py
│   ├── test_cli.py
│   ├── test_commission.py
│   ├── test_config.py
│   ├── test_config_path.py      # Config 경로 탐색 및 ante init 테스트
│   ├── test_data_pipeline.py
│   ├── test_dataset_delete_api.py # 데이터셋 삭제 API 테스트
│   ├── test_database.py
│   ├── test_dynamic_config.py
│   ├── test_event_history.py
│   ├── test_eventbus.py
│   ├── test_equity_curve.py     # 자산 곡선 기능 (표준화, 리포트 추출, 피드백 생성)
│   ├── test_external_signal_subscription.py # 외부 시그널 구독
│   ├── test_external_signals.py # 외부 시그널 처리
│   ├── test_gateway_stop_routing.py # Gateway 스탑 주문 라우팅
│   ├── test_gateway.py
│   ├── test_instrument_cache_ttl.py # InstrumentService 캐시 TTL
│   ├── test_instrument_import.py    # 종목 데이터 CSV/JSON import
│   ├── test_instrument_sync.py  # KIS API 종목 동기화
│   ├── test_instrument.py
│   ├── test_kis_error_handling.py
│   ├── test_kis_stream.py      # KIS WebSocket 스트리밍
│   ├── test_listed_only.py      # --listed-only 필터
│   ├── test_main.py
│   ├── test_member.py
│   ├── test_member_api.py       # 멤버 관리 API 테스트
│   ├── test_mock_broker.py      # MockBroker 테스트
│   ├── test_notification_dedup.py   # 알림 중복 억제
│   ├── test_notification_history.py
│   ├── test_notification.py
│   ├── test_notification_templates.py # 알림 메시지 템플릿 테스트
│   ├── test_parquet_validation.py   # Parquet 파일 검증
│   ├── test_performance_summary.py  # 일간/월간 성과 요약
│   ├── test_portfolio_api.py    # 포트폴리오 API 테스트
│   ├── test_reconciler.py       # PositionReconciler 테스트
│   ├── test_report_draft.py     # 백테스트 초안 자동 생성
│   ├── test_report_api.py       # 리포트 API 테스트 (상세 조회, equity_curve, metrics)
│   ├── test_report.py
│   ├── test_rule.py
│   ├── test_seed_data.py        # 시드 데이터 테스트
│   ├── test_signal_channel.py   # SignalChannel 파이프 통신
│   ├── test_signal_key.py       # 시그널 키 발급/관리
│   ├── test_stop_order.py       # 스탑 주문 에뮬레이션
│   ├── test_indicators.py       # TA-Lib 기술 지표 계산기
│   ├── test_normalizer_classes.py # BaseNormalizer ABC + 소스별 Normalizer
│   ├── test_rule_modify.py      # 주문 정정 룰 검증
│   ├── test_session_auth.py     # 세션 기반 인증 API 테스트
│   ├── test_strategy.py
│   ├── test_strategy_api.py     # 전략 API 테스트
│   ├── test_strategy_snapshot.py # 전략 파일 스냅샷
│   ├── test_system_config_api.py # 시스템 설정 API 테스트 (킬스위치 + 동적 설정)
│   ├── test_system_state.py
│   ├── test_telegram_receiver.py
│   ├── test_token_expiry.py     # API 토큰 만료 정책
│   ├── test_trade.py
│   ├── test_trade_history_view.py # TradeHistoryView ABC
│   ├── test_treasury_sync.py
│   ├── test_treasury.py
│   ├── test_treasury_api.py     # 자금관리 API 확장 테스트
│   ├── test_web_api.py
│   ├── test_bot_guard.py        # 봇 런타임 가드
│   ├── test_dynamic_log_level.py # 동적 로그 레벨
│   ├── test_config_audit.py     # 설정 감사
│   └── feed/                    # DataFeed 모듈 단위 테스트
│       ├── test_checkpoint.py   # 체크포인트 저장/복원
│       ├── test_cli_init.py     # ante feed CLI 초기화
│       ├── test_cli_run.py      # ante feed run CLI 테스트
│       ├── test_cli_status.py   # ante feed status CLI 테스트
│       ├── test_config.py       # FeedConfig 설정 관리
│       ├── test_dart.py         # DART 소스 어댑터
│       ├── test_data_go_kr.py   # data.go.kr 소스 어댑터
│       ├── test_injector.py     # FeedInjector 데이터 주입
│       ├── test_orchestrator.py # FeedOrchestrator ETL 파이프라인
│       ├── test_report.py       # 수집 리포트 생성
│       ├── test_scheduler.py    # 날짜 범위 생성
│       └── test_validate.py     # 4계층 데이터 검증
├── integration/                 # 통합 테스트
│   └── test_e2e_flow.py
└── tc/                          # Gherkin 테스트 케이스 (.feature)
    ├── account/
    ├── approval/
    ├── bot/
    ├── config/
    ├── data/
    ├── member/
    ├── scenario/
    ├── strategy/
    ├── trade/
    └── treasury/
```

## deploy/ — 서비스 배포

```
deploy/
├── ante.service         # Linux systemd 유닛 파일
└── com.ante.plist       # macOS launchd plist 파일
```

## scripts/ — 설치·운영 스크립트

```
scripts/
├── generate_cli_reference.py  # CLI 레퍼런스 문서 자동 생성 (Click introspection)
├── install-service.sh         # OS 감지 후 systemd/launchd 서비스 설치
├── uninstall-service.sh       # 서비스 제거
├── verify-install.py          # 설치 검증 스크립트
├── qa-entrypoint.sh           # QA Docker 엔트리포인트
├── qa_seed_datasets.py        # QA 테스트용 데이터셋 시드
└── qa_seed_strategies.py      # QA 테스트용 전략 시드
```

## docs/ — 설계 문서

```
docs/
├── architecture/               # 시스템 아키텍처 문서 묶음
│   ├── README.md               # 아키텍처 인덱스 + 기술 스택
│   ├── system-diagram.md       # 시스템 구성도, 데이터/통신 흐름
│   ├── module-map.md           # 모듈 책임, 확장성, 배포 산출물
│   └── generated/              # 소스에서 생성된 문서
│       ├── db-schema.md        # SQLite 스키마 전체 목록
│       └── project-structure.md # 이 문서 — 프로젝트 디렉토리 구조
├── dashboard/                  # 대시보드 설계·목업
│   ├── architecture.md         # 대시보드 아키텍처
│   ├── design-guide.css
│   ├── design-guide.html
│   ├── mockups/
│   └── user-stories/
├── decisions/                  # 설계 결정 이력 디렉토리
│   ├── README.md               # 설계 결정 인덱스
│   └── D-001.md ... D-014.md
├── references/                 # 외부 참조 문서
│   └── dashboard/
├── runbooks/                   # 운영 절차서
│   ├── 00-issue-management.md  # 이슈 등록, 분류, 추적
│   ├── 01-development-process.md
│   ├── 02-agent-structure.md   # 에이전트 구조
│   ├── 03-git-workflow.md
│   ├── 04-ci-cd.md
│   ├── 05-testing.md
│   ├── 06-release.md           # 릴리스 절차
│   └── README.md
├── specs/                      # 모듈별 세부 설계
│   ├── README.md
│   ├── account/
│   │   ├── README.md
│   │   └── account.md
│   ├── approval/
│   │   ├── README.md
│   │   └── approval.md
│   ├── api-gateway/
│   │   └── api-gateway.md
│   ├── audit/
│   │   └── audit.md
│   ├── backtest/
│   │   ├── README.md
│   │   └── backtest.md
│   ├── bot/
│   │   ├── README.md
│   │   └── bot.md
│   ├── broker-adapter/
│   │   ├── README.md
│   │   └── broker-adapter.md
│   ├── cli/
│   │   ├── README.md
│   │   └── cli.md
│   ├── config/
│   │   ├── README.md
│   │   └── config.md
│   ├── core/
│   │   └── core.md
│   ├── data-feed/
│   │   ├── README.md
│   │   └── data-feed.md
│   ├── data-pipeline/
│   │   ├── README.md
│   │   └── data-pipeline.md
│   ├── eventbus/
│   │   └── eventbus.md
│   ├── instrument/
│   │   └── instrument.md
│   ├── ipc/
│   │   └── ipc.md
│   ├── member/
│   │   ├── README.md
│   │   └── member.md
│   ├── notification/
│   │   └── notification.md
│   ├── report-store/
│   │   └── report-store.md
│   ├── rule-engine/
│   │   ├── README.md
│   │   └── rule-engine.md
│   ├── strategy/
│   │   ├── README.md
│   │   └── strategy.md
│   ├── trade/
│   │   ├── README.md
│   │   └── trade.md
│   ├── treasury/
│   │   ├── README.md
│   │   └── treasury.md
│   └── web-api/
│       └── web-api.md
└── temp/                       # 임시 작업 문서
```

## guide/ — 사용자·운용 가이드

```
guide/
├── agent.md             # AI Agent 온보딩 가이드
├── cli.md               # CLI 레퍼런스 (자동 생성)
├── dashboard.md         # 대시보드 사용 가이드
├── getting-started.md   # 설치·초기 설정 가이드
├── security.md          # 보안 가이드
├── strategy.md          # 전략 개발 가이드
└── assets/              # 가이드 이미지·SVG
    └── how-it-works.svg # 시스템 구조 도식
```

## frontend/ — React 대시보드

```
frontend/src/
├── main.tsx                     # Vite 엔트리포인트
├── App.tsx                      # 라우터 설정, 전역 레이아웃
├── index.css                    # 글로벌 스타일
│
├── api/
│   ├── client.ts                # Axios 클라이언트 (baseURL, 인터셉터)
│   ├── approvals.ts             # 결재 API 호출
│   ├── auth.ts                  # 인증 API 호출 (로그인/로그아웃)
│   ├── reports.ts               # 리포트 API 호출
│   ├── bots.ts                  # 봇 API 호출
│   ├── data.ts                  # 데이터 API 호출
│   ├── members.ts               # 멤버 API 호출
│   ├── portfolio.ts             # 포트폴리오 API 호출
│   ├── strategies.ts            # 전략 API 호출
│   ├── system.ts                # 시스템 API 호출
│   └── treasury.ts              # 자금관리 API 호출
│
├── types/
│   ├── approval.ts              # 결재 타입 정의
│   ├── auth.ts                  # 인증 타입 정의
│   ├── bot.ts                   # 봇 타입 정의
│   ├── member.ts                # 멤버 타입 정의
│   ├── portfolio.ts             # 포트폴리오 타입 정의
│   ├── strategy.ts              # 전략 타입 정의
│   ├── system.ts                # 시스템 타입 정의
│   ├── feed.ts                  # DataFeed 타입 정의
│   ├── report.ts                # 리포트 타입 정의
│   └── treasury.ts              # 자금관리 타입 정의
│
├── hooks/
│   ├── useApprovals.ts          # 결재 데이터 훅
│   ├── useAuth.ts               # 인증 상태 훅
│   ├── useBacktestData.ts       # 백테스트 데이터 훅
│   ├── useBots.ts               # 봇 데이터 훅
│   ├── useFeed.ts               # DataFeed 데이터 훅
│   ├── useMembers.ts            # 멤버 데이터 훅
│   ├── usePortfolio.ts          # 포트폴리오 데이터 훅
│   ├── useReports.ts            # 리포트 데이터 훅
│   ├── useStrategies.ts         # 전략 데이터 훅
│   ├── useSystemStatus.ts       # 시스템 상태 훅
│   └── useTreasury.ts           # 자금관리 데이터 훅
│
├── pages/
│   ├── AgentDetail.tsx          # 에이전트 상세 페이지
│   ├── Agents.tsx               # 에이전트 목록 페이지
│   ├── ApprovalDetail.tsx       # 결재 상세 페이지
│   ├── Approvals.tsx            # 결재 목록 페이지
│   ├── BacktestData.tsx         # 백테스트 데이터 관리 페이지
│   ├── BotDetail.tsx            # 봇 상세 페이지
│   ├── Bots.tsx                 # 봇 목록 페이지
│   ├── Dashboard.tsx            # 대시보드 메인 페이지
│   ├── Login.tsx                # 로그인 페이지
│   ├── NotFound.tsx             # 404 페이지
│   ├── Performance.tsx          # 성과 분석 페이지
│   ├── ReportDetail.tsx         # 리포트 상세 페이지
│   ├── Settings.tsx             # 시스템 설정 페이지
│   ├── Strategies.tsx           # 전략 목록 페이지
│   ├── StrategyDetail.tsx       # 전략 상세 페이지
│   ├── Trades.tsx               # 거래 내역 페이지
│   ├── Treasury.tsx             # 자금관리 페이지
│   └── TreasuryHistory.tsx      # 자금관리 이력 페이지
│
├── components/
│   ├── auth/
│   │   ├── LoginForm.tsx        # 로그인 폼
│   │   └── ProtectedRoute.tsx   # 인증 필요 라우트 가드
│   ├── layout/
│   │   ├── Header.tsx           # 상단 헤더
│   │   ├── Layout.tsx           # 공통 레이아웃 (헤더 + 사이드바)
│   │   └── Sidebar.tsx          # 사이드바 네비게이션
│   ├── common/
│   │   ├── DataTable.tsx        # 범용 데이터 테이블
│   │   ├── ErrorBoundary.tsx    # React 에러 바운더리
│   │   ├── HintTooltip.tsx      # 힌트 툴팁
│   │   ├── LoadingSpinner.tsx   # 로딩 스피너
│   │   ├── Pagination.tsx       # 페이지네이션 컨트롤
│   │   ├── ServiceUnavailable.tsx # 서비스 불가 안내
│   │   ├── Modal.tsx            # 범용 모달 (ESC/오버레이 닫기)
│   │   ├── Skeleton.tsx         # 로딩 스켈레톤 UI
│   │   ├── StatusBadge.tsx      # 상태 뱃지
│   │   └── Toast.tsx            # 토스트 알림
│   ├── agents/
│   │   ├── AgentRegisterForm.tsx # 에이전트 등록 폼
│   │   ├── AgentTable.tsx       # 에이전트 목록 테이블
│   │   ├── ChangePasswordModal.tsx # 비밀번호 변경 모달
│   │   └── MemberCard.tsx       # 멤버 카드 컴포넌트
│   ├── approvals/
│   │   ├── ApprovalFilters.tsx  # 결재 필터
│   │   ├── ApprovalTable.tsx    # 결재 목록 테이블
│   │   ├── ExecutionContent.tsx # 결재 유형별 실행 내용 렌더러
│   │   ├── MarkdownBody.tsx     # 마크다운 본문 (lazy 로딩 래퍼)
│   │   ├── MarkdownRenderer.tsx # react-markdown 기반 마크다운 렌더러
│   │   └── ReviewControls.tsx   # 승인/거부 컨트롤 (모달 포함)
│   ├── bots/
│   │   ├── BotCard.tsx          # 봇 카드 컴포넌트
│   │   ├── BotCreateForm.tsx    # 봇 생성 폼
│   │   ├── BotDeleteModal.tsx   # 봇 삭제 확인 모달
│   │   ├── BotStopModal.tsx     # 봇 정지 확인 모달
│   │   └── BotTable.tsx         # 봇 목록 테이블
│   ├── charts/
│   │   ├── AssetTrendChart.tsx  # 자산 추이 차트
│   │   ├── DailyReturnChart.tsx # 일간 수익률 차트
│   │   ├── EquityCurveChart.tsx # 자산 곡선 차트
│   │   └── LightweightChart.tsx # lightweight-charts 래퍼
│   ├── data/
│   │   ├── ApiKeyStatusPanel.tsx # API 키 상태 패널
│   │   └── FeedStatusPanel.tsx  # DataFeed 상태 패널
│   ├── strategies/
│   │   ├── PerformancePanel.tsx # 전략 성과 패널
│   │   ├── PeriodPerformance.tsx # 기간별 성과 표시
│   │   └── StrategyTable.tsx    # 전략 목록 테이블
│   └── treasury/
│       ├── AccountSummary.tsx   # 계좌 요약
│       ├── AllocationForm.tsx   # 자금 할당 폼
│       ├── AnteSummary.tsx      # Ante 자금 요약
│       ├── BudgetPieChart.tsx   # 예산 배분 파이 차트
│       ├── BudgetTable.tsx      # 봇별 예산 테이블
│       └── RecentTransactions.tsx # 최근 거래 내역
│
├── globals.d.ts                 # 전역 타입 선언
│
└── utils/
    ├── constants.ts             # 공통 상수
    └── formatters.ts            # 포맷 유틸리티 (통화, 날짜 등)
```

## .agent/ — 에이전트 정의/명령/스킬

```
.agent/
├── agents/                      # 역할별 에이전트 프로필
├── commands/                    # 프로젝트 슬래시 커맨드
│   ├── implement-issue.md       # /implement-issue
│   ├── autopilot.md             # /autopilot
│   ├── qa-test.md               # /qa-test
│   ├── qa-sweep.md              # /qa-sweep
│   └── api-docs.md              # /api-docs
└── skills/                      # 프로젝트 스킬 (컨벤션·패턴 참조)
    ├── asyncio-patterns.md
    ├── frontend-conventions.md
    ├── module-conventions.md
    ├── qa-tester/               # QA 테스터 스킬 (Gherkin 해석)
    ├── release.md               # /release 릴리스 절차
    ├── review-pr.md
    └── sqlite-patterns.md
```

## .claude/ — Claude Code 설정 및 호환 레이어

```
.claude/
├── settings.json                # 권한 설정, 훅 설정
├── settings.local.json          # 로컬 환경별 설정
├── settings.local.example.json  # 로컬 설정 예시
├── hooks/                       # 자동 훅 스크립트 (auto-format, protect-files)
├── agents -> ../.agent/agents
├── commands -> ../.agent/commands
└── skills -> ../.agent/skills
```
