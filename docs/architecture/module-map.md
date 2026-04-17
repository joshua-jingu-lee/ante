# Ante 모듈 구성과 책임

> 인덱스: [README.md](README.md) | 런타임 구조: [system-diagram.md](system-diagram.md)

## 모듈 구성

### 1. EventBus
- **역할**: 핵심 이벤트의 발행/구독 관리
- **구현**: asyncio.Queue 기반
- **설계**: publish(event) / subscribe(event_type, handler)
- 상세 설계: [specs/eventbus/eventbus.md](../specs/eventbus/eventbus.md)

### 2. BotManager
- **역할**: 봇 생명주기 관리, asyncio.Task 풀 운영
- **봇 유형**: 실전투자 봇 / 모의투자 봇 (가상 자금)
- **실행 모드**: 실시간, 스케줄링, 혼합
- **생명주기**: 생성 -> 전략 로드 -> 활성화 -> 운영 -> 중지
- **예외 격리**: 각 봇의 Task에서 예외 발생 시 해당 봇만 중지, 타 봇 무영향
- 상세 설계: [specs/bot/bot.md](../specs/bot/bot.md)

### 3. 거래 룰 엔진 (Rule Engine)
- **역할**: 2중 룰 구조로 주문 검증
- **전역 룰**: 시스템 레벨, 모든 봇에 강제 적용
- **전략별 룰**: 각 봇/전략이 자체 보유, 전역 룰 범위 내에서만 유효
- **동작**: OrderRequestEvent 구독 -> 검증 -> OrderValidatedEvent 또는 거래 차단
- 상세 설계: [specs/rule-engine/rule-engine.md](../specs/rule-engine/rule-engine.md)

### 4. 자금 관리 (Treasury)
- **역할**: 전체 잔고 중앙 관리, 봇별 자금 할당
- **기능**: 자금 배분, 가용자금 추적, 봇 중지 조건 판단
- **호출 방식**: EventBus(주문 승인 흐름) + 직접 호출(잔고 조회)
- 상세 설계: [specs/treasury/treasury.md](../specs/treasury/treasury.md)

### 5. API 요청 관리 (API Gateway)
- **역할**: 복수 봇의 API 요청을 중간에서 관리
- **기능**: 요청 큐잉, 캐싱, Rate Limit 준수, 중복 요청 병합
- **구현**: Token Bucket + Priority Queue
- 상세 설계: [specs/api-gateway/api-gateway.md](../specs/api-gateway/api-gateway.md)

### 6. 증권사 연동 모듈 (Broker Adapter)
- **역할**: 증권사 API와의 통신을 추상화
- **설계**: 공통 인터페이스 정의, 증권사별 구현체로 분리
- **초기 구현**: 한국투자증권 (KIS)
- **대사(Reconciliation)**: Reconciler가 브로커 실제 데이터와 로컬 데이터를 비교·보정 (봇 시작 시 + 주기적)
- 상세 설계: [specs/broker-adapter/broker-adapter.md](../specs/broker-adapter/broker-adapter.md)

### 7. 데이터 저장소 (DataStore)
- **역할**: 시세·재무 데이터의 저장·정규화·조회·관리를 담당하는 유일한 Parquet 접근 계층
- **ParquetStore**: Parquet 파일 읽기/쓰기/검증 (모든 데이터 쓰기는 이 계층을 경유)
- **Normalizer**: 모든 소스(KIS, Yahoo, DataGoKr, DART 등)의 데이터를 통일 스키마로 정규화
- **Collector**: 봇 운영 중 APIGateway 경유 실시간 시세 수집 → ParquetStore 적재
- **Injector**: 외부 소스(CSV 등)에서 과거 데이터 수동 주입
- **Catalog**: 보유 데이터 탐색 (CLI `ante data list/schema`)
- **Retention**: 보존 정책 기반 용량 관리 (60GB 제약 대응)
- **호출 방식**: 직접 호출(데이터 조회) + EventBus(새 데이터 도착 알림)
- 상세 설계: [specs/data-pipeline/data-pipeline.md](../specs/data-pipeline/data-pipeline.md)

