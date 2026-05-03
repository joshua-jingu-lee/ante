# Config 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 설계 결정

### 계층별 역할

#### 1. 정적 설정 — TOML 파일 (`<config_dir>/system.toml`)

시스템 인프라 수준의 설정으로, 변경 시 재시작 필요.

```toml
[system]
log_level = "INFO"
timezone = "Asia/Seoul"

[db]
path = "db/ante.db"
event_log_retention_days = 30

[data]
path = "data"

[runtime]
pid_path = "run/ante.pid"
socket_path = "run/ante.sock"

[logging]
directory = "logs"

[parquet]
compression = "snappy"

[web]
host = "0.0.0.0"
port = 3982
cors_origins = ["http://localhost:3000"]

# [broker] 섹션의 계좌성 값은 Account 모델로 이관됨.
# broker.type → Account.broker_type
# broker.commission_rate → Account.buy_commission_rate
# broker.commission_rate + broker.sell_tax_rate → Account.sell_commission_rate
# broker.kis.* 또는 secrets.env의 KIS_* → Account.credentials JSON으로 암호화 저장.
# 상세 mapping은 docs/specs/account/08-config-migration.md를 따른다.
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
- Ante는 Python 3.13 표준 라이브러리 `tomllib`로 TOML을 파싱한다 — 외부 의존성 없음
- 사람이 읽기/편집 용이 (JSON보다 코멘트 지원, YAML보다 파싱 안정적)
- FreqTrade의 JSON 방식은 코멘트 불가, NautilusTrader의 YAML은 보안 이슈(arbitrary code execution) 가능

#### 2. 비밀값 — `.env` 파일 (`<config_dir>/secrets.env`)

API 키, 토큰 등 민감 정보. gitignore 대상.

```env
# 한국투자증권 API — legacy migration input 예시
# 이관 후에는 Account.credentials JSON으로 암호화 저장한다.
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
| `rule.max_daily_loss_rate` | trading | 일일 누적 손실 한도 기본값. 계좌별 룰이 없을 때 seed로 사용 가능 | `0.03` |
| `rule.max_total_exposure` | trading | 최대 총 노출 비율 기본값. 계좌별 룰이 없을 때 seed로 사용 가능 | `0.30` |

*계좌별 룰 (RuleEngine이 런타임 재로드)*:

| 키 | 카테고리 | 설명 | 예시 값 |
|----|---------|------|--------|
| `accounts.{account_id}.rules` | rule | 계좌별 리스크 룰 리스트. 런타임 룰 변경의 SSOT | `[{"type":"daily_loss_limit","enabled":true,"max_daily_loss_rate":0.03,"action":"halt"}]` |

계좌별 룰은 per-rule key로 나누지 않는다. `PUT /api/accounts/{account_id}/rules/{rule_type}`는
해당 rule만 수정하더라도 `accounts.{account_id}.rules` 리스트 전체를 갱신하고,
`ConfigChangedEvent(category="rule", key="accounts.{account_id}.rules")`를 발행한다.
정적 TOML의 `accounts.{account_id}.rules`는 초기 seed/fallback으로만 사용한다.

*전략별 룰 (RuleEngine/BotManager가 참조)*:

| 키 | 카테고리 | 설명 | 예시 값 |
|----|---------|------|--------|
| `rules.strategy.{strategy_id}` | strategy_rule | 전략별 룰 리스트. 봇 시작/전략 룰 갱신 시 로드 | `[{"type":"position_size","enabled":true,"max_position_percent":0.1}]` |

*자금 관리 (Treasury가 참조)*:

| 키 | 카테고리 | 설명 | 예시 값 |
|----|---------|------|--------|
| `treasury.bot_{id}.allocation` | treasury | 봇별 자금 할당 한도. 봇이 사용 가능한 최대 자금 | `5000000` |

*알림 (NotificationAdapter가 참조)*:

| 키 | 카테고리 | 설명 | 예시 값 |
|----|---------|------|--------|
| `notification.telegram_enabled` | notification | 텔레그램 알림 발송 활성화 여부. `false`이면 CRITICAL 외 알림을 발송하지 않음 | `"true"` |
| `notification.min_level` | notification | 최소 발송 레벨. 허용 값: `critical`, `error`, `warning`, `info` | `"info"` |
| `notification.quiet_hours` | notification | `HH:MM-HH:MM` 형식의 알림 무음 시간대. 이 시간에는 CRITICAL 외 알림을 발송하지 않음 | `"23:00-07:00"` |

