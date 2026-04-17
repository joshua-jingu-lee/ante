# Web API 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/web/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 웹 대시보드, D-008, [cli.md](../cli/cli.md) CLI 인터페이스

## 개요

Web API는 **React 대시보드에 데이터를 제공하는 FastAPI 백엔드**이다.
웹 대시보드를 통한 시스템 모니터링·봇 관리·거래 조회를 지원한다.

**주요 기능**:
- **REST API**: 봇 관리, 거래 조회, 자금 관리, 리포트 관리 등 CRUD
- **정적 파일 서빙**: React 빌드 결과물 배포

## 설계 결정

### FastAPI 애플리케이션

> 소스: [`src/ante/web/app.py`](../../../src/ante/web/app.py)

**근거** (D-008):
- FastAPI — 타입 힌트 기반 자동 문서화, asyncio 네이티브, 경량
- 의존성 주입 — `app.state`에 서비스 인스턴스 저장, 라우터에서 접근
- React SPA — 빌드된 정적 파일을 FastAPI가 서빙, 별도 웹서버 불필요

**라우터 구성**:

| Prefix | 태그 | 설명 |
|--------|------|------|
| `/api/system` | system | 시스템 상태·헬스체크·킬스위치 (계좌별/전체) |
| `/api/accounts` | accounts | 계좌 CRUD + 정지·활성화 |
| `/api/auth` | auth | 세션 인증 (login/logout/me) |
| `/api/bots` | bots | 봇 CRUD + 제어 |
| `/api/trades` | trades | 거래 이력 조회 |
| `/api/strategies` | strategies | 전략 관리 |
| `/api/reports` | reports | 리포트 관리 |
| `/api/notifications` | notifications | ~~알림 이력 조회~~ (텔레그램으로 이관, 라우터 비활성) |
| `/api/data` | data | 데이터셋 조회·삭제 |
| `/api/approvals` | approvals | 결재 관리 (목록/상세/승인·거부) |
| `/api/treasury` | treasury | 자금 관리 (잔고/예산/일별 스냅샷) |
| `/api/portfolio` | portfolio | 포트폴리오 (총 자산·손익·수익률, 자산 추이 — 스냅샷 기반) |
| `/api/members` | members | 멤버(에이전트) 관리 |
| `/api/config` | config | 동적 설정 관리 |
| `/api/audit` | audit | 감사 로그 조회 |

### 인증

세션 기반 인증 구현 완료. `POST /api/auth/login`으로 로그인 후 세션 쿠키를 발급하며, 401 응답 통일. `GET /api/auth/me`로 현재 사용자 정보 조회, `POST /api/auth/logout`으로 로그아웃.

### SessionService — 서버사이드 세션 관리

> 소스: [`src/ante/web/session.py`](../../../src/ante/web/session.py)

SQLite 기반 서버사이드 세션 저장소. `sessions` 테이블에 세션 ID, 멤버 ID, 만료 시각 등을 관리한다.

**생성자 파라미터:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `db` | Database | (필수) | SQLite 연결 인스턴스 |
| `ttl_hours` | int | 24 | 세션 TTL (시간) |

**메서드:**

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | sessions 테이블 스키마 생성 |
| `create` | member_id: str, ip_address: str = "", user_agent: str = "" | str | 세션 생성. session_id 반환 |
| `validate` | session_id: str | dict \| None | 세션 유효성 확인. 유효하면 세션 데이터, 만료/미존재 시 None |
| `delete` | session_id: str | None | 세션 삭제 |
| `delete_by_member` | member_id: str | None | 멤버의 모든 세션 삭제 |
| `cleanup_expired` | — | int | 만료된 세션 일괄 삭제. 삭제 건수 반환 |

### CORS 설정

홈서버 환경이므로 개발 편의상 전체 origin 허용 (`allow_origins=["*"]`).

### OpenAPI 자동 문서화

FastAPI가 라우터 정의와 Pydantic 스키마(`schemas.py`)로부터 OpenAPI 3.x 스펙을 자동 생성한다. 별도 설정 없이 다음 경로에서 접근 가능:

| 경로 | 설명 |
|------|------|
| `/docs` | Swagger UI — 인터랙티브 API 탐색기. 엔드포인트별 파라미터 확인, 직접 요청 실행 가능 |
| `/redoc` | ReDoc — 읽기 전용 API 레퍼런스 문서 |
| `/openapi.json` | OpenAPI JSON 스키마 원본. Agent나 외부 도구가 API 계약을 파싱할 때 사용 |

