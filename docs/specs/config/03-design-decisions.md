# Config 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 설계 결정

### 계층별 역할

#### 1. 정적 설정 — TOML 파일 (`config/system.toml`)

시스템 인프라 수준의 설정으로, 변경 시 재시작 필요.

```toml
[system]
log_level = "INFO"
timezone = "Asia/Seoul"

[db]
path = "db/ante.db"
event_log_retention_days = 30

[parquet]
base_path = "data/"
compression = "snappy"

[web]
host = "0.0.0.0"
port = 3982
cors_origins = ["http://localhost:3000"]

# [broker] 섹션은 Account 모델로 이관됨.
# broker.type, broker.commission_rate, broker.sell_tax_rate → Account 모델의 필드로 관리.
# broker.kis.* (APP_KEY, APP_SECRET 등) → Account.credentials_ref를 통해 secrets.env 참조.
# 아래는 Account와 무관한 브로커 인프라 설정만 유지.
[broker]
base_url = "https://openapi.koreainvestment.com:9443"  # 실전
paper_base_url = "https://openapivts.koreainvestment.com:29443"  # 모의투자

[notification]
default_channel = "telegram"

[eventbus]
history_size = 1000  # 인메모리 링버퍼 크기
```

**근거**:
- TOML은 Python 3.11+ 표준 라이브러리(`tomllib`)로 파싱 가능 — 외부 의존성 없음
- 사람이 읽기/편집 용이 (JSON보다 코멘트 지원, YAML보다 파싱 안정적)
- FreqTrade의 JSON 방식은 코멘트 불가, NautilusTrader의 YAML은 보안 이슈(arbitrary code execution) 가능

#### 2. 비밀값 — `.env` 파일 (`config/secrets.env`)

API 키, 토큰 등 민감 정보. gitignore 대상.

```env
# 한국투자증권 API — Account.credentials_ref로 참조
# Account별 접두사: KIS_{ACCOUNT_ID}_ 형식
KIS_DEFAULT_APP_KEY=xxxxxxxx
KIS_DEFAULT_APP_SECRET=xxxxxxxx
KIS_DEFAULT_ACCOUNT_NO=12345678-01

# 복수 계좌 예시
KIS_PAPER01_APP_KEY=yyyyyyyy
KIS_PAPER01_APP_SECRET=yyyyyyyy
KIS_PAPER01_ACCOUNT_NO=50012345-01

# 텔레그램 알림
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
TELEGRAM_CHAT_ID=987654321
```

**로딩 우선순위**: 환경변수 > `.env` 파일 > 기본값

**근거**:
- 비밀값을 설정 파일과 분리하여 git 커밋 시 노출 방지
- 환경변수 우선으로 systemd 배포 시 유연한 오버라이드
- 자체 구현한 경량 `.env` 파서 사용 (`KEY=VALUE` 형식, `#` 코멘트, 따옴표 제거 지원) — 외부 의존성 없음

#### 3. 동적 설정 — SQLite (`dynamic_config` 테이블)

런타임 변경이 필요한 설정. 웹 대시보드에서 CRUD, 변경 시 EventBus 알림.

```sql
CREATE TABLE dynamic_config (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,     -- JSON 직렬화
    category  TEXT NOT NULL,     -- 분류 (예: 'rule', 'fund', 'notification')
    updated_at TEXT DEFAULT (datetime('now'))
);
```

**저장 대상**:

*글로벌 안전장치 (RuleEngine이 검증)*:

| 키 | 카테고리 | 설명 | 예시 값 |
|----|---------|------|--------|
| `rule.max_daily_loss_rate` | rule | 일일 누적 손실 한도 (총 자금 대비 %). 초과 시 시스템이 자동으로 HALTED 전환 | `0.03` |
| `rule.max_total_exposure` | rule | 최대 총 노출 비율 (총 자금 대비 %). 보유 포지션 평가액 합계가 이 비율에 도달하면 신규 매수 거부 | `0.30` |

*자금 관리 (Treasury가 참조)*:

| 키 | 카테고리 | 설명 | 예시 값 |
|----|---------|------|--------|
| `treasury.bot_{id}.allocation` | treasury | 봇별 자금 할당 한도. 봇이 사용 가능한 최대 자금 | `5000000` |

*알림 (NotificationAdapter가 참조)*:

| 키 | 카테고리 | 설명 | 예시 값 |
|----|---------|------|--------|
| `notification.enabled` | notification | 알림 발송 활성화 여부 | `true` |
| `notification.quiet_hours` | notification | 알림 무음 시간대. 이 시간에는 긴급 알림 외 발송 안 함 | `"23:00-07:00"` |

