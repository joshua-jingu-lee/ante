# Web API 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/web/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 웹 대시보드, D-008, [cli.md](../cli/cli.md) CLI 인터페이스

이 문서는 분할된 `web-api` 스펙의 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
최신 계약 SSOT는 [README.md](README.md)의 문서 목록과 주제별 하위 문서다.
새 계약, 결정, 미결 사항은 이 파일에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | FastAPI 구성·라우터·인증·CORS·OpenAPI 문서화 |
| [03-session-service.md](03-session-service.md) | SessionService — 서버사이드 세션 관리 |
| [04-system-endpoints.md](04-system-endpoints.md) | 시스템 엔드포인트 (`/api/system/*`) 및 헬스체크 상세 |
| [05-resource-endpoints.md](05-resource-endpoints.md) | 리소스 엔드포인트 (계좌·봇·전략·거래·자금·결재·멤버·설정·감사 등) |
| [06-pagination.md](06-pagination.md) | Cursor 기반 페이지네이션 |
| [07-error-format.md](07-error-format.md) | RFC 7807 에러 응답 |
| [08-pydantic-schemas.md](08-pydantic-schemas.md) | Pydantic 스키마 목록 |
| [10-cross-module-notes.md](10-cross-module-notes.md) | 타 모듈 설계 시 참고 |
