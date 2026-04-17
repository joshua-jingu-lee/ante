# Web API 모듈 세부 설계 - 에러 응답 포맷

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# RFC 7807 에러 응답

> 소스: [`src/ante/web/errors.py`](../../../src/ante/web/errors.py)

RFC 7807 (Problem Details for HTTP APIs) 표준을 따르는 에러 응답 포맷.
`register_exception_handlers(app)`으로 FastAPI 앱에 등록한다.

응답 필드는 표준 RFC 7807 스키마를 따르며, Pydantic 스키마는 [08-pydantic-schemas.md](08-pydantic-schemas.md)의 `ErrorResponse` 참조.