> **참고 — 킬 스위치(Trading State)**는 `dynamic_config`에 포함하지 않음.
> 긴급 상황에서 DB 경로를 거치지 않고 즉시 작동해야 하므로
> `AccountService`에서 계좌별 인메모리로 관리하며,
> SQLite에는 재시작 복원용으로만 기록한다.
> 상태: ACTIVE / HALTED (2단계). 계좌별 정지/활성화 또는 전체 제어 가능.
> 제어 채널: 웹 대시보드, CLI (`ante system halt/activate [--account <id>]`), 텔레그램 명령.

### SystemState — 킬 스위치(Trading State) 관리

#### TradingState Enum

| 값 | 설명 |
|----|------|
| ACTIVE | 정상 거래 |
| HALTED | 모든 거래 차단 (긴급 중지) |

SystemState는 시스템 거래 상태(킬 스위치)를 관리한다.
인메모리에서 즉시 조회 가능하며, SQLite에 재시작 복원용으로 영속화한다.
상태 변경 시 `TradingStateChangedEvent`를 발행하여 시스템 전체에 전파한다.

> **Account 모델 도입 후**: 거래 상태는 `AccountService`가 계좌별로 관리한다.
> `TradingStateChangedEvent`의 발행자가 `SystemState` → `AccountService`로 변경되며,
> 이벤트에 `account_id`가 포함된다. 전체 시스템 halt는 모든 계좌를 일괄 HALTED로 전환하는 방식으로 동작한다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | 스키마 생성 + DB에서 마지막 상태 복원 |
| `trading_state` (property) | — | TradingState | 현재 거래 상태 조회 (인메모리 즉시 반환) |
| `set_state` | state: TradingState, reason: str = "", changed_by: str = "" | None | 거래 상태 변경 (인메모리 + DB + 이벤트 발행). 동일 상태로의 변경은 무시 |

**SQLite 스키마**:

```sql
CREATE TABLE system_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE system_state_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    old_state  TEXT NOT NULL,
    new_state  TEXT NOT NULL,
    reason     TEXT DEFAULT '',
    changed_by TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
```

**설계 근거**:
- **인메모리 우선**: `trading_state` 프로퍼티는 DB 조회 없이 즉시 반환 — 킬 스위치의 핵심 요건
- **DB는 복원 전용**: 시스템 재시작 시 마지막 상태로 복원
- **이력 기록**: 누가/언제/왜 상태를 변경했는지 감사 추적
- **Config와 분리**: Config는 정적 설정(TOML) + 비밀값(.env), SystemState는 실시간 운영 상태

구현: `src/ante/config/system_state.py` 참조

### 동적 설정 변경 알림 흐름

```
WebAPI -> DynamicConfigService.update(key, value)
  -> SQLite UPDATE
  -> EventBus.publish(ConfigChangedEvent(key=..., old=..., new=...))
  -> 해당 모듈 핸들러가 설정 갱신
```

**근거**:
- 재시작 없이 즉시 반영 — 운영 중 룰 변경, 자금 재배분 등에 필수
- SQLite에 저장하므로 재시작 후에도 유지
- EventBus 알림으로 모듈이 능동적으로 반영 (폴링 불필요)

### Config 클래스

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `load` (classmethod) | config_dir: Path \| None | Config | 설정 파일 로드 및 인스턴스 생성. config_dir이 None이면 `resolve_config_dir()`로 자동 탐색 |
| `get` | key: str, default: Any | Any | 정적 설정 조회. 점(.) 구분자로 중첩 접근 |
| `secret` | key: str | str | 비밀값 조회. 환경변수 우선, 없으면 .env. 미존재 시 ConfigError |
| `validate` | — | None | 필수 설정 존재 여부 및 타입 검증 (Fail-fast) |

### resolve_config_dir()

설정 디렉토리를 탐색하는 유틸리티 함수.

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `override` | `Path \| None` | 명시적 지정 시 우선 사용 |

**탐색 우선순위**: override 인자 > `ANTE_CONFIG_DIR` 환경변수 > `~/.config/ante/` > `./config/`

**설계 포인트**:

1. **정적 설정은 점(.) 구분자로 중첩 접근** — `config.get("db.path")` → TOML의 `[db]` 섹션 내 `path` 키
2. **비밀값은 별도 메서드 (`secret()`)** — 호출부에서 비밀값임을 명시적으로 표현, 로깅 시 실수 방지, 미존재 시 즉시 예외
3. **동적 설정은 Config 클래스에 포함하지 않음** — `DynamicConfigService`가 별도로 CRUD + EventBus 알림 담당