`notification.enabled`는 사용하지 않는다. 1.0의 알림 채널은 Telegram 단일 채널이므로
런타임 토글 키는 `notification.telegram_enabled`로 고정한다.
`notification.telegram_level`, `notification.fill_alert`, `notification.on_fill`,
`notification.daily_report` 같은 세부 알림 정책 키는 1.0 계약에 포함하지 않는다.
채널 토글, 최소 레벨, 무음 시간대만 표준 설정으로 둔다.
`notification.quiet_hours`는 값이 없거나 빈 문자열이면 비활성화된다. 잘못된 형식도
무음 시간대 비활성으로 처리하고, 알림 서비스는 경고 로그만 남긴다.
NotificationService는 시작 시 세 키를 읽고, 이후
`ConfigChangedEvent(key="notification.telegram_enabled")`와
`ConfigChangedEvent(key="notification.min_level")`,
`ConfigChangedEvent(key="notification.quiet_hours")`를 구독하여 재시작 없이 반영한다.
CRITICAL 알림은 `telegram_enabled=false`, `min_level`, `quiet_hours`를 모두 우회한다.

> **참고 — 킬 스위치(Trading State)**는 `dynamic_config`와 별도 `system_state`
> 테이블에 포함하지 않는다. 거래 가능 상태의 SSOT는 Account 모듈의
> `Account.status`이며, 값은 `ACTIVE` / `SUSPENDED` / `DELETED`다.
> `ante system halt`는 모든 ACTIVE 계좌를 SUSPENDED로 전환하는 편의 명령이고,
> `ante system clear-halt`는 모든 SUSPENDED 계좌를 ACTIVE로 복구한다 (계좌 상태만 복구하며 봇을 자동 재시작하지 않는다).
> 상태 변경 이벤트는 `TradingStateChangedEvent`가 아니라
> `AccountSuspendedEvent` / `AccountActivatedEvent`를 사용한다.

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

### 1.0 단일 active runtime 정책

Ante 1.0은 동일 OS user/home server 기준으로 **단일 active runtime server만**
공식 지원한다. `config_dir`은 데이터/설정 프로필 경계이지 동시 namespace가 아니다.
즉, 서로 다른 `config_dir`을 사용해도 같은 호스트에서 두 개의 Ante runtime을
동시에 실행하는 구성은 1.0의 보증 범위 밖이다.