> AI Agent는 `/openapi.json`을 조회하여 사용 가능한 엔드포인트, 파라미터, 응답 스키마를 자동으로 파악할 수 있다.

## REST API 엔드포인트

> 각 엔드포인트의 요청/응답 스키마, 파라미터 상세, 에러 코드는 Swagger UI(`/docs`)를 참조한다. 아래 표는 전체 엔드포인트 목록과 용도를 요약한다.

### 시스템 (`/api/system`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/system/status` | 시스템 상태 (status, version) |
| GET | `/api/system/health` | 헬스체크 (`{"ok": true}`) |
| POST | `/api/system/kill-switch` | 킬 스위치 제어 (halt/activate). 파라미터: action, reason, account_id? (생략 시 전체 계좌) |

### 계좌 관리 (`/api/accounts`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/accounts` | 계좌 목록 |
| POST | `/api/accounts` | 계좌 등록. Body: account_id, exchange, currency, broker_type, credentials_ref, commission_rate, sell_tax_rate |
| GET | `/api/accounts/{account_id}` | 계좌 상세 조회 |
| POST | `/api/accounts/{account_id}/suspend` | 계좌 거래 정지. Body: reason. 이미 정지 상태이면 409 Conflict |
| POST | `/api/accounts/{account_id}/activate` | 계좌 거래 재개. 이미 활성 상태이면 409 Conflict |
| DELETE | `/api/accounts/{account_id}` | 계좌 삭제 (연결된 봇이 없을 때만) |
| GET | `/api/accounts/{account_id}/rules` | 계좌 리스크 룰 목록 조회. Config에서 `accounts.{id}.rules` 키를 읽어 RULE_REGISTRY 기반으로 구조화 반환. 응답: `{rules: [{type, name, enabled, priority, config, param_schema}]}` |
| PUT | `/api/accounts/{account_id}/rules/{rule_type}` | 계좌 리스크 룰 수정. Body: `{enabled?, config?}`. RULE_REGISTRY에서 rule_type 유효성 + config 파라미터 스키마 검증 후 Config API(`PUT /api/config/{key}`)에 위임. ConfigChangedEvent → RuleEngine 자동 리로드 |

### 인증 (`/api/auth`)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/auth/login` | 패스워드 로그인 → 세션 쿠키 발급 |
| POST | `/api/auth/logout` | 로그아웃 — 세션 삭제 + 쿠키 제거 |
| GET | `/api/auth/me` | 현재 로그인 사용자 정보 |

### 봇 관리 (`/api/bots`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/bots` | 봇 목록 (cursor 페이지네이션, 필터: account_id, limit, cursor). 응답에 `strategy_name` 포함 — StrategyRegistry 조인 |
| POST | `/api/bots` | 봇 생성. Body: bot_id, strategy_id, name, bot_type, interval_seconds. 계좌 정지 상태이면 409 Conflict |
| GET | `/api/bots/{bot_id}` | 봇 상세 조회 (전략/예산/포지션 포함) |
| POST | `/api/bots/{bot_id}/start` | 봇 시작 |
| POST | `/api/bots/{bot_id}/stop` | 봇 중지 |
| PUT | `/api/bots/{bot_id}` | 봇 설정 수정. 중지 상태에서만 가능. Body: name?, interval_seconds?, budget?, auto_restart?, max_restart_attempts?, restart_cooldown_seconds?, step_timeout_seconds?, max_signals_per_step?. BotConfig 재생성 패턴 적용. budget 변경 시 Treasury 연동. 응답: `{bot: {...}}` |
| DELETE | `/api/bots/{bot_id}` | 봇 삭제. Query: handle_positions (`keep`\|`liquidate`, 기본 `keep`). `liquidate` 시 보유 종목 시장가 매도 후 삭제 |
| GET | `/api/bots/{bot_id}/logs` | 봇 실행 로그 조회. `event_log` 테이블에서 해당 봇의 이벤트를 필터링. 필터: limit(기본 10, 최대 100), offset, start_date, end_date. 대상 이벤트: `BotStepCompletedEvent`, `BotStartedEvent`, `BotStoppedEvent`, `BotErrorEvent`. 응답: `{logs: [{timestamp, result, message}], total}` |