구현: `src/ante/config/config.py` 참조

### DynamicConfigService

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | 스키마 생성 |
| `get` | key: str, default: Any = None | Any | 동적 설정 값 조회 (JSON 역직렬화). default가 None이고 키 미존재 시 ConfigError |
| `set` | key: str, value: Any, category: str, changed_by: str = "system" | None | 동적 설정 값 변경 + ConfigChangedEvent 발행. changed_by로 변경 주체 기록 |
| `delete` | key: str | bool | 동적 설정 삭제. 삭제 성공 시 True, 미존재 시 False |
| `get_all` | — | list[dict[str, Any]] | 모든 동적 설정 조회 (key, value, category, updated_at) |
| `get_by_category` | category: str | dict[str, Any] | 카테고리별 모든 설정 조회 |
| `register_default` | key: str, value: Any, category: str | None | 기본 설정값 등록. 해당 키가 이미 존재하면 무시 |
| `exists` | key: str | bool | 설정 존재 여부 확인 |
| `get_history` | key: str, limit: int = 50 | list[dict[str, Any]] | 설정 변경 이력 조회 |
| `cleanup_history` | retention_days: int = 90 | int | 오래된 변경 이력 정리. 삭제된 건수 반환 |

구현: `src/ante/config/dynamic.py` 참조

### 설정 유효성 검증

**접근 방식**: 로드 시점에 검증 (Fail-fast)

`Config.validate()`는 시스템 시작 시 호출되며, 필수 정적 설정(`db.path`, `parquet.base_path`, `web.port`)의 존재 여부와 타입을 검증한다. 검증 실패 시 모든 에러를 수집하여 `ConfigError`로 일괄 보고한다.

**근거**:
- 시작 시 전체 검증으로 런타임 에러 방지
- Pydantic Settings 도입은 현재 불필요 (설정 항목이 적고, 의존성 추가 대비 이점 부족)
- 향후 설정 항목이 크게 늘어나면 Pydantic 전환 검토

### 기본값 전략

| 키 | 기본값 |
|----|--------|
| `system.log_level` | `"INFO"` |
| `system.timezone` | `"Asia/Seoul"` |
| `db.path` | `"db/ante.db"` |
| `db.event_log_retention_days` | `30` |
| `parquet.base_path` | `"data/"` |
| `parquet.compression` | `"snappy"` |
| `web.host` | `"0.0.0.0"` |
| `web.port` | `3982` |
| `eventbus.history_size` | `1000` |
| `member.token_ttl_days` | `90` |
| `instrument.default_exchange` | `"KRX"` |
| `instrument.cache_ttl_seconds` | `3600` |
| `broker.commission_rate` | `0.00015` (Account 모델로 이관 예정) |
| `broker.sell_tax_rate` | `0.0023` (Account 모델로 이관 예정) |
| `broker.retry.max_retries_order` | `3` |
| `broker.retry.max_retries_query` | `2` |
| `broker.retry.max_retries_auth` | `2` |
| `broker.retry.backoff_base_seconds` | `1.0` |
| `broker.circuit_breaker.failure_threshold` | `5` |
| `broker.circuit_breaker.recovery_timeout` | `60` |
| `broker.timeout.order` | `10` |
| `broker.timeout.query` | `5` |
| `broker.timeout.auth` | `10` |
| `treasury.sync_interval_seconds` | `300` |
| `telegram.command.polling_interval` | `3.0` |
| `telegram.command.confirm_timeout` | `30.0` |

- TOML에 없는 항목은 기본값에서 가져옴
- 우선순위: TOML > DEFAULTS
- `system.toml`이 아예 없어도 기본값으로 시스템 시작 가능 (비밀값 제외)

구현: `src/ante/config/defaults.py` 참조

## §3 환경변수 (logging 관련)

| 환경변수 | 값 | 용도 | 기본값 |
|---|---|---|---|
| `ANTE_ENV` | `production` / `staging` / `qa` | JSONL 로그 레코드의 `env` 필드로 주입되어 환경 식별 | `production` |
| `ANTE_LOG_JSONL` | `1` / 미설정 | JSONL 파일 핸들러 활성화 게이트. 미설정 시 stdout 평문 핸들러만 동작 | 미설정 |

**세부 스펙**: [docs/specs/logging/](docs/specs/logging/) (JSON 스키마, 핸들러 구성, 회전 정책, Fingerprint 규칙 등)