### 8. 데이터 피드 (DataFeed)
- **역할**: 외부 공공 API에서 과거 시세·재무 데이터를 배치 수집하는 ETL 파이프라인
- **저장**: 자체 Parquet 구현 없이 DataStore의 ParquetStore를 통해 저장
- **정규화**: DataStore의 Normalizer를 사용 (DataGoKrNormalizer, DARTNormalizer)
- **자체 책임**: 외부 API 어댑터(sources/), 데이터 검증(validate), 타임프레임 합성(synthesize), 오케스트레이션(pipeline/), 체크포인트, 리포트
- **수집 소스**: data.go.kr (OHLCV+시가총액+상장주식수), DART (재무제표), pykrx (백업/수급)
- **실행 모드**: `ante feed start` (내장 스케줄러 상주), `ante feed run backfill/daily` (one-shot)
- **활성화**: `pip install ante`에 항상 포함, `ante feed init`으로 활성화 전까지 비활성
- **설정**: `{data}/.feed/config.toml` (수집 대상, 스케줄, 가드, 라우팅) + 환경변수 (API 키)
- **장애 대응**: 재시도 (Exponential Backoff), 체크포인트, 실패 스킵, 리포트 생성
- **BrokerAdapter와의 관계**: DataFeed는 증권사 API(KIS)를 사용하지 않으며 APIGateway를 경유하지 않는다. 공공 데이터 API 전용 Rate Limiter를 자체 보유한다.
- 상세 설계: [specs/data-feed/data-feed.md](../specs/data-feed/data-feed.md)

### 9. 백테스트 엔진 (Backtest Engine)
- **역할**: 백데이터 기반 전략 검증
- **실행**: 메인 프로세스와 별도 subprocess로 격리
- **입출력**: 전략+설정 인자 전달, DataStore(ParquetStore) 경유 데이터 읽기, 결과 파일/DB 기록
- **완료 통지**: 메인 프로세스에 BacktestCompleteEvent 발행
- **설계 고려**: 벡터화 연산으로 N100 환경 대응
- 상세 설계: [specs/backtest/backtest.md](../specs/backtest/backtest.md)

### 10. 거래 기록 및 성과 추적 (Trade)
- **역할**: 모든 거래의 실행 기록을 영속 저장하고, 봇/전략 단위 성과 지표 산출
- **기능**: 거래 기록 (체결/취소/거부/실패), 포지션 변동 추적, 성과 지표 계산 (승률, MDD, 수익팩터 등)
- **동작**: OrderFilledEvent 등 주문 흐름 이벤트를 구독하여 자동 기록
- **저장**: SQLite (trades, positions, position_history 테이블)
- 상세 설계: [specs/trade/trade.md](../specs/trade/trade.md)

### 11. 전략 모듈 (Strategy)
- **역할**: 전략 등록·검증·로드를 관리
- **StrategyRegistry**: 전략 파일 검색, 클래스 로드, 봇에 전략 공급
- **StrategyValidator**: AST 기반 정적 검증 (금지 임포트, 필수 구조 확인)
- **StrategyContext**: 전략이 사용하는 데이터 조회·주문 API (샌드박스)
- 상세 설계: [specs/strategy/strategy.md](../specs/strategy/strategy.md)

### 12. 결재 (Approval)
- **역할**: Agent의 요청을 사용자가 승인·거절하는 의사결정 체계
- **기능**: 결재 요청 생성, 조회, 승인/거절/보류 처리, 승인 시 자동 실행
- **요청 유형**: 전략 채택, 예산 변경, 봇 생성/중지, 규칙 변경 등
- **동작**: 요청 생성 시 NotificationEvent 발행 → 사용자 승인 시 해당 동작 즉시 반영
- **참고**: 사용자는 Dashboard에서 결재 없이 직접 동일 작업을 수행할 수 있다 (대표 권한)
- 상세 설계: [specs/approval/approval.md](../specs/approval/approval.md)

### 13. 전략 리포트 저장소 (Strategy Report Store)
- **역할**: Agent가 생성한 전략 리포트 축적/관리. 결재(Approval)의 근거 자료로 참조된다.
- **기능**: 리포트 저장, 조회
- 상세 설계: [specs/report-store/report-store.md](../specs/report-store/report-store.md)

### 14. 웹 대시보드 (Web Dashboard)
- **역할**: 사용자의 주요 인터페이스
- **기능**: 봇 상태/수익 확인, 리포트 열람/채택, 봇 생성/전략 로드/활성화
- **구현**: FastAPI (같은 프로세스 내에서 EventBus 상태 조회)
- 상세 설계: [specs/web-api/web-api.md](../specs/web-api/web-api.md) (백엔드 API), [dashboard/architecture.md](../dashboard/architecture.md) (프론트엔드)

### 15. 알림 모듈 (Notification Adapter)
- **역할**: 외부 알림 발송
- **설계**: 증권사 모듈과 동일하게 공통 인터페이스 + 구현체 분리
- **동작**: NotificationEvent 구독 -> 알림 발송
- **초기 구현**: Telegram
- 상세 설계: [specs/notification/notification.md](../specs/notification/notification.md)

### 16. 종목 관리 (Instrument)
- **역할**: 종목 마스터 데이터 중앙 관리
- **기능**: 종목 메타데이터(코드, 이름, 유형) 등록·조회, 메모리 캐시(TTL 기반)
- **설계**: (symbol, exchange) 복합 PK, 전체 종목 메모리 캐시 + SQLite 영속화
- 상세 설계: [specs/instrument/instrument.md](../specs/instrument/instrument.md)

