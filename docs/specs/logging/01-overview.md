# Logging 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

# 개요

Logging은 **Ante 시스템 전역의 운영 로그를 표준 포맷으로 출력·보관하는 공통 인프라**다.
모든 모듈은 표준 Python `logging` API(`logging.getLogger(__name__)`)를 통해 사용하며, 이벤트 로그([eventbus](../eventbus/eventbus.md))·감사 로그([audit](../audit/audit.md))와 함께 시스템 관찰의 세 축을 이룬다.

**주요 기능**:
- **이중 핸들러**: 콘솔 stdout 평문(사람 관찰용) + 파일 JSONL(에이전트·스크립트 분석용)
- **JSON Lines 포맷**: 한 줄에 한 JSON 객체, 필드 구조화, 스택 트레이스 단일 필드 보관
- **Exception Fingerprint**: 같은 근본 원인을 묶는 안정 식별자
- **환경 게이트**: `ANTE_LOG_JSONL`, `ANTE_ENV`로 환경별 활성화·식별
- **회전 정책**: 자정 기준 일일 회전, 30일 보관, 3일 이후 gzip 압축

## 로그 3종 구분

Ante는 용도가 다른 세 종류의 "로그"를 별도로 관리한다. 본 문서 묶음이 다루는 **시스템 로그**는 운영 상태·에러 추적용이며, 다른 두 종류와 저장소·포맷이 분리된다.

| 종류 | 저장소 | 목적 | 정의 위치 |
|---|---|---|---|
| **시스템 로그** | stdout + 파일(JSONL) | 런타임 관찰, 에러 추적, 운영 진단 | 본 문서 묶음 |
| **이벤트 로그** | SQLite `event_log` 테이블 | EventBus 도메인 이벤트 영속화 | [eventbus/eventbus.md](../eventbus/eventbus.md) |
| **감사 로그** | SQLite `audit_log` 테이블 | API 상태 변경 감사 추적 | [audit/audit.md](../audit/audit.md) |

시스템 로그는 이벤트·감사 로그와 교차하지 않는다. 도메인 이벤트 처리 중 발생한 예외는 시스템 로그에 기록되지만, 이벤트 자체의 페이로드는 이벤트 로그가 SSOT이다.

## Logging이 하지 않는 것

- 도메인 이벤트 저장 → EventHistoryStore (이벤트 로그)
- API 상태 변경 감사 → AuditLogger (감사 로그)
- 외부 알림 발송 → Notification 모듈 (Telegram 등)
- 로그 기반 메트릭 집계 → Logging 모듈 외부 (감시 에이전트·외부 뷰어)
- 민감값 마스킹 정책 정의 → 호출자 책임 (로깅 인프라는 주입된 값을 그대로 직렬화)
