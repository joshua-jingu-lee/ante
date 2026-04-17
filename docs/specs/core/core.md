# Core 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/core/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성

## 개요

Core 모듈은 **모든 모듈이 공유하는 기반 인프라**를 제공한다.
시스템 전체에서 단일 인스턴스로 공유되며, 개별 도메인 모듈은 Core가 제공하는 계약에 따라 협력한다.

**주요 기능**:
- **Database**: SQLite WAL 모드 비동기 래퍼 — writer/reader 분리로 동시 읽기/쓰기 지원
- **Logging**: 표준 Python `logging` 기반 시스템 로그 인프라 — 평문 stdout + 구조화 JSONL 파일 이중 핸들러

## Database 인터페이스

### 생성자

```python
Database(db_path: str)
```

### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `connect` | — | None | DB 연결 초기화. writer + reader 두 연결 생성 |
| `close` | — | None | 모든 연결 종료 |
| `execute` | sql: str, params: tuple = () | None | INSERT/UPDATE/DELETE 실행 (writer 사용, 자동 커밋) |
| `fetch_one` | sql: str, params: tuple = () | dict \| None | 단일 행 조회 (reader 사용). dict(컬럼명 → 값) 반환 |
| `fetch_all` | sql: str, params: tuple = () | list[dict] | 다중 행 조회 (reader 사용) |
| `execute_script` | sql: str | None | DDL 스크립트 실행 (테이블 생성 등, writer 사용) |

### SQLite PRAGMA 설정

연결 초기화 시 다음 PRAGMA를 설정한다:

| PRAGMA | 값 | 설명 |
|--------|-----|------|
| `journal_mode` | WAL | Write-Ahead Logging — 동시 읽기/쓰기 지원 |
| `synchronous` | NORMAL | WAL 모드에서 안전한 성능 최적화 |
| `temp_store` | MEMORY | 임시 테이블을 메모리에 저장 |
| `foreign_keys` | ON | 외래 키 제약 활성화 |
| `busy_timeout` | 5000 | 잠금 대기 타임아웃 (밀리초) |

### 설계 근거

1. **Writer/Reader 분리**: 쓰기 작업은 writer 연결, 읽기 작업은 reader 연결을 사용하여 WAL 모드의 동시성 이점을 활용
2. **aiosqlite 래핑**: asyncio 기반 시스템에서 DB I/O가 이벤트 루프를 차단하지 않도록 비동기 래퍼 사용
3. **dict 반환**: `aiosqlite.Row`를 dict로 변환하여 모듈 간 데이터 전달을 단순화
4. **자동 커밋**: `execute()` 호출 시 자동 커밋으로 트랜잭션 관리 단순화

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## Logging 인터페이스

### 로그 3종 구분

Ante는 용도가 다른 세 종류의 "로그"를 별도로 관리한다. 본 절에서 설계하는 **시스템 로그**는 그중 운영 상태·에러 추적용이며, 다른 두 종류와 저장소·포맷이 분리된다.

| 종류 | 저장소 | 목적 | 정의 위치 |
|---|---|---|---|
| **시스템 로그** | stdout + 파일(JSONL) | 런타임 관찰, 에러 추적, 운영 진단 | 본 절 |
| **이벤트 로그** | SQLite `event_log` 테이블 | EventBus 도메인 이벤트 영속화 | [eventbus/eventbus.md](../eventbus/eventbus.md) |
| **감사 로그** | SQLite `audit_log` 테이블 | API 상태 변경 감사 추적 | [audit/audit.md](../audit/audit.md) |

시스템 로그가 이벤트·감사 로그와 교차하지 않는다. 도메인 이벤트 처리 중 발생한 예외는 시스템 로그에 기록되지만, 이벤트 자체의 페이로드는 이벤트 로그가 SSOT이다.

### 설계 결정

#### 1. JSONL 포맷 채택

