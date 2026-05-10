# D-015: default-deny 인증 게이트 (2026-05-11)

> Ante 설계 결정 기록.
> 인덱스: [README.md](README.md)

**결정**: Web API와 CLI 모두 인증을 **default-deny + allowlist (opt-out)** 게이트로
전환한다. middleware/group factory가 1차 차단(인증)을 담당하고, dependency/decorator는
scope 검증만 담당한다.

**근거**:

- 기존 Web/CLI는 라우트/명령마다 `Depends(require_*)` 또는 `@require_auth`를 명시적으로
  부착하는 **opt-in 모델**이다. 70개 Web 라우트 중 30개만 인증이 부착돼 있고, 나머지는
  `TokenAuthMiddleware`가 Bearer가 있을 때만 인증을 시도한 뒤 그대로 통과시킨다
  (`src/ante/web/middleware/token_auth.py:42-49`).
- 그 결과 oracle A7 host probe가 새로운 인증 누락을 사후에 반복적으로 발견하고 있다
  (#1351, #1352, #1357, #1358, #1359, #1360, #1369, #1370, #1371-#1380).
- `docs/specs/member/02-design-decisions.md` Authorization SSOT는 "endpoint별 / command별
  required scope를 검사"라고 정의했지만, **부착 강제 메커니즘 자체는 spec에 빠져 있다**.
  default-deny가 명시적으로 거부된 게 아니라 단지 정의되지 않았다.
- default-deny로 전환하면 새 라우트/명령 추가 시 자동으로 401/exit 1이 발생하며, 공개
  접근이 의도된 표면은 allowlist에 명시적으로 등록해야 한다. 즉 "공개"가 누락이 아닌
  의도된 결정으로 드러난다.
- `require_scope` predicate(human bypass + agent scope 검증)는 이미 SSOT에 정의되어
  있으므로 그대로 유지하고 dependency 단의 책임으로만 둔다.

**책임 분리**:

| 단계 | 책임 | 위치 |
|------|------|------|
| 1차 차단 (authentication) | 인증된 principal이 있는지 확인. 없으면 401 (Web) / exit 1 (CLI). | Web: middleware. CLI: group factory. |
| 2차 차단 (authorization) | required scope를 만족하는지 확인. agent가 부족하면 403. human은 bypass. | Web: dependency. CLI: decorator. |

middleware/factory는 scope를 모른다. dependency/decorator는 인증된 principal을 전제로
한다. 이 분리로 인증 실패와 권한 부족이 다른 단계에서 다른 코드로 응답된다.

**Web 미들웨어 책임 매트릭스 (Bearer/Session/Gate 분담)**:

Web 1차 차단은 두 인증 transport(Bearer 헤더, `ante_session` 쿠키)를 모두 인식해야
한다. `POST /api/auth/login`으로 로그인한 dashboard 사용자는 Bearer 헤더 없이 쿠키만
보내므로, gate 미들웨어가 쿠키 fallback을 직접 수행하거나 별도 단계에서 부착해야
한다. 그렇지 않으면 정상 로그인 세션도 모든 보호 라우트에서 401을 받는다.

| 미들웨어 | 책임 | principal 부착 결과 |
|----------|------|---------------------|
| `TokenAuthMiddleware` | `Authorization: Bearer` 헤더가 있으면 검증해 `request.state.member_id`/`request.state.member`에 caller를 부착. 없거나 실패면 그대로 통과(401 raise 안 함). | Bearer caller |
| `RequireAuthMiddleware` (신규, #1403) | 아래 **5단계 판정 순서**를 따라 caller를 결정한다(상세는 [web-api/02-design-decisions.md](../specs/web-api/02-design-decisions.md#인증-게이트-단계)). 1) HTTP `OPTIONS` preflight면 즉시 통과. 2) 경로가 `PUBLIC_PATHS` / `PUBLIC_PREFIXES` allowlist 또는 비-`/api` SPA fallback이면 즉시 통과(세션 fallback / ACTIVE 검사도 수행하지 않음). 3) `request.state.member_id`가 이미 부착돼 있으면(=Bearer caller) 그대로 통과. 4) Bearer caller가 없으면 `ante_session` 쿠키를 직접 검증하고 `member.status == ACTIVE`를 명시 확인한 뒤 caller를 부착. 5) 어느 단계로도 caller가 결정되지 않으면 401. | Bearer caller (위 단계에서 부착) 또는 Session caller (gate가 부착) |
| 라우트 dependency / `@require_scope` | 인증된 principal을 전제로 scope만 검사. agent에 대해서만 required scope를 검증하고, human은 bypass. | — |

`RequireAuthMiddleware`의 세션 쿠키 fallback은 기존 dependency
(`require_master_caller`, `require_audit_read` 등이 `src/ante/web/deps.py:267-345`에서
이미 동일한 fallback을 수행)와 같은 SessionService 인터페이스(`session.validate`)를
사용한다. 미들웨어가 caller를 부착하면 dependency 단의 fallback은 자연스럽게
no-op이 되고, 두 단이 같은 caller에 합의한다.

대안적으로 `Audit → TokenAuth → SessionAuth → RequireAuth`처럼 세션 fallback을
별도 미들웨어로 분리할 수 있으나, 본 결정에서는 단일 `RequireAuthMiddleware`가
"인증된 principal 부착 + 미부착 시 401"을 함께 수행하는 것을 SSOT로 둔다.
이유: (1) gate가 단일 책임 지점이 되어야 default-deny invariant가 한 곳에서 보장됨,
(2) 추가 미들웨어 단계는 Audit / OpenAPI / SPA fallback 등과 순서 결합이 늘어
유지보수가 어렵기 때문.

**판정 순서 SSOT 위치 (Codex review v5 Finding 2)**: 위 책임 매트릭스의
`RequireAuthMiddleware` 5단계 순서(OPTIONS preflight → PUBLIC allowlist →
Bearer caller → 세션 fallback + ACTIVE → 미결정 시 401)는 본 ADR과
[web-api/02-design-decisions.md](../specs/web-api/02-design-decisions.md#인증-게이트-단계)
양쪽에서 동일하게 유지한다. 두 문서는 cross-link으로 묶여 있으며, 어느 한쪽이
바뀌면 다른 쪽도 같은 라운드에서 정정해야 한다. 특히 "공개 경로 면제"는 항상
"세션 fallback / ACTIVE 검사"보다 **먼저** 평가되어야 하며, 이 순서가 깨지면
`SUSPENDED`/`REVOKED` 멤버가 `/login` SPA 진입이나 `POST /api/auth/logout` 같은
복구/공개 경로 자체를 차단당해 재로그인 / 쿠키 정리 경로가 막힌다.

**Alternatives considered**:

- **opt-in 유지 + 정적 검증 게이트만 추가**: 라우트 정의에 `Depends(require_*)`가 있는지
  AST/test로 강제. 누락 시 CI 실패. → 정적 검증은 효과적이지만 런타임 안전망이 없다.
  검증 게이트 자체에 누락이 생기면 다시 oracle finding으로 회귀한다. default-deny는
  런타임 차단까지 보장한다.
- **FastAPI `dependencies=[Depends(...)]` per-router 부착**: APIRouter 생성 시 default
  dependency를 모든 라우트에 일괄 적용. → 라우터별 boilerplate가 생기고, 공개 라우트는
  router를 분리해야 한다. middleware 단일 게이트가 라우터 구성 자유도를 더 보존한다.

**Consequences**:

- 새 라우트/명령 추가 시 별도 조치 없이 자동 401/exit 1 차단. 의도된 공개는 allowlist에
  명시.
- 공개 라우트는 `PUBLIC_PATHS` / `PUBLIC_PREFIXES` allowlist로 관리한다. SSOT는
  [docs/specs/web-api/09-public-paths.md](../specs/web-api/09-public-paths.md).
- CLI 공개 명령은 `_AUTH_EXEMPT_COMMAND_PATHS` allowlist로 관리한다. SSOT는
  [docs/specs/cli/03-commands.md](../specs/cli/03-commands.md).
- `require_scope`(human bypass + agent scope 검증)는 dependency/decorator 단에 그대로
  유지된다. middleware/factory는 scope를 검사하지 않는다.
- 70-route 전수 결정 표는 본 결정의 SSOT 범위를 벗어나므로 별도 이슈 #1409로 분리한다.
  본 결정은 정책과 책임 분리만 확정한다.
- 후속 구현 이슈: #1403 (Web middleware), #1404 (CLI factory), #1405 (정적 검증),
  #1406 (factory shim), #1407 (라우트 일관 부착), #1408 (import 마이그레이션),
  #1409 (70-route 결정 표).
