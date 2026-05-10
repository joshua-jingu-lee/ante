# Web API 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# 설계 결정

## FastAPI 애플리케이션

> 소스: [`src/ante/web/app.py`](../../../src/ante/web/app.py)

**근거** (D-008):
- FastAPI — 타입 힌트 기반 자동 문서화, asyncio 네이티브, 경량
- 의존성 주입 — `app.state`에 서비스 인스턴스 저장, 라우터에서 접근
- React SPA — 빌드된 정적 파일을 FastAPI가 서빙, 별도 웹서버 불필요

## 라우터 구성

| Prefix | 태그 | 설명 |
|--------|------|------|
| `/api/system` | system | 시스템 상태·헬스체크·킬스위치 (계좌별/전체) |
| `/api/accounts` | accounts | 계좌 조회 + 정지·활성화 + 비구조 필드 수정. 구조 변경 요청은 cold-path 계약에 따라 409로 차단 |
| `/api/auth` | auth | 세션 인증 (login/logout/me) + Bearer token 기반 me 조회 |
| `/api/bots` | bots | 봇 CRUD + 제어 |
| `/api/trades` | trades | 거래 이력 조회 |
| `/api/strategies` | strategies | 전략 관리 |
| `/api/reports` | reports | 리포트 관리 |
| `/api/notifications` | notifications | ~~알림 이력 조회~~ (텔레그램으로 이관, 라우터 비활성) |
| `/api/data` | data | 데이터셋 조회·삭제 |
| `/api/approvals` | approvals | 결재 관리 (목록/상세/승인·거부) |
| `/api/treasury` | treasury | 자금 관리 (잔고/예산/일별 스냅샷) |
| `/api/portfolio` | portfolio | 포트폴리오 (총 자산·손익·수익률, 자산 추이 — 스냅샷 기반) |
| `/api/members` | members | 멤버(에이전트) 관리 |
| `/api/config` | config | 동적 설정 관리 |
| `/api/audit` | audit | 감사 로그 조회 |

## 인증