에러·이상 징후를 자동으로 분석하고 집계할 주체(감시 에이전트, 외부 뷰어)가 평문을 재파싱하지 않도록 **JSON Lines**(한 줄에 한 JSON 객체)를 공식 파일 포맷으로 둔다.

**근거**:
- 1라인 = 1이벤트 → 스택 트레이스의 멀티라인 경계 모호함이 사라짐
- 필드 구조화 → `level=ERROR`, `account_id=paper01` 같은 조건 집계가 자연스럽다
- 표준 라이브러리 `json`만으로 파싱·생성 가능 — 외부 의존성 없음
- grep 호환성도 유지 (평문 대비 손해 없음)

#### 2. 이중 핸들러 — stdout 평문 / 파일 JSONL

개발자 경험과 자동 분석을 모두 만족하기 위해 두 핸들러를 병행한다.

| 핸들러 | 대상 | 포맷 | 용도 |
|---|---|---|---|
| `StreamHandler(sys.stdout)` | 콘솔 | 평문 (`%(asctime)s [%(levelname)s] %(name)s: %(message)s`) | 사람이 직접 관찰 |
| `TimedRotatingFileHandler` | `logs/ante-YYYY-MM-DD.jsonl` | JSONL | 에이전트·스크립트 분석 |

두 핸들러는 동일한 로그 레코드를 각자의 포맷으로 기록한다. 한쪽이 실패해도 다른 쪽은 유지된다.

#### 3. `ANTE_LOG_JSONL` 환경변수 게이트

파일 핸들러는 환경변수 `ANTE_LOG_JSONL=1`일 때만 활성화된다. 미설정(기본) 시 stdout 평문 핸들러만 동작하여 기존 운영 동작과 완전 호환한다.

**근거**: 스테이징·QA에서 먼저 사용해 안정성을 확인한 뒤 프로덕션에 점진 도입한다. 동작 회귀 없이 선택적 활성화가 가능하다.

#### 4. `ANTE_ENV` 환경 식별

로그 레코드의 `env` 필드는 환경변수 `ANTE_ENV`에서 주입된다. 기본값은 `production`, 스테이징은 `staging`, QA는 `qa`.

**근거**: 다중 환경이 동일한 이슈 추적 시스템·분석 도구를 공유할 때 환경 구분이 필수이다. 필드로 분리하여 후속 쿼리·필터링을 단순화한다.

### JSON 로그 스키마

#### 필수 필드 (모든 엔트리)

| 필드 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `ts` | string (ISO 8601 UTC) | `"2026-04-17T20:15:32.145Z"` | 타임존 독립 정렬·비교 |
| `level` | string | `"ERROR"` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `logger` | string | `"ante.broker.kis.adapter"` | Python logger 이름 (모듈 경로) |
| `msg` | string | `"주문 전송 실패"` | 주 메시지 (`logger.error(...)`의 첫 인자 치환 결과) |
| `env` | string | `"staging"` | `ANTE_ENV` 환경변수 값 |

#### 선택 컨텍스트 필드 (`extra={}`로 주입)

호출자가 `logger.error(msg, extra={...})` 형태로 주입한 값이 최상위 필드로 승격된다. 권장 키 목록:

| 필드 | 타입 | 사용 맥락 |
|---|---|---|
| `account_id` | string | Broker/Trade 경로 |
| `bot_id` | string | 봇 수명주기 |
| `strategy_id` | string | 전략 실행 |
| `order_id` | string | 주문 흐름 추적 |
| `symbol` | string | 종목 관련 |
| `request_id` | string | Web API 요청 |
| `extra` | object | 모듈 특수 정보 (표준 필드에 들지 않는 자유 객체) |

표준 필드와 중복되는 키(`ts`, `level`, `logger`, `msg`, `env`, `exc`)는 `extra=`로 주입해도 무시된다.

#### Exception 필드 (예외 포함 시)

`logger.exception()` 또는 `logger.error(..., exc_info=True)` 호출 시 Formatter가 자동 생성한다.

