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

Ante의 시스템 로그(운영 상태·에러 추적)는 표준 Python `logging` 기반 공통 인프라로 제공된다. JSONL 파일 핸들러, Exception Fingerprint, 환경 게이트, 회전 정책 등 세부 설계는 분할 스펙을 참조한다.

**세부 스펙**: [logging/README.md](logging/README.md)

**요약**:
- 이중 핸들러 — stdout 평문(사람) + 파일 JSONL(자동 분석)
- `ANTE_LOG_JSONL=1` 환경변수 게이트로 점진 도입
- `ANTE_ENV`로 환경 식별 (`production` / `staging` / `qa`)
- 이벤트 로그([eventbus](../eventbus/eventbus.md))·감사 로그([audit](../audit/audit.md))와 완전 분리

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