### 17. 멤버 관리 (Member)
- **역할**: 시스템 행위자(사용자·AI Agent) 등록·인증·권한 관리
- **설계**: human/agent 타입 분리, 역할 기반 접근 제어(RBAC), master는 human 1명만
- **기능**: 멤버 등록/비활성화, 타입별 토큰 인증, Recovery Key 기반 복구
- 상세 설계: [specs/member/member.md](../specs/member/member.md)

### 18. 감사 로그 (Audit)
- **역할**: 멤버 액션의 감사 로그 기록·조회
- **기능**: 누가·언제·무엇을 했는지 추적 (member_id, action, resource, detail, ip)
- **동작**: 각 모듈에서 AuditLogger.log() 호출
- 상세 설계: [specs/audit/audit.md](../specs/audit/audit.md)

### 19. 설정 관리 (Config)
- **역할**: 모든 설정에 대한 통일된 접근 인터페이스
- **설계**: 3계층 분리 — 정적(TOML) + 비밀값(.env) + 동적(SQLite)
- **기능**: 시작 시 유효성 검증(Fail-fast), 동적 설정 런타임 변경(ConfigChangedEvent)
- 상세 설계: [specs/config/config.md](../specs/config/config.md)

### 20. CLI
- **역할**: `ante` 커맨드를 통한 시스템 제어 인터페이스
- **설계**: click 기반, 사용자와 AI Agent 모두 지원
- **기능**: 시스템·봇·전략·백테스트·데이터 관리, `--format json` 구조화 출력(D-010)
- **통신**: 오프라인 커맨드(직접 모듈 임포트) + 런타임 커맨드(IPC 위임)
- 상세 설계: [specs/cli/cli.md](../specs/cli/cli.md)

### 21. IPC
- **역할**: CLI 런타임 커맨드가 서버 프로세스의 서비스 계층을 호출하는 프로세스 간 통신 인프라
- **설계**: Unix domain socket, JSON 기반 길이 접두사 프레이밍
- **기능**: CLI에서 서버의 ServiceRegistry를 통해 서비스 실행, EventBus 이벤트 체인 보장
- 상세 설계: [specs/ipc/ipc.md](../specs/ipc/ipc.md)

### Database 래퍼 (공통 인프라)
- **역할**: 모든 모듈이 공유하는 SQLite 접근 계층
- **구현**: aiosqlite 기반 async 래퍼, writer/reader 연결 분리
- 상세 설계: [specs/core/core.md](../specs/core/core.md)

## 확장성 고려

현재 구현은 단일 사용자·단일 거래소를 전제로 하지만, 다음 두 원칙을 설계에 반영하여 향후 확장 비용을 낮춘다.

- **교체 가능한 외부 의존성**: 증권사 연동부(`BrokerAdapter`)와 알림 채널(`NotificationAdapter`)은 공통 인터페이스 + 구현체 분리 구조로 설계한다. 초기 구현(KIS, Telegram)을 교체하거나 복수 구현체를 병행 운영할 때 시스템 코어를 수정하지 않아도 된다.
- **상품 비종속**: 봇과 전략은 특정 상품 유형(주식, ETF, 채권 등)에 종속되지 않는다. 증권사 API가 지원하는 모든 상품을 동일한 인터페이스로 거래할 수 있도록 설계한다.
- **복수 Agent 협업**: 현재는 단일 Agent를 전제하지만, 향후 리서치 Agent·실행 감시 Agent 등 역할별 Agent가 협업하는 구조로 확장할 수 있다. CLI와 API 인터페이스가 Agent 수에 종속되지 않도록 설계한다. Agent 등록·역할·권한·활동 이력은 Member 모듈([specs/member/member.md](../specs/member/member.md))에서 관리한다.

## 배포 산출물

Ante는 PyPI 패키지로 배포한다. (pip only — Docker/Windows 미지원)

### PyPI 패키지 (`pip install ante`)

- 사용자가 Python 환경에서 패키지를 설치하고 `ante` CLI로 시스템을 실행한다.
- 최초 실행 시 `ante init`으로 설정 디렉토리(`~/.config/ante/`)를 생성하고, 대화형으로 필수 설정(증권사 API 키, 계좌번호)과 선택 설정(텔레그램 토큰 등)을 입력받는다.
- systemd 서비스로 등록하여 홈서버에서 상시 구동한다.
- 설정 경로 탐색 우선순위: CLI 인자(`--config-dir`) > 환경변수(`ANTE_CONFIG_DIR`) > `~/.config/ante/` > `./config/`
- 프론트엔드 빌드는 CI에서 수행하며, 패키지에 정적 파일로 포함된다.
- 업데이트는 `ante update` 명령으로 수행한다 (DB 마이그레이션 포함).
