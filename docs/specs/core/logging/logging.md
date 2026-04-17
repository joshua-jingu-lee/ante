# Logging 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/core/log/` 를 참조하세요.

> 참조: [core.md](../core.md) Core 모듈 개요, [eventbus.md](../../eventbus/eventbus.md) 이벤트 로그, [audit.md](../../audit/audit.md) 감사 로그, [config/03-design-decisions.md](../../config/03-design-decisions.md) 환경변수

이 문서는 분할된 `logging` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 및 로그 3종 구분 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-json-schema.md](03-json-schema.md) | JSON 로그 스키마 |
| [04-fingerprint.md](04-fingerprint.md) | Exception Fingerprint 규칙 |
| [05-handlers-and-rotation.md](05-handlers-and-rotation.md) | 핸들러 구성과 회전 정책 |
| [06-context-fields.md](06-context-fields.md) | 컨텍스트 필드 주입 패턴 |
| [07-implementation.md](07-implementation.md) | 구현 위치와 설계 근거 |
| [08-open-issues.md](08-open-issues.md) | 미결 사항 |