```json
{
  "exc": {
    "type": "ConnectionError",
    "message": "WebSocket closed unexpectedly",
    "traceback": "Traceback (most recent call last):\n  ...",
    "fingerprint": "ConnectionError@ante.broker.kis_stream:handle_reconnect"
  }
}
```

| 필드 | 설명 |
|---|---|
| `exc.type` | 예외 클래스명 |
| `exc.message` | `str(exception)` |
| `exc.traceback` | `traceback.format_exception()` 결과 (단일 문자열, JSON 이스케이프) |
| `exc.fingerprint` | 같은 에러를 식별하는 안정 키 (다음 절 참조) |

### Fingerprint 규칙

같은 근본 원인의 반복 발생을 묶기 위한 식별자.

**생성 방식**: `{exception class}@{스택에서 가장 최근의 ante.* 프레임 module:function}`

| 조건 | Fingerprint 예시 |
|---|---|
| `ante.broker.kis_stream.handle_reconnect` 내부에서 `ConnectionError` | `ConnectionError@ante.broker.kis_stream:handle_reconnect` |
| 스택에 `ante.*` 프레임이 없음 (로거만 호출) | `{exception class}@{logger 이름}` (폴백) |

**주의**:
- 라인번호는 포함하지 않는다 (리팩터링 저항).
- 표준 라이브러리/외부 라이브러리 프레임은 건너뛰고 `ante.*`의 최상단 호출 지점을 선택한다.
- Fingerprint는 GitHub 이슈 dedup 키로 사용된다 (`docs/specs/` 외부 — 감시 에이전트 계약).

### 핸들러 구성과 회전 정책

| 항목 | 값 | 근거 |
|---|---|---|
| stdout 핸들러 레벨 | `system.log_level` (기본 INFO) | [config/03-design-decisions.md](../config/03-design-decisions.md) §1 |
| 파일 핸들러 레벨 | 동일 | 두 핸들러가 같은 레코드를 본다 |
| 파일명 | `logs/ante-YYYY-MM-DD.jsonl` | 날짜 기반 자연 정렬 |
| 회전 | `TimedRotatingFileHandler(when="midnight", utc=False)` | Asia/Seoul 자정 기준 |
| 보관 | 30일 | 감시 에이전트의 과거 패턴 분석 최소 기간 |
| 3일 이후 | gzip 압축 (`*.jsonl.gz`) | 디스크 절약, `zcat`으로 검색 가능 |
| 디렉토리 | 컨테이너 `/app/logs` (named volume 또는 bind mount) | 재시작 시 보존 |

### 컨텍스트 필드 주입 패턴

기존 호출부는 변경 없이 유지한다. 새로 작성하거나 중요한 경로에만 `extra=`를 선택적으로 도입한다.

```python
# Before (기존, 그대로 동작)
logger.error("주문 전송 실패: code=%d", code)

# After (선택적 보강 — 필드 분리 분석이 필요한 경우)
logger.error(
    "주문 전송 실패",
    extra={"account_id": account_id, "order_id": order_id, "code": code},
)
```

JSON 출력 예:

```json
{"ts":"2026-04-17T20:15:32.145Z","level":"ERROR","logger":"ante.broker.kis","msg":"주문 전송 실패","env":"staging","account_id":"paper01","order_id":"ord-123","extra":{"code":403}}
```

**가이드**:
- 표준 필드(`account_id`, `bot_id` 등)는 최상위 키로 주입한다.
- 모듈 특수 정보는 `extra={"extra": {...}}`에 중첩한다.
- 민감값(토큰, 비밀번호, 계좌번호 원본)은 절대 주입하지 않는다. 필요하면 마스킹 후 주입한다.

### 구현 위치