Web API는 HTTP 인증 transport를 담당한다. 권한 모델, scope vocabulary, human bypass,
agent 제한 규칙의 SSOT는 [member/02-design-decisions.md](../member/02-design-decisions.md#authorization-ssot)다.

| 호출자 | 인증 transport | principal |
|--------|----------------|-----------|
| human dashboard | `POST /api/auth/login` 후 `ante_session` 쿠키 | human member |
| agent/API client | `Authorization: Bearer ante_ak_*` | agent member |

`POST /api/auth/login`은 패스워드 인증 후 세션 쿠키를 발급한다. `POST /api/auth/logout`은
세션을 삭제하고 쿠키를 제거한다. `GET /api/auth/me`는 Bearer token이 있으면 토큰 인증
결과를 우선 사용하고, 없으면 `ante_session` 쿠키를 검증한다.

인증 실패는 401, 인증은 되었지만 required scope가 부족한 경우는 403으로 응답한다.
endpoint별 required scope는 Web API 라우터 계약에 둘 수 있지만, scope 문자열의 의미는
Member 스펙을 따른다.

세션 저장·검증의 세부 인터페이스는 [03-session-service.md](03-session-service.md) 참조.
Bearer token 추출은 Web API token auth middleware가 수행하며, 실제 토큰 검증은
MemberService.authenticate()에 위임한다.

### 인증 게이트 단계

default-deny 정책의 SSOT는 [D-015](../../decisions/D-015-default-deny-auth-gate.md)다.
Web API는 다음 **요청 처리 순서**로 미들웨어를 적용한다.

```
요청 → TokenAuthMiddleware → RequireAuthMiddleware → 라우트 → dependency(@require_scope) → 응답 → AuditMiddleware
```

| 단계 | 책임 |
|------|------|
| `TokenAuthMiddleware` | `Authorization: Bearer` 헤더가 있을 때 토큰을 검증해 `request.state.member_id` / `request.state.member`에 principal을 부착. 없거나 실패면 그대로 통과(여기서는 401 raise 안 함). |
| `RequireAuthMiddleware` (신규, #1403) | (0) 요청 메소드가 `OPTIONS`(CORS preflight)면 인증 검사를 건너뛰고 즉시 통과. (1) 경로가 `PUBLIC_PATHS` / `PUBLIC_PREFIXES` allowlist 또는 비-`/api` SPA fallback 경로에 속하면 caller 결정 시도 없이 즉시 통과(세션 fallback / ACTIVE 검사도 수행하지 않음). (2) `request.state.member_id`가 비어 있지 않으면(=`TokenAuthMiddleware`가 Bearer caller를 부착했으면) 그대로 통과. (3) Bearer caller가 없으면 `ante_session` 쿠키를 직접 검증해 caller를 결정하고 `member_service.get(caller)` + `MemberStatus.ACTIVE` 검사를 거쳐 `request.state`에 부착. (4) 어느 경로로도 caller가 결정되지 않으면 401. **scope는 검사하지 않는다.** CORS preflight 면제 근거는 본 문서의 [CORS 설정](#cors-설정) 절. |
| 라우트 dependency | endpoint별 `@require_scope(...)`. agent에 대해서만 required scope를 검사하고, human은 bypass. |
| `AuditMiddleware` | 요청/응답 감사 로그 기록. 응답이 완성된 뒤(상위에서 raise된 예외도 변환된 응답 형태로) 기록되므로 처리 순서상 마지막 outer 단계다. |

**Bearer / 세션 쿠키 동시 지원**:

`POST /api/auth/login`으로 로그인한 dashboard 사용자는 이후 요청에 Bearer 헤더 없이
`ante_session` 쿠키만 보낸다. 따라서 `RequireAuthMiddleware`는 Bearer 단(`TokenAuth`)
이 caller를 채우지 못한 경우 **자체적으로 세션 쿠키 fallback**을 수행한다. 이 fallback이
없으면 정상 로그인 dashboard 사용자가 모든 보호 API에서 401을 받는다(D-015 ADR의
"Web 미들웨어 책임 매트릭스" 절 참조).

세션 fallback 알고리즘은 `src/ante/web/deps.py:267-345`의 `require_master_caller` /
`require_audit_read` 등 기존 dependency가 이미 사용 중인 패턴을 따른다
(`SessionService.validate(ante_session)` → `session["member_id"]`). 미들웨어가 caller를
부착하면 dependency 단의 같은 fallback은 자연스럽게 no-op이 되고, gate와 dependency
양쪽이 같은 caller에 합의한다.

**세션 fallback 시 멤버 상태 검증 (Codex review v3 Finding X)**:

`SessionService.validate(ante_session)`은 세션 만료/서명만 검증하며,
멤버의 `status` 필드는 보지 않는다. 따라서 세션 row가 남아 있는 상태에서 멤버가
`SUSPENDED`/`REVOKED`/`DELETED`로 전환되어도 세션 fallback만으로 caller가 결정되면
default-deny 게이트를 통과해 보호 라우트에 도달할 수 있다. 이는 Bearer 경로
(`TokenAuthMiddleware`가 `member_service.authenticate`에서 ACTIVE 검사)와의 비대칭이며,
`require_audit_read`(4차 fix, `src/ante/web/deps.py:444-452`)가 dependency 단에서 이미
정정한 SSOT 패턴을 그대로 따른다.

따라서 `RequireAuthMiddleware`(#1403)는 세션 쿠키 fallback으로 caller를 결정한 뒤,
caller를 `request.state.member_id`에 부착하기 직전에 `member_service.get(caller)`를
호출하고 `member.status == MemberStatus.ACTIVE`를 명시적으로 확인한다. ACTIVE가 아니면
caller를 부착하지 않고 401(인증 실패) 또는 403(비활성 멤버)을 반환한다. Bearer 경로는
`TokenAuthMiddleware`가 동일 검사를 이미 수행하므로 미들웨어 진입 시점에 부착된 caller는
ACTIVE 보장이 있다고 가정해도 좋다.

**공개 경로 판정은 세션 fallback / ACTIVE 검사보다 먼저 수행한다 (Codex review v4
Finding 1)**: 위 ACTIVE 검사는 어디까지나 caller 결정이 필요한 보호 라우트에 대해서만
적용된다. 공개 경로(OPTIONS preflight, `PUBLIC_PATHS` / `PUBLIC_PREFIXES`, 비-`/api`
SPA fallback)에 대해서는 미들웨어가 세션 fallback 자체를 시도하지 않으며 ACTIVE 검사도
수행하지 않는다. 이 순서가 깨지면 `ante_session` 쿠키를 가진 채 멤버 상태가
`SUSPENDED`/`REVOKED`로 전환된 사용자가 `/login` SPA 진입, `POST /api/auth/login`(재로그인
시도), `POST /api/auth/logout`(쿠키 정리), `/api/system/health` 등 복구/공개 경로에
접근할 때 ACTIVE 검사가 먼저 발화해 401/403으로 차단되어 재로그인 / 쿠키 삭제 경로
자체가 막힌다. 위 단계 표의 (1) 공개 경로 면제 분기는 이 회귀를 막기 위해 (3) 세션
fallback + ACTIVE 검사보다 앞에 배치된다.

이렇게 ACTIVE 검사가 미들웨어 책임으로 옮겨지면, 기존 dependency
(`require_audit_read` 등)의 중복 ACTIVE 검사는 #1408에서 제거 대상이 된다. 권한
검사(`require_scope`/dependency)는 ACTIVE 가정 위에서 scope만 본다.

`AuditMiddleware`는 세션으로 결정된 caller도 정확히 기록할 수 있도록
`request.state.member_id`(미들웨어가 부착)를 그대로 읽는다.

**add_middleware 순서 vs 실행 순서**:

FastAPI/Starlette는 **마지막에 `add_middleware()`된 사용자 미들웨어가 요청을 가장 먼저
받는다**(역순 스택). 따라서 위 실행 순서를 얻으려면 `app.add_middleware()`를 **역순**으로
호출해야 한다.

| 호출 순서 (`add_middleware`) | 결과 (요청 처리 순서) |
|------------------------------|------------------------|
| 1. `app.add_middleware(AuditMiddleware)` | 가장 바깥 → 응답 시점에 실행 |
| 2. `app.add_middleware(RequireAuthMiddleware)` | 중간 |
| 3. `app.add_middleware(TokenAuthMiddleware)` | 가장 안쪽 → 요청 시점에 가장 먼저 실행 |

즉 코드상 add 순서는 `Audit → RequireAuth → TokenAuth`이고, 런타임 요청 흐름은
역순인 `TokenAuth → RequireAuth → 라우트 → 응답 → Audit`이다. #1403 구현은 이 매핑을
그대로 따라야 한다. add 순서를 잘못 적으면(예: 의도된 실행 순서를 그대로 add) Audit가
가장 먼저 요청을 받게 되어 인증 단계가 감사 기록 안쪽으로 들어가지 않거나,
RequireAuth가 TokenAuth보다 먼저 실행되어 Bearer caller가 비어 있는 상태로 401을
던지게 된다.

> 위 표는 인증 관련 3개 미들웨어만 보여주는 단순화 표다. `CORSMiddleware`를 포함한
> 4개 미들웨어 전체 add 시퀀스 예시는 아래 [CORS 설정](#cors-설정) 절을 참조한다.
> `CORSMiddleware`는 위 3개 표의 `Audit`보다 **앞에** add되어 가장 안쪽에 위치한다.

**책임 분리**:

- 미들웨어 (`RequireAuthMiddleware`) = 인증(authentication). Bearer 부착 결과를 보고,
  비어 있으면 세션 쿠키 fallback까지 수행. 그래도 비어 있으면 401(PUBLIC 제외).
- dependency (`@require_scope(...)`) = 권한(authorization). scope만 검사한다.

이 분리로 401(인증 실패)과 403(권한 부족)이 다른 코드 경로에서 응답된다. 새 라우트
추가 시 인증은 자동으로 부착되며, scope가 필요한 라우트는 명시적으로 `@require_scope`를
부착한다. scope 누락은 #1407, default-deny 미들웨어 도입은 #1403, 라우트별 결정 표는
#1409가 담당한다.

공개 라우트 allowlist의 SSOT는 [09-public-paths.md](09-public-paths.md)다.

## CORS 설정

홈서버 환경이므로 개발 편의상 전체 origin 허용 (`allow_origins=["*"]`).

**CORS preflight와 인증 게이트의 관계**:

cross-origin 브라우저 클라이언트가 `Authorization: Bearer ...` 같은 non-simple 헤더로
보호 API를 호출할 때, 브라우저는 본 요청 전에 `OPTIONS /api/...` preflight 요청을
자격증명 없이 보낸다. preflight 자체에 default-deny 게이트를 적용하면 401이 반환되어
브라우저가 본 요청을 진행하지 못하고, 결과적으로 정상 토큰을 가진 cross-origin
클라이언트조차 모든 보호 API에서 차단된다(`tests/unit/web/test_app.py::test_cors_headers`가
검증하는 동작 회귀).

따라서 `RequireAuthMiddleware`(#1403)는 **HTTP `OPTIONS` 메소드 요청을 게이트에서
면제**한다. 이는 공개 경로 allowlist와 별개의 메소드 기반 면제 카테고리이며
[09-public-paths.md](09-public-paths.md)의 PUBLIC_PATHS / PUBLIC_PREFIXES 테이블과
독립적으로 적용된다. OPTIONS는 CORSMiddleware가 응답을 생성하므로 라우트 단의
권한 검사로도 진입하지 않는다.

**CORS 등록 순서와 RequireAuth의 관계 (Codex review v3 Finding Y / v5 Finding 1)**:

Starlette `add_middleware()`는 `insert(0)` 시맨틱이므로, 가장 먼저 등록된
미들웨어가 user middleware 리스트의 가장 뒤로 가고, 빌드 시 `reversed()`로
wrap된 결과 가장 안쪽(요청을 가장 늦게 받는 쪽)에 위치한다. 마지막에 add된
미들웨어가 가장 바깥(요청을 가장 먼저 받는 쪽)이다.

`src/ante/web/app.py:48-59` 기준 **현행** 등록 순서는
`CORSMiddleware → AuditMiddleware → TokenAuthMiddleware`다. 따라서 요청 흐름은
**TokenAuth → Audit → CORS → 라우트** 순이고, `CORSMiddleware`는 가장 안쪽에 있다.

`RequireAuthMiddleware`(#1403)를 추가할 때 위 "인증 게이트 단계" 표에서 정한
의도 흐름(`TokenAuth → RequireAuth → Audit → CORS → 라우트`)을 얻으려면, 위
`add_middleware 순서 vs 실행 순서` 표에 따라 add 순서를 **역순**으로 잡아야 한다.
즉 `RequireAuthMiddleware`는 `CORSMiddleware`와 `AuditMiddleware` add **뒤**,
`TokenAuthMiddleware` add **앞**에 끼워 넣는다. 결과 add 순서는
`CORS → Audit → RequireAuth → TokenAuth`이고, 마지막 add인 `TokenAuth`가
가장 바깥(요청을 가장 먼저 받음), 그 다음이 `RequireAuth`, 그 다음 `Audit`,
가장 안쪽이 `CORS`다. 이 배치에서만 Bearer caller가 `TokenAuth` 단계에서
`request.state.member_id`에 부착된 뒤 `RequireAuth`가 그 값을 보고 통과
판단을 내릴 수 있다.

반대로 `TokenAuthMiddleware` add **뒤**에 `RequireAuthMiddleware`를 add하면
`RequireAuth`가 더 바깥(=먼저 실행)이 되어 `request.state.member_id`가 아직
비어 있는 상태로 default-deny가 발화하고, **정상 Bearer 토큰 사용자도
모두 401**을 받는다. 본 spec은 이 잘못된 배치를 명시적으로 금지한다.

OPTIONS preflight 안전망: 위 배치에서도 `CORSMiddleware`는 가장 안쪽이므로
`RequireAuthMiddleware`가 OPTIONS preflight를 먼저 만난다. 따라서 본 spec은
미들웨어 등록 순서에 의존하지 않도록 **`RequireAuthMiddleware` 자체가 HTTP
`OPTIONS` 메소드 요청을 무조건 통과시키는 가드**를 갖도록 요구한다. 이 가드가
있으면 CORS가 안쪽이든 바깥이든, 추후 누군가 등록 순서를 바꿔도 cross-origin
preflight 회귀가 발생하지 않는다. 실제 CORS 응답 본문 생성은 안쪽의
`CORSMiddleware`가 라우트 직전 단계에서 수행한다(현행 코드 동작과 동일,
`tests/unit/web/test_app.py::test_cors_headers`가 보증한다).

대안으로 CORS를 RequireAuth보다 바깥에 두려면 `RequireAuthMiddleware` 등록
**뒤**에 `CORSMiddleware`를 다시 add해야 한다. 본 spec은 그 변경을 요구하지
않으며, OPTIONS 면제 가드만으로 동일한 안전성을 확보한다.

**#1403 구현 시 권장 add 시퀀스 (참고용 코드 예시, 단계 표와 분리)**:

위 단계 표는 *요청 처리 순서*를 정의하고, 아래 예시는 그 순서를 얻기 위한
Starlette `add_middleware()` *호출 순서*를 보여준다. 두 표는 서로 역순이다.

```python
# 현행 (src/ante/web/app.py:48-59)
app.add_middleware(CORSMiddleware, ...)          # add 1 → 가장 안쪽
app.add_middleware(AuditMiddleware)              # add 2
app.add_middleware(TokenAuthMiddleware)          # add 3 → 가장 바깥 (현행)

# #1403에서 RequireAuthMiddleware를 도입한 뒤 의도 흐름
# (TokenAuth → RequireAuth → Audit → CORS → 라우트)을 얻으려면
# TokenAuth add 직전에 끼워 넣는다.
app.add_middleware(CORSMiddleware, ...)          # add 1 → 가장 안쪽
app.add_middleware(AuditMiddleware)              # add 2
app.add_middleware(RequireAuthMiddleware)        # add 3
app.add_middleware(TokenAuthMiddleware)          # add 4 → 가장 바깥
```

LIFO 시맨틱이므로 **마지막 add가 가장 먼저 요청을 처리**한다. `TokenAuth`가
가장 마지막에 add되어야 Bearer caller 부착이 `RequireAuth` 평가보다 먼저
일어난다.

| 메소드 | 게이트 동작 |
|--------|------------|
| `OPTIONS` (preflight) | 인증 검사 면제. 항상 통과(CORS 응답 또는 라우트가 처리). |
| 그 외 (GET/POST/PUT/PATCH/DELETE 등) | default-deny. PUBLIC_PATHS/PUBLIC_PREFIXES allowlist만 면제. |

## OpenAPI 자동 문서화

FastAPI가 라우터 정의와 Pydantic 스키마(`schemas.py`)로부터 OpenAPI 3.x 스펙을 자동 생성한다. 별도 설정 없이 다음 경로에서 접근 가능:

| 경로 | 설명 |
|------|------|
| `/docs` | Swagger UI — 인터랙티브 API 탐색기. 엔드포인트별 파라미터 확인, 직접 요청 실행 가능 |
| `/redoc` | ReDoc — 읽기 전용 API 레퍼런스 문서 |
| `/openapi.json` | OpenAPI JSON 스키마 원본. Agent나 외부 도구가 API 계약을 파싱할 때 사용 |

> AI Agent는 `/openapi.json`을 조회하여 사용 가능한 엔드포인트, 파라미터, 응답 스키마를 자동으로 파악할 수 있다.
