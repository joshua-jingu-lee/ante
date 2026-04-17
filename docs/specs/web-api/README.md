# Web API 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/web/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 웹 대시보드, D-008, [cli.md](../cli/cli.md) CLI 인터페이스

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 참조 호환을 위해 [web-api.md](web-api.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [web-api.md](web-api.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | FastAPI 구성·라우터·인증·CORS·OpenAPI 문서화 |
| [03-session-service.md](03-session-service.md) | SessionService — 서버사이드 세션 관리 |
| [04-system-endpoints.md](04-system-endpoints.md) | 시스템 엔드포인트 (`/api/system/*`) 및 헬스체크 상세 |
| [05-resource-endpoints.md](05-resource-endpoints.md) | 리소스 엔드포인트 (계좌·봇·전략·거래·자금·결재·멤버·설정·감사 등) |
| [06-pagination.md](06-pagination.md) | Cursor 기반 페이지네이션 |
| [07-error-format.md](07-error-format.md) | RFC 7807 에러 응답 |
| [08-pydantic-schemas.md](08-pydantic-schemas.md) | Pydantic 스키마 목록 |
| [09-open-issues.md](09-open-issues.md) | 미결 사항 |
| [10-cross-module-notes.md](10-cross-module-notes.md) | 타 모듈 설계 시 참고 |
