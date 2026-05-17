# Web API 모듈 세부 설계 - 에러 응답 포맷

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# RFC 7807 에러 응답

> 소스: [`src/ante/web/errors.py`](../../../src/ante/web/errors.py)

RFC 7807 (Problem Details for HTTP APIs) 표준을 따르는 에러 응답 포맷.
`register_exception_handlers(app)`으로 FastAPI 앱에 등록한다.

응답 필드는 표준 RFC 7807 스키마를 따르며, Pydantic 스키마는 [08-pydantic-schemas.md](08-pydantic-schemas.md)의 `ErrorResponse` 참조.

모든 라우트의 *명시 등록된* 4xx/5xx `responses` 항목은 `model: ErrorResponse`를 사용한다(invariant).

명시 등록된 4xx/5xx `responses` entry는 OpenAPI 노출 시 `application/problem+json` content-type만 사용하며, 런타임 응답 content-type(`PROBLEM_JSON`)과 일치한다(invariant, #1164).

**Validation error sanitization (invariant, 보안 — L1: 값 반사 금지, #1629)**: 422 validation 응답 detail은 거부된 입력 **값**을 반사하지 않는다. (1) raw-body 핸들러는 `e.errors(include_context=False, include_input=False)`(pydantic `ValidationError`), 글로벌 `RequestValidationError` 핸들러는 `_sanitize_pydantic_errors(exc.errors())`로 `input`/`ctx`를 제거한다. (2) web request 모델 validator 메시지는 거부된 raw value를 `msg`에 interpolation하지 않는다(필드/제약만 명시). `type`/`msg`/`url`만 노출. 신규 raw-body validation 핸들러·validator는 본 invariant를 의무 준수한다. **(L2: `loc` 키 노출 — 정책 판정 완료, #1643로 분리)** `loc` 세그먼트에 caller-제어 input(거부된 extra 필드 **키 이름**, 자유형 `dict[str,*]` 필드의 **키**)이 들어가는 것은 invariant 위반으로 규정되며, 정규화는 web 422 경계 한정·service caller 무영향이라 **#1643(별도 이슈)** 으로 분리 처리한다(선행: #1629 L1 merge). #1629는 **L1(값/`input`/`ctx`/`msg` 반사 금지)만** 다룬다.