| 자산 | 경로 | 역할 |
|---|---|---|
| `JsonFormatter` | `src/ante/core/log/formatter.py` (신설) | `logging.Formatter` 상속, `format()`이 위 스키마에 따라 JSON 직렬화 |
| `setup_logging()` | `src/ante/core/log/setup.py` (신설) | 핸들러 구성 함수. `main.py`가 `_init_core`에서 호출 |
| 통합 지점 | `src/ante/main.py` | 기존 `logging.basicConfig(...)`을 `setup_logging(config)`으로 교체 |

`src/ante/log/`가 아닌 `src/ante/core/log/`에 두는 이유: 표준 라이브러리 `logging`과 이름이 충돌하지 않는 네임스페이스를 보장하면서, Core 모듈(공통 인프라)의 자산임을 경로로 명시한다.

### 설계 근거

1. **표준 라이브러리 기반**: `logging.Handler`·`Formatter` 계약을 그대로 사용하여 외부 의존성(`structlog`, `python-json-logger` 등) 없이 구현한다. 모든 모듈이 이미 `logging.getLogger(__name__)` 패턴으로 통일되어 있어 호출부 수정이 불필요하다.
2. **점진 도입 가능**: `ANTE_LOG_JSONL` 게이트로 전역 영향 없이 개별 환경에서 검증 후 확산한다. 기존 프로덕션은 미설정 상태로 회귀 위험이 0.
3. **관심사 분리**: 시스템 로그가 이벤트·감사 로그와 완전히 독립된 파이프라인을 갖는다. 각 종류의 변경이 서로 영향을 주지 않는다.
4. **Fingerprint 안정성**: 라인번호 배제·최상위 앱 프레임 선택으로 리팩터링 저항성을 확보한다. 같은 근본 원인이 여러 위치에서 기록되어도 동일 키로 묶인다.

### 미결 사항

- [ ] `JsonFormatter` 초기 구현 (`src/ante/core/log/formatter.py`) 및 단위 테스트
- [ ] `setup_logging()` 구현 및 `main.py` 통합, 회귀 테스트 (`ANTE_LOG_JSONL` 미설정 시 기존 동작 유지)
- [ ] [config/03-design-decisions.md](../config/03-design-decisions.md)에 `ANTE_ENV`, `ANTE_LOG_JSONL` 환경변수 문서화
- [ ] 주요 에러 경로(`ante.broker.*`, `ante.bot.*`, `ante.web.*`)에 `extra={}` 컨텍스트 필드 점진 보강 — 후속 이슈로 분리
- [ ] Fingerprint 생성 시 `ante.*` 프레임 탐색 구현 세부(프레임 필터, 재귀 한계) 확정

## 시스템 초기화 순서

모듈 간 의존 관계에 따라 다음 순서로 초기화한다:

```
1. Config.load() + Config.validate()     # 정적 설정 로드 + 검증
2. Database 초기화                        # SQLite 연결, WAL 모드 설정
3. EventBus 초기화
4. AccountService 초기화                  # DB + EventBus 주입, 기존 Account 로드
5. DynamicConfigService 초기화            # DB + EventBus 주입
6. TreasuryManager 초기화                 # 계좌별 Treasury 생성
7. TradeService 초기화                    # DB + EventBus (PositionHistory, TradeRecorder, PerformanceTracker)
8. RuleEngineManager 초기화               # 계좌별 RuleEngine 생성 (Config + DynamicConfig + EventBus + AccountService)
9. APIGateway 초기화                      # AccountService 주입, 계좌별 BrokerAdapter 라우팅
10. BotManager 초기화                      # EventBus + StrategyRegistry + APIGateway factories
11. NotificationService 초기화             # EventBus + 알림 어댑터
12. WebAPI 시작                           # FastAPI (모든 서비스 주입)
13. BotManager.restore_bots()             # DB에서 봇 설정 복원 + 시작
```

## 이벤트 버스 연동 (EventBus Integration)

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `AccountSuspendedEvent` | 계좌 거래 중단 시 (Account.status → SUSPENDED) | BotManager (해당 계좌 봇 중지), 로깅 |
| `AccountActivatedEvent` | 계좌 거래 재개 시 (Account.status → ACTIVE) | BotManager (해당 계좌 봇 재개), 로깅 |
| `NotificationEvent` | 계좌 상태 변경, 시스템 시작/종료 시 | NotificationService → Telegram 어댑터 (category: "system") |

