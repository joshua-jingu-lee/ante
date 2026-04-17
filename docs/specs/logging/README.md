# Logging 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/core/log/` 를 참조하세요.

> 참조: [eventbus.md](../eventbus/eventbus.md) 이벤트 로그, [audit.md](../audit/audit.md) 감사 로그, [config/03-design-decisions.md](../config/03-design-decisions.md) 환경변수, [core.md](../core/core.md) 시스템 초기화 순서

이 디렉토리는 Logging 스펙을 주제별 문서로 분할해 관리한다.
기존 참조 호환을 위해 [logging.md](logging.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [logging.md](logging.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
| [01-overview.md](01-overview.md) | 개요 및 로그 3종 구분 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-json-schema.md](03-json-schema.md) | JSON 로그 스키마 |
| [04-fingerprint.md](04-fingerprint.md) | Exception Fingerprint 규칙 |
| [05-handlers-and-rotation.md](05-handlers-and-rotation.md) | 핸들러 구성과 회전 정책 |
| [06-context-fields.md](06-context-fields.md) | 컨텍스트 필드 주입 패턴 |
| [07-implementation.md](07-implementation.md) | 구현 위치와 설계 근거 |
| [08-open-issues.md](08-open-issues.md) | 미결 사항 |
