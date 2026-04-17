# 모듈 스펙 인덱스

> 마스터 문서: [AGENTS.md](../../AGENTS.md) | 아키텍처: [architecture.md](../architecture/README.md)

`docs/specs/`는 모듈별 상세 설계 문서의 인덱스다. 큰 모듈은 `docs/specs/<module>/README.md`를 인덱스로 두고 주제별 하위 문서로 분할 관리한다. 기존 참조 호환을 위해 `docs/specs/<module>/<module>.md`는 개요와 앵커를 유지하는 호환 문서로 남겨둔다.

| 모듈 | 스펙 문서 | 설명 |
|---|---|---|
| `account` | [README.md](account/README.md) | 계좌 모델, 서비스, 잔고/포지션 관리 |
| `api-gateway` | [api-gateway/api-gateway.md](api-gateway/api-gateway.md) | 브로커 API 요청 중개, 큐잉, rate limit |
| `approval` | [README.md](approval/README.md) | 결재 요청, 승인, 이력 관리 |
| `audit` | [audit/audit.md](audit/audit.md) | 감사 로그 기록과 조회 |
| `backtest` | [README.md](backtest/README.md) | 백테스트 실행, 결과 모델, 리포트 연계 |
| `bot` | [README.md](bot/README.md) | 봇 실행 수명주기, 외부 시그널 처리 |
| `broker-adapter` | [README.md](broker-adapter/README.md) | 브로커 어댑터 인터페이스, KIS/Test Broker |
| `cli` | [README.md](cli/README.md) | CLI 명령 체계와 서비스 진입점 |
| `config` | [README.md](config/README.md) | 설정 계층, 동적 설정 관리 |
| `core` | [core/core.md](core/core.md) | 공통 인프라와 Database 래퍼 |
| `data-feed` | [README.md](data-feed/README.md) | 배치 데이터 수집과 공급 인터페이스 |
| `data-pipeline` | [README.md](data-pipeline/README.md) | 저장소, 스키마, ETL 파이프라인 |
| `eventbus` | [eventbus/eventbus.md](eventbus/eventbus.md) | 타입 기반 이벤트 발행/구독 인프라 |
| `instrument` | [instrument/instrument.md](instrument/instrument.md) | 종목 메타데이터, 별칭, 표시 규칙 |
| `ipc` | [ipc/ipc.md](ipc/ipc.md) | CLI와 서버 프로세스 간 IPC 프로토콜 |
| `logging` | [README.md](logging/README.md) | 시스템 로그 인프라, JSONL 포맷, Fingerprint |
| `member` | [README.md](member/README.md) | 멤버 인증, 권한, 알림 연계 |
| `notification` | [notification/notification.md](notification/notification.md) | 알림 이벤트, 채널, 전송 정책 |
| `report-store` | [report-store/report-store.md](report-store/report-store.md) | 백테스트/운영 리포트 저장과 조회 |
| `rule-engine` | [README.md](rule-engine/README.md) | 거래 규칙, 검증, 차단, 알림 |
| `strategy` | [README.md](strategy/README.md) | 전략 인터페이스, 레지스트리, 외부 신호 |
| `trade` | [README.md](trade/README.md) | 주문, 체결, 포지션, reconciliation |
| `treasury` | [README.md](treasury/README.md) | 예산, 가상 현금, 자금 스냅샷 |
| `web-api` | [web-api/web-api.md](web-api/web-api.md) | 대시보드 API, 인증, 라우트 계약 |