### 거래 이력 (`/api/trades`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/trades` | 거래 이력 (cursor 페이지네이션, 필터: account_id, bot_id, symbol, limit, cursor) |

### 전략 관리 (`/api/strategies`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/strategies` | 전략 목록 (필터: status). 응답에 `cumulative_return`, `backtest_return` 포함 — 전략별 PerformanceTracker 조회 |
| GET | `/api/strategies/{strategy_id}` | 전략 상세 조회. 응답에 `params`, `param_schema`, `rationale`, `risks` 포함 — 전략 클래스 런타임 로드 + StrategyRecord 확장 필드 |
| POST | `/api/strategies/validate` | 전략 파일 검증. Body: `{"path": "..."}` |
| GET | `/api/strategies/{strategy_id}/performance` | 전략 성과 지표 |
| GET | `/api/strategies/{strategy_id}/daily-summary` | 전략 일별 성과 집계 |
| GET | `/api/strategies/{strategy_id}/weekly-summary` | 전략 주별 성과 집계 |
| GET | `/api/strategies/{strategy_id}/monthly-summary` | 전략 월별 성과 집계 |
| GET | `/api/strategies/{strategy_id}/trades` | 전략 거래 내역 (cursor 페이지네이션) |

### 리포트 관리 (`/api/reports`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/reports/schema` | 리포트 제출 스키마 |
| POST | `/api/reports` | 리포트 제출 (201 응답) |
| GET | `/api/reports` | 리포트 목록 (cursor 페이지네이션, 필터: status, limit, cursor) |
| GET | `/api/reports/{report_id}` | 리포트 상세 조회 |

### 데이터 (`/api/data`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/data/datasets` | 보유 데이터셋 목록 (필터: symbol, timeframe, data_type, offset, limit) |
| GET | `/api/data/datasets/{dataset_id}` | 데이터셋 상세 조회. 메타데이터(symbol, timeframe, 기간, 행 수) + 데이터 미리보기(최근 5행). dataset_id = `{symbol}__{timeframe}`. ParquetStore.read(limit=5) 활용 |
| GET | `/api/data/schema` | 데이터 스키마 (필터: data_type) |
| GET | `/api/data/storage` | 저장 용량 현황 |
| DELETE | `/api/data/datasets/{dataset_id}` | 데이터셋 삭제 (필터: data_type) |
| GET | `/api/data/feed-status` | Feed 파이프라인 상태 조회 |

### 결재 관리 (`/api/approvals`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/approvals` | 결재 목록 (필터: status, type, search, offset, limit). `search`: title/requester LIKE 키워드 검색 |
| GET | `/api/approvals/{approval_id}` | 결재 상세 조회 |
| PATCH | `/api/approvals/{approval_id}/status` | 결재 승인/거부. Body: status, memo |

### 자금 관리 (`/api/treasury`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/treasury` | 자금 현황 요약 (필터: account_id) |
| GET | `/api/treasury/transactions` | 자금 변동 이력 (필터: account_id, type, bot_id, limit, offset) |
| GET | `/api/treasury/budgets` | 봇별 예산 목록 |
| POST | `/api/treasury/bots/{bot_id}/allocate` | 봇에 예산 할당. Body: amount |
| POST | `/api/treasury/bots/{bot_id}/deallocate` | 봇 예산 회수. Body: amount |
| POST | `/api/treasury/balance` | 계좌 총 잔고 수동 설정. Body: balance |
| GET | `/api/treasury/snapshots/latest` | 가장 최근 일별 스냅샷 조회 (필터: account_id). 자금 관리 T-1 데이터 소스 |
| GET | `/api/treasury/snapshots` | 기간별 일별 스냅샷 목록 (필터: account_id, start_date, end_date). 자금 관리 T-2 차트 데이터 소스 |
| GET | `/api/treasury/snapshots/{date}` | 특정일 스냅샷 조회 (필터: account_id) |

