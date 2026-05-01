# Web API 모듈 세부 설계 - 에러 응답 포맷

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# RFC 7807 에러 응답

> 소스: [`src/ante/web/errors.py`](../../../src/ante/web/errors.py)

RFC 7807 (Problem Details for HTTP APIs) 표준을 따르는 에러 응답 포맷.
`register_exception_handlers(app)`으로 FastAPI 앱에 등록한다.

응답 필드는 표준 RFC 7807 스키마를 따르며, Pydantic 스키마는 [08-pydantic-schemas.md](08-pydantic-schemas.md)의 `ErrorResponse` 참조.

모든 라우트의 *명시 등록된* 4xx/5xx `responses` 항목은 `model: ErrorResponse`를 사용한다(invariant).

명시 등록된 4xx/5xx `responses` entry는 OpenAPI 노출 시 `application/problem+json` content-type만 사용하며, 런타임 응답 content-type(`PROBLEM_JSON`)과 일치한다(invariant, #1164).