이 정책은 cold-path CLI 명령(`ante account create/delete/set-credentials`)의
차단 기준에 직접 영향을 준다. CLI는 "active Ante runtime guard"로 서버 실행
여부를 판정하며, runtime이 살아 있으면 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER`로
종료한다. 같은 OS user에서 다중 runtime이 필요하다면 별도 인스턴스 분리/스케줄링은
1.x 후속 결정 사항으로 분리한다.

`runtime.pid_path` / `runtime.socket_path` 도입에 따라 legacy cwd-relative
`db/ante.pid` 경로의 read-fallback은 두지 않는다 (#1157). canonical PID 파일이
부재하면 server는 "running" 판정을 받지 않으며, 기존 환경에서 업그레이드는
`ante system stop` 후 PR을 적용하는 흐름을 표준 시나리오로 한다. legacy 파일이
잔존하면 `_remove_pid_file`이 canonical 정리 시 best-effort로 함께 unlink한다.

### Ante instance/path contract

Ante 인스턴스의 루트는 `config_dir`이다. `system.toml`이 있는 디렉토리와
`config_dir`은 같은 경계이며, 서버 프로세스·CLI·IPC·migration은
같은 `config_dir`을 공유할 때 같은 Ante 인스턴스를 바라본다.

**경로 해석 규칙**:

1. `system.toml` 안의 상대 경로는 모두 `config_dir` 기준으로 해석한다.
2. 호출 시점의 CWD는 인스턴스 경계나 정적 설정 경로의 기준이 아니다.
3. `ante init`은 상대 경로 기본값을 기록하고, resolver가 절대 경로로 정규화한다.
4. 명시적 CLI override(`--db-path`, `--data-path`)는 해당 커맨드의 작업 대상만 바꾸며, 인스턴스 인증 DB나 서버 프로세스 경계를 바꾸지 않는다. 인스턴스를 바꾸려면 `--config-dir` 또는 `ANTE_CONFIG_DIR`을 사용한다.

**Canonical resource table**:

| 리소스 | 설정 키/위치 | 기본값 | 정규화 결과 |
|---|---|---|---|
| Instance root | `config_dir` | `~/.config/ante/` | `config_dir` 자체 |
| 정적 설정 | `<config_dir>/system.toml` | — | `<config_dir>/system.toml` |
| 비밀값 | `<config_dir>/secrets.env` | — | `<config_dir>/secrets.env` |
| Canonical DB | `db.path` | `db/ante.db` | `<config_dir>/db/ante.db` |
| Data root | `data.path` | `data` | `<config_dir>/data` |
| PID file | `runtime.pid_path` | `run/ante.pid` | `<config_dir>/run/ante.pid` |
| IPC socket | `runtime.socket_path` | `run/ante.sock` | `<config_dir>/run/ante.sock` |
| System logs | `logging.directory` | `logs` | `<config_dir>/logs` |
| DataFeed workspace | derived from `data.path` | `.feed/` | `<config_dir>/data/.feed/` |

`db.path`는 서버 DB, CLI 인증 DB, CLI 작업 DB의 기본값, migration DB, EventHistoryStore,
AuditLogger가 공유하는 canonical DB이다. 예외적으로 다른 DB를 볼 수 있는 명령은
`--db-path` 같은 명시적 작업 DB override 계약을 가져야 한다.

`data.path`는 ParquetStore와 DataFeed가 공유하는 canonical data root이다.
과거 `parquet.base_path`는 legacy alias로만 취급한다. `data.path`가 없고
`parquet.base_path`만 있는 기존 설정은 `data.path`로 이관해 해석할 수 있지만, 둘이
동시에 있으면 `data.path`가 우선하며 검증 경고를 낸다.

### Config 클래스

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `load` (classmethod) | config_dir: Path \| None | Config | 설정 파일 로드 및 인스턴스 생성. config_dir이 None이면 `resolve_config_dir()`로 자동 탐색 |
| `get` | key: str, default: Any | Any | 정적 설정 조회. 점(.) 구분자로 중첩 접근 |
| `resolve_path` | key: str, default: str \| None = None | Path | path-like 정적 설정을 `config_dir` 기준의 절대 경로로 정규화 |
| `secret` | key: str | str | 비밀값 조회. 환경변수 우선, 없으면 .env. 미존재 시 ConfigError |
| `validate` | — | None | 필수 설정 존재 여부 및 타입 검증 (Fail-fast) |

### resolve_config_dir()

설정 디렉토리를 탐색하는 유틸리티 함수.

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `override` | `Path \| None` | 명시적 지정 시 우선 사용 |

**탐색 우선순위**: override 인자 > `ANTE_CONFIG_DIR` 환경변수 > `~/.config/ante/` > `./config/`

**설계 포인트**:

1. **정적 설정은 점(.) 구분자로 중첩 접근** — `config.get("db.path")` → TOML의 `[db]` 섹션 내 `path` 키. path-like 설정을 사용할 때는 raw 문자열을 직접 조합하지 않고 `resolve_path()` 계열 resolver를 거친다.
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

`Config.validate()`는 시스템 시작 시 호출되며, 필수 정적 설정(`db.path`, `data.path`, `web.port`)의 존재 여부와 타입을 검증한다. 검증 실패 시 모든 에러를 수집하여 `ConfigError`로 일괄 보고한다.

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
| `data.path` | `"data"` |
| `runtime.pid_path` | `"run/ante.pid"` |
| `runtime.socket_path` | `"run/ante.sock"` |
| `logging.directory` | `"logs"` |
| `parquet.compression` | `"snappy"` |
| `web.host` | `"0.0.0.0"` |
| `web.port` | `3982` |
| `eventbus.history_size` | `1000` |
| `member.token_ttl_days` | `90` |
| `instrument.default_exchange` | `"KRX"` |
| `instrument.cache_ttl_seconds` | `3600` |
| `broker.commission_rate` | legacy source. Account `buy_commission_rate` 및 `sell_commission_rate` 산정에 사용 |
| `broker.sell_tax_rate` | legacy source. Account `sell_commission_rate` 산정에 합산 |
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
| `notification.telegram_enabled` | `"true"` |
| `notification.min_level` | `"info"` |

- TOML에 없는 항목은 기본값에서 가져옴
- 우선순위: TOML > DEFAULTS
- `system.toml`이 아예 없어도 기본값으로 시스템 시작 가능 (비밀값 제외)
- `notification.quiet_hours`는 기본값을 시드하지 않는다. 키가 없거나 값이 비어 있으면 무음 시간대 비활성으로 해석한다.

구현: `src/ante/config/defaults.py` 참조

## §3 환경변수 (logging 관련)

| 환경변수 | 값 | 용도 | 기본값 |
|---|---|---|---|
| `ANTE_ENV` | `production` / `staging` / `test` | JSONL 로그 레코드의 `env` 필드로 주입되어 환경 식별 | `production` |
| `ANTE_LOG_JSONL` | `1` / 미설정 | JSONL 파일 핸들러 활성화 게이트. 미설정 시 stdout 평문 핸들러만 동작 | 미설정 |

**세부 스펙**: [docs/specs/logging/](../logging/) (JSON 스키마, 핸들러 구성, 회전 정책, Fingerprint 규칙 등)
