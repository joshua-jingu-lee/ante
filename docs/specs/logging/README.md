# Logging 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/core/log/` 를 참조하세요.

> 참조: [eventbus.md](../eventbus/eventbus.md) 이벤트 로그, [audit.md](../audit/audit.md) 감사 로그, [config/03-design-decisions.md](../config/03-design-decisions.md) 환경변수, [core.md](../core/core.md) 시스템 초기화 순서

이 디렉토리는 Logging 스펙을 주제별 문서로 분할해 관리한다.
계약 SSOT는 이 README의 문서 목록과 주제별 하위 문서다.
[logging.md](logging.md)는 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
새 계약, 결정, 미결 사항은 [logging.md](logging.md)에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [logging.md](logging.md) | 호환용 인덱스 및 기존 섹션 앵커 (계약 본문 아님) |
| [01-overview.md](01-overview.md) | 개요 및 로그 3종 구분 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-json-schema.md](03-json-schema.md) | JSON 로그 스키마 |
| [04-fingerprint.md](04-fingerprint.md) | Exception Fingerprint 규칙 |
| [05-handlers-and-rotation.md](05-handlers-and-rotation.md) | 핸들러 구성과 회전 정책 |
| [06-context-fields.md](06-context-fields.md) | 컨텍스트 필드 주입 패턴 |
| [07-implementation.md](07-implementation.md) | 구현 위치와 설계 근거 |