## 알림 이벤트 정의 (Notification Events)

### 1. 계좌 상태 변경 (계좌별 킬 스위치)

> 소스: `src/ante/account/service.py` — AccountService

**트리거**: 계좌 거래 상태가 변경될 때 (ACTIVE ↔ SUSPENDED)

**데이터 수집**:
- `account_id` → 대상 계좌
- `old_status`, `new_status` → 상태 전환 정보
- `reason` → 변경 사유 (일일 손실 한도 초과, 사용자 요청 등)

**발행 메시지**:

```
level: critical
title: 계좌 상태 변경
category: system

계좌: {account_id}
{old_status} → *{new_status}*
사유: {reason}
```

### 2. 시스템 시작

> 소스: `src/ante/main.py` — _run()

**트리거**: Ante 시스템 초기화가 완료되고 종료 시그널 대기 상태에 진입할 때

**데이터 수집**: 없음 (고정 메시지)

**발행 메시지**:

```
level: info
title: 시스템 시작
category: system

Ante 시스템이 시작되었습니다.
```

### 3. 시스템 종료

> 소스: `src/ante/main.py` — _shutdown()

**트리거**: 종료 시그널(SIGTERM/SIGINT)을 수신하여 시스템 종료 절차가 시작될 때

**데이터 수집**: 없음 (고정 메시지)

**발행 메시지**:

```
level: info
title: 시스템 종료
category: system

Ante 시스템이 종료됩니다.
```

## 미결 사항

- [x] 알림 메시지 발행 — `main.py`(시작/종료), AccountService(계좌 상태 변경)에서 NotificationEvent 직접 발행 구현 완료 (category: "system")
- [ ] `SystemStartedEvent` 신규 생성 ([#539](https://github.com/joshua-jingu-lee/ante/issues/539)) — `eventbus/events.py`에 이벤트 정의 + `main.py`에서 시스템 시작 완료 시 발행. `restore_bots()` 구현 시 자동 재개 봇 수 페이로드 반영
- [ ] 텔레그램 `/halt` 응답 메시지 스펙 적용 ([#540](https://github.com/joshua-jingu-lee/ante/issues/540)) — 계좌별 정지로 변경. 에픽: [#531](https://github.com/joshua-jingu-lee/ante/issues/531)
- [ ] 텔레그램 `/activate` 응답 메시지 스펙 적용 ([#541](https://github.com/joshua-jingu-lee/ante/issues/541)) — 계좌별 활성화로 변경. 에픽: [#531](https://github.com/joshua-jingu-lee/ante/issues/531)
- [ ] `AccountService.suspend()`에 `suppress_notification` 파라미터 추가 ([#517](https://github.com/joshua-jingu-lee/ante/issues/517)) — `True`이면 NotificationEvent 발행을 생략. 에픽: [#515](https://github.com/joshua-jingu-lee/ante/issues/515)

**`/halt` 응답 메시지 — 결과 분기:**

| 조건 | 응답 |
|------|------|
| 성공 (ACTIVE → SUSPENDED) | 아래 메시지 |
| 이미 중지됨 | `이미 거래가 중지된 상태입니다. (계좌: {account_id})` |

```
🚨 계좌 거래가 중지되었습니다.
계좌: {account_id}
사유: {reason}
해제하려면 /activate {account_id} 를 입력하세요.
```

**`/activate` 응답 메시지 — 결과 분기:**

| 조건 | 응답 |
|------|------|
| 성공 (SUSPENDED → ACTIVE) | `✅ 계좌 거래가 재개되었습니다. (계좌: {account_id})` |
| 이미 활성 | `이미 거래가 활성 상태입니다. (계좌: {account_id})` |
