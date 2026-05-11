# Web API 모듈 세부 설계 - 공개 경로 allowlist

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)
> 정책 SSOT: [D-015 default-deny 인증 게이트](../../decisions/D-015-default-deny-auth-gate.md)
> 게이트 단계 SSOT: [02-design-decisions.md — 인증 게이트 단계](02-design-decisions.md#인증-게이트-단계)

# 공개 경로 (PUBLIC_PATHS / PUBLIC_PREFIXES) allowlist

`RequireAuthMiddleware`(#1403)는 default-deny 정책에 따라 인증되지 않은 요청을 401로
차단한다. 본 문서는 그 게이트에서 **면제**되는 공개 경로의 SSOT다.

> 70개 라우트 전수 결정 표는 본 문서 범위를 벗어나며 [#1409](https://github.com/joshua-jingu-lee/ante/issues/1409)에서 별도로
> 작성한다. 본 문서는 정책 결정 시점에 코드/스펙으로 확정 가능한 항목만 다룬다.

## 카테고리

allowlist 항목은 다음 세 카테고리 중 하나에 속한다.

| 카테고리 | 의미 | 게이트 처리 | 라우트 책임 |
|---------|------|------------|-------------|
| `public` | 인증 없이 누구나 접근 가능. 응답에 민감 정보 없음. | 미들웨어가 401 없이 통과시킨다. | 라우트는 caller-agnostic. 인증 검사 자체를 하지 않는다. |
| `gate-exempt-self-auth` | 미들웨어 게이트는 면제. 라우트가 자체적으로 세션/토큰을 검증하고 미인증이면 401, 인증되었으면 본인 정보만 응답. | 미들웨어가 401 없이 통과시킨다. | 라우트가 직접 세션 쿠키 / Bearer 토큰을 확인해 401 또는 본인 정보(self-only)를 응답한다. |
| `unresolved` | 본 이슈에서 결정 보류. #1409 70-route 결정 표에 위임. | 결정 시까지 default-deny가 적용된다. 즉 인증되지 않으면 401이 응답된다. | (결정 후 카테고리에 따름) |

**책임 분리**:

`public`은 응답 자체에 민감 정보가 없거나, 호출자가 누구든 동일한 응답을 줘도 안전한
표면이다. 인증 무관 응답이 곧 정상 응답이다.

`gate-exempt-self-auth`는 미들웨어 게이트만 면제되며, **응답 자체는 caller에 따라 달라야
한다**. 미인증이면 라우트가 직접 401을 던지고, 인증되었으면 호출자 본인 정보만
응답한다. 미들웨어 단의 default-deny를 그대로 적용하면 dashboard 초기 로딩에서
"내가 누구인지" 조회조차 불가능해지므로 게이트만 면제하고 라우트가 self-only 가드를
직접 수행한다.

두 카테고리가 섞이지 않도록 새 항목 추가 시 응답 내용을 점검한다. 인증 무관 정보를
주려는 항목은 `public`, 본인 정보를 주려는 항목은 `gate-exempt-self-auth`다.

## PUBLIC_PATHS (정확 일치)

| 경로 | 카테고리 | 근거 |
|------|---------|------|
| `/` | public | SPA 진입점. `src/ante/web/app.py:357-377`의 `SPAFallbackMiddleware`가 비-`/api` 경로의 404 응답을 `index.html`로 폴백한다. 미인증 사용자가 로그인 화면 HTML 자체를 받지 못하면 로그인 자체가 시작되지 않으므로 PUBLIC 필요. |
| `/index.html` | public | SPA 진입점(직접 요청 경로). `/`와 동일 근거. SPA 자산을 받기 위해 인증을 요구하면 로그인 화면 진입이 불가능. |
| `/api/system/health` | public | reverse proxy / 모니터링 헬스체크. 인증 요구 시 운영 인프라가 헬스를 판정할 수 없다. 라우트 정의: `src/ante/web/routes/system.py:102`. |
| `/api/auth/login` | public | 인증 자체를 수행하는 엔드포인트. 인증되지 않은 상태에서 시작되어야 한다. 라우트 정의: `src/ante/web/routes/auth.py:31`. |
| `/api/auth/logout` | public | 세션 종료. 인증이 만료된 상태에서도 호출 가능해야 한다(클라이언트 측 정리 + 서버 측 best-effort). 라우트 정의: `src/ante/web/routes/auth.py:106`. |
| `/api/reports/schema` | public | 리포트 제출 폼 스키마(필드명 + 예시). 비밀값 없음. 클라이언트가 폼 렌더링용으로 사용. `/api/data/schema`(data:read)와 구별: reports schema는 폼 메타데이터, data schema는 운영 데이터 구조. [#1409](https://github.com/joshua-jingu-lee/ante/issues/1409) 70-route 결정 표에서 결정 (자세한 근거: [11-route-scope-table.md](11-route-scope-table.md) reports 섹션). |
| `/openapi.json` | public | OpenAPI 스키마 정적 자원. Agent와 외부 도구가 계약을 파싱한다. |
| `/docs` | public | Swagger UI. OpenAPI 탐색기. |
| `/redoc` | public | ReDoc. API 레퍼런스 문서. |
| `/api/auth/me` | gate-exempt-self-auth | 미들웨어 게이트는 면제하되 라우트가 직접 세션 쿠키 또는 Bearer 토큰을 검증해 본인 정보를 응답한다. 미인증이면 라우트가 401, 인증되었으면 self-only 응답. |

## PUBLIC_PREFIXES (접두어 일치)

| 접두어 | 카테고리 | 근거 |
|--------|---------|------|
| `/assets/*` | public | Vite 빌드 SPA 자산. `src/ante/web/app.py:347`에서 `app.mount("/assets", StaticFiles(...))`로 마운트된다. 인증된 사용자만 SPA 번들을 받게 하려면 로그인 페이지 자체가 동작할 수 없다. |

### SPA fallback 경로 — 비-`/api` 전체 면제 (정식 채택)

`SPAFallbackMiddleware`(`src/ante/web/app.py:357-377`)는 비-`/api` 경로에서 404가
나오면 `static_dir/<path>`가 실제 파일이면 그 파일을, 아니면 `index.html`을 돌려준다.
React Router 같은 client-side routing이 도입되면 임의 경로(`/login`, `/dashboard/...`,
`/strategies/...`, `/bots/...`, `/accounts/...`, `/treasury/...` 등)가 모두
`index.html`로 폴백된다. 이러한 SPA fallback 경로 자체는 default-deny 게이트에서
면제되어야 미인증 사용자가 로그인 화면을 받을 수 있다.

특히 사용자가 브라우저 주소창에 `/login`이나 `/strategies/abc` 같은 deep link로
**직접 진입**할 때, `RequireAuthMiddleware`가 `SPAFallbackMiddleware` 전에 실행되어
401을 반환하면 SPA 번들 자체가 로드되지 않아 로그인 화면을 표시할 수단이 없다.
PUBLIC_PATHS에 `/`와 `/index.html`만 등록하고 `/login` 같은 정확 일치를 누락하면
이 회귀가 발생한다.

따라서 #1403 구현은 **비-`/api` 모든 경로를 게이트에서 면제**한다. 구체적으로
`RequireAuthMiddleware`는 다음 단락 조건 중 어느 하나라도 만족하면 401을 던지지
않고 통과시킨다.

```
if not request.url.path.startswith("/api/") and request.url.path != "/api":
    # SPA fallback / 정적 자산 / SPA deep link 경로
    return await call_next(request)
```

이 분기 채택의 의미:

- 비-`/api` 경로는 정의상 보호 라우트가 아니다. 실제 응답은 정적 자산(있으면) 또는
  SPA `index.html` 폴백이며, 어느 쪽도 caller-sensitive 데이터를 노출하지 않는다.
- SPA가 React Router로 정의하는 모든 client-side route(`/login`, `/dashboard/*`,
  `/strategies/*`, `/bots/*`, `/accounts/*`, `/treasury/*`, 향후 추가 경로 포함)가
  자동으로 면제된다. PUBLIC_PATHS 테이블에 client-side route를 일일이 추가하는
  유지보수 부담이 없으며, 프론트엔드 라우팅 진화 대응이 1차 면제 분기 안에서
  완결된다.
- SPA가 로드된 뒤 보호 API를 호출할 때는 그 API가 default-deny + Bearer/세션 쿠키
  fallback으로 인증을 강제하므로 SPA 진입 단계의 게이트 면제와 충돌하지 않는다.

**비-`/api` 보호 표면이 신설될 경우**: 본 spec 작성 시점에 `src/ante/web/routes/`의
모든 라우터는 `/api/` 접두를 가진다(02-design-decisions.md "라우터 구성" 표). 향후
보호되어야 할 비-`/api` 라우트가 신설되면 본 spec의 SPA 면제 분기를 재검토하거나
해당 라우트만 별도 데코레이터/dependency로 인증을 강제해야 한다. 신설 시 본 표에
경고를 추가한다.

PUBLIC_PATHS 테이블의 `/`, `/index.html` 행은 본 분기 채택 후에도 SSOT 추적을 위해
남겨 둔다(코드 단의 명시적 allowlist 등록은 SPA 면제 분기로 흡수되어 사실상 잉여
이지만, SPA 진입점이 명시적으로 공개라는 의도를 문서가 보존한다).

## 결정 보류 항목 (`unresolved`)

본 표 작성 시점(#1403)에 결정 보류했던 두 항목은 [#1409](https://github.com/joshua-jingu-lee/ante/issues/1409) 70-route 결정 표에서 모두 결정 완료되었다. 현재 보류 항목은 없다.

| 경로 | 결정 | 결정 출처 |
|------|------|----------|
| `/api/system/status` | `system:read` scope 부착 (PUBLIC_PATHS 아님) | [11-route-scope-table.md](11-route-scope-table.md) system 섹션 — 운영 정보(account_count, last_health_check 등) 노출은 인증 토큰 보유자만. 모니터링도 system:read 토큰 사용. `/api/system/health`(public)와 구별. |
| `/api/reports/schema` | `public` (위 PUBLIC_PATHS 표에 추가됨) | [11-route-scope-table.md](11-route-scope-table.md) reports 섹션 — 리포트 제출 폼 스키마. 비밀값 없음. |

## 후보에서 제거된 항목

본 이슈 검토 과정에서 거론되었으나 코드/스펙 grep으로 확인되지 않아 allowlist에서
제거된 후보. 추후 해당 라우트가 신설되면 별도 이슈로 공개 여부를 결정한다.

| 후보 경로 | 제거 사유 |
|-----------|----------|
| `/static/*` | 실제 정적 자산 prefix는 `/assets/*`(`src/ante/web/app.py:347`). `/static/*`은 코드에 존재하지 않음. |
| `/api/signal/{key}/event` | `src/ante/web/routes/` grep에서 라우트 미발견. 1.0 범위에 존재하지 않으므로 allowlist 후보 아님. 신규 라우트 추가 시 별도 결정. |

## SSOT 운용 규칙

- 본 표는 정책 결정의 SSOT다. 실제 `PUBLIC_PATHS` / `PUBLIC_PREFIXES` Python 상수는
  #1403 구현 시 본 표를 그대로 반영한다.
- 새 공개 라우트 추가 시 다음 순서를 따른다.
  1. 본 표에 행 추가 (경로, 카테고리, 근거)
  2. #1409 70-route 결정 표 갱신
  3. 코드에서 `PUBLIC_PATHS` / `PUBLIC_PREFIXES`에 등록
- 공개 라우트가 더 이상 공개 정책에 맞지 않으면 본 표에서 행을 제거하고 같은 PR에서
  코드의 allowlist도 함께 제거한다. 표와 코드는 항상 동기화 상태를 유지한다.
