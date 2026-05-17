# Web API 모듈 세부 설계 - 에러 응답 포맷

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# RFC 7807 에러 응답

> 소스: [`src/ante/web/errors.py`](../../../src/ante/web/errors.py)

RFC 7807 (Problem Details for HTTP APIs) 표준을 따르는 에러 응답 포맷.
`register_exception_handlers(app)`으로 FastAPI 앱에 등록한다.

응답 필드는 표준 RFC 7807 스키마를 따르며, Pydantic 스키마는 [08-pydantic-schemas.md](08-pydantic-schemas.md)의 `ErrorResponse` 참조.

모든 라우트의 *명시 등록된* 4xx/5xx `responses` 항목은 `model: ErrorResponse`를 사용한다(invariant).

명시 등록된 4xx/5xx `responses` entry는 OpenAPI 노출 시 `application/problem+json` content-type만 사용하며, 런타임 응답 content-type(`PROBLEM_JSON`)과 일치한다(invariant, #1164).

**Validation error sanitization (invariant, 보안 — L1: 값 반사 금지, #1629 / L2: `extra_forbidden` loc 말단 정규화, #1650)**: 422 validation 응답 detail은 거부된 입력 **값**을 반사하지 않으며, Pydantic `error["type"] == "extra_forbidden"` 항목의 `loc` **말단 세그먼트**(거부된 caller extra 필드의 **키 이름**)는 고정 placeholder 토큰 `[extra]`로 정규화된다.

- **L1 (값/`input`/`ctx`/`msg` 반사 금지, #1629)**: (1) raw-body 핸들러는 공용 chokepoint `sanitize_validation_errors(e)`(= `e.errors(include_context=False, include_input=False)` + `_normalize_error_loc`, pydantic `ValidationError`), 글로벌 `RequestValidationError` 핸들러는 `_sanitize_pydantic_errors(exc.errors())`(= `input`/`ctx` 제거 + `_normalize_error_loc`)를 사용한다. (2) web request 모델 validator 메시지는 거부된 raw value를 `msg`에 interpolation하지 않는다(필드/제약만 명시). `type`/`msg`/`url`만 노출. 신규 raw-body validation 핸들러·validator는 본 invariant를 의무 준수하며, raw-body 사이트는 `e.errors(include_input=False)` 직접호출 대신 공용 chokepoint `sanitize_validation_errors`만 호출한다(직접 호출 잔존 0 — SSOT).
- **L2 (`extra_forbidden` loc 말단 정규화, #1650)**: 두 sanitization 경로(글로벌 `_sanitize_pydantic_errors` / raw-body chokepoint `sanitize_validation_errors`)는 `_normalize_error_loc`로 **`type=='extra_forbidden'` 항목 한정** `loc[-1]`(거부된 caller extra 필드 키)을 고정 placeholder `[extra]`로 치환한다. static `loc` prefix(`body` 등)·`type`/`msg`/`url`·HTTP 422·RFC7807 envelope는 보존한다(현 `extra="forbid"` 요청모델은 전부 flat `BaseModel`이라 extra 키는 항상 `loc` 말단 — #1643 v-series AST 실측). 본 정규화의 **보안 단언은 `type=='extra_forbidden'` loc 벡터에 한정**한다.
- **L2 범위 외 (→ #1651 spec-first 종합 정책)**: 비-`extra_forbidden` caller-controlled `loc`(자유형 `dict[str,*]` 필드의 **키**, structured body[dataclass/TypedDict/RootModel], validator-합성 `loc`, root-container body)와 `PUT /api/accounts/{id}` raw-body의 **수동 unknown-key 422**(`accounts.py:644-648` — Pydantic `extra_forbidden` 미경유, unknown key를 직접 detail 문자열에 join = F3 벡터)는 본 invariant(L2) 정규화 대상이 **아니며**, **#1651**(비-`extra_forbidden` 종합 정책) 및 F3 후속 후보에서 다룬다. #1650은 `type=='extra_forbidden'` loc 말단에 한정한다.