> 스냅샷 스펙: [treasury.md — 일별 자산 스냅샷](../treasury/treasury.md#일별-자산-스냅샷-daily-asset-snapshot)

### 포트폴리오 (`/api/portfolio`)

자금 관리 T-1(총 자산·당일 손익·수익률), T-2(자산 추이 차트)를 제공한다. 내부적으로 `treasury_daily_snapshots` 테이블을 조회하며, 실시간 계산 없이 스냅샷 기반으로 응답한다.

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/portfolio/value` | 총 자산 가치 + 당일 손익 + 당일 수익률 + 미실현 손익 (필터: account_id). 최신 스냅샷 기반 |
| GET | `/api/portfolio/history` | 기간별 자산 추이 (필터: account_id, start_date, end_date). `treasury_daily_snapshots` 시계열 반환 |

> `/api/portfolio/value` 응답에는 스냅샷의 `total_asset`, `daily_pnl`, `daily_return`, `unrealized_pnl` 등이 포함된다.
> `/api/portfolio/history`는 프론트엔드가 기간 버튼(1주/1개월/3개월/전체)에 따라 `start_date`/`end_date`를 계산하여 요청한다. 기간 수익률은 프론트엔드에서 `daily_return`의 기하평균으로 산출.

### 멤버 관리 (`/api/members`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/members` | 멤버 목록 (필터: type, org, status, limit, offset) |
| POST | `/api/members` | 멤버 등록 (토큰 1회 반환) |
| GET | `/api/members/{member_id}` | 멤버 상세 조회 |
| POST | `/api/members/{member_id}/suspend` | 멤버 일시 정지 |
| POST | `/api/members/{member_id}/reactivate` | 멤버 재활성화 |
| POST | `/api/members/{member_id}/revoke` | 멤버 영구 폐기 |
| POST | `/api/members/{member_id}/rotate-token` | 토큰 재발급 |
| PATCH | `/api/members/{member_id}/password` | 비밀번호 변경 (human 멤버 전용) |
| PUT | `/api/members/{member_id}/scopes` | 권한 범위 변경 |

### 설정 관리 (`/api/config`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/config` | 동적 설정 전체 조회 |
| PUT | `/api/config/{key:path}` | 동적 설정 값 변경. Body: value, category |

### 감사 로그 (`/api/audit`)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/audit` | 감사 로그 조회 (필터: member_id, action, from_date, to_date, limit, offset) |

### Cursor 기반 페이지네이션

> 소스: [`src/ante/web/pagination.py`](../../../src/ante/web/pagination.py)

대량 데이터 목록 API에 cursor 기반 페이지네이션을 적용한다.

| 함수 | 설명 |
|------|------|
| `encode_cursor(value)` | 커서 값을 base64 URL-safe 인코딩 |
| `decode_cursor(cursor)` | 인코딩된 커서를 디코딩 |
| `paginate(items, cursor_field, limit, cursor)` | 아이템 목록에서 커서 이후 limit건 추출. `{"items": [...], "next_cursor": ... \| None}` 반환 |

적용 엔드포인트: `/api/bots`, `/api/trades`, `/api/notifications`, `/api/reports`

### RFC 7807 에러 응답

> 소스: [`src/ante/web/errors.py`](../../../src/ante/web/errors.py)

RFC 7807 (Problem Details for HTTP APIs) 표준을 따르는 에러 응답 포맷.
`register_exception_handlers(app)`으로 FastAPI 앱에 등록한다.

## Pydantic 스키마 (`schemas.py`)

| 클래스 | 설명 |
|--------|------|
| `StatusResponse` | 시스템 상태 응답 (status, version) |
| `ErrorResponse` | RFC 7807 에러 응답 (type, title, detail, status, instance) |
| `ReportSubmitRequest` | 리포트 제출 요청 (strategy_name, strategy_version, backtest_result, summary, recommendation) |
| `LoginRequest` | 로그인 요청 (member_id, password) |
| `LoginResponse` | 로그인 응답 (member_id, name, type) |
| `MeResponse` | 현재 사용자 정보 응답 (member_id, name, type, emoji, role, login_at) |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## 미결 사항

없음.

## 타 모듈 설계 시 참고

- **CLI 스펙**: CLI와 Web API는 동일한 서비스 계층을 공유, 기능 대칭 유지
- **EventBus 스펙**: ExternalSignalEvent 정의
- **Bot 스펙**: BotManager가 REST API에서 호출됨 (생성/시작/중지)
- **Report Store 스펙**: 리포트 CRUD + 상태 변경 API
- **Notification 스펙**: 알림은 독립 채널 (텔레그램)
- **Treasury 스펙**: 일별 자산 스냅샷 API (`/api/treasury/snapshots/*`) — [treasury.md](../treasury/treasury.md#일별-자산-스냅샷-daily-asset-snapshot), 포트폴리오 API는 스냅샷 기반 응답
