# Web API 모듈 세부 설계 - 70 라우트 scope 결정 표

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)
> 정책 SSOT: [D-015 default-deny 인증 게이트](../../decisions/D-015-default-deny-auth-gate.md)
> 게이트 단계 SSOT: [02-design-decisions.md — 인증 게이트 단계](02-design-decisions.md#인증-게이트-단계)
> 공개 경로 SSOT: [09-public-paths.md](09-public-paths.md)
> Scope vocabulary SSOT: [../member/02-design-decisions.md](../member/02-design-decisions.md) (도메인별 read/write/admin/run 표)

# 70 라우트 scope 결정 표 (Epic #1401)

본 문서는 `src/ante/web/routes/` 의 **모든 라우트(70개)** 에 대해
`require_*` dependency 부착 결정 SSOT를 row 단위로 명시한다.
후속 이슈 #1407(라우트 일관 부착), #1408(import 마이그레이션), #1405(정적 검증)는
본 표를 직접 인용해 코드 적용 / 검증을 수행한다.

## 결정 카테고리

| 카테고리 | 의미 |
|---------|------|
| `public` | [09-public-paths.md](09-public-paths.md) PUBLIC_PATHS allowlist. 인증 게이트 면제. 라우트도 caller-agnostic. |
| `gate-exempt-self-auth` | 미들웨어 게이트만 면제. 라우트가 자체적으로 세션/토큰을 검증하고 본인 정보만 응답. |
| `<domain>:<action>` | `require_scope("<domain>:<action>")` dependency 부착. spec scope vocabulary 정합. |
| `master-only` | master 호출자만 허용. service layer `MemberService._assert_master`가 1.0 계약 invariant. agent token / non-master human token이면 `403 Forbidden`. 표면 dependency 정렬은 #1543. (#1511 oracle drift, #1542 결정 방향 B) |

`authenticated-only` 카테고리는 본 표에서 사용하지 않는다. 모든 라우트에 대해
명시적 `public` / `gate-exempt-self-auth` / `<scope>` / `master-only` 결정을 둔다.

## 표의 컬럼

| 컬럼 | 의미 |
|------|------|
| Module | 라우터 파일 (`src/ante/web/routes/<module>.py`) |
| Method | HTTP method |
| Path | API path (router prefix 포함) |
| 현재 부착 dependency | 코드 grep `Depends(require_*)` 결과 — `master_caller` / `<scope>` / `(none)` |
| 결정 카테고리 | `public` / `gate-exempt-self-auth` / `<scope>` |
| Scope | `<domain>:<action>` (해당 시) |
| 근거 | spec vocabulary 정합 + 운영 가시성 |
| 후속 이슈 | 코드 마이그레이션을 처리할 이슈 (#1407 등) |

## 카운트 요약

총 70 라우트, 14 모듈:
accounts(9) + approvals(3) + audit(1) + auth(3) + bots(8) + config(2) + data(6)
+ members(9) + portfolio(2) + reports(4) + strategies(9) + system(4) + trades(1)
+ treasury(9) = **70**.

현재 부착 dependency: 17개
(`require_master_caller` 13 + `require_audit_read` 1 + `require_config_write` 1
+ `require_report_write` 1 + `require_strategy_write` 1).

본 표 결정 적용 대상: 70 라우트 전체.
이미 부착된 17개는 코드 grep 결과와 cross-check 완료.

**70 라우트 분해**:
- **17개**: 이미 dependency 부착 완료 (현재 head 기준 코드 부착됨).
- **48개**: scope 미부착 — 후속 #1407에서 `require_scope("<scope>")` 부착 대상.
  단, member admin mutation 7종(아래)은 #1542 결정으로 #1407 대상에서 분리되어
  `master-only` 카테고리로 이동했고, 표면 가드 정렬은 #1543이 담당한다.
- **5개**: 면제 라우트 — `public` 4개(`/api/system/health`, `/api/auth/login`, `/api/auth/logout`, `/api/reports/schema`) + `gate-exempt-self-auth` 1개(`/api/auth/me`). 본 표에서 결정 + [09-public-paths.md](09-public-paths.md) PUBLIC_PATHS allowlist로 처리 (`/api/reports/schema`는 본 이슈에서 09에 추가됨; 나머지 4개는 #1403 머지로 이미 처리됨).

후속 #1407 작업 대상은 **미부착 scope 라우트만**이며, 5개 면제 라우트와 7개
master-only 라우트(#1543 정렬 대상)는 #1407 변환 대상이 아니다.

## accounts (`/api/accounts`, 9 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| accounts | GET | `/api/accounts` | (none) | `<scope>` | `account:read` | spec `account:read` 정합. 계좌 목록은 trading-sensitive하므로 인증 필요. | #1407 |
| accounts | POST | `/api/accounts` | (none) | `<scope>` | `account:write` | spec `account:write` 정합. 계좌 생성은 cold-path지만 런타임에서도 인증 필요. | #1407 |
| accounts | GET | `/api/accounts/{account_id}` | (none) | `<scope>` | `account:read` | spec `account:read` 정합. 단건 조회. | #1407 |
| accounts | PUT | `/api/accounts/{account_id}` | `require_master_caller` | `<scope>` | `account:write` | spec `account:write` 정합. 현재 master_caller → #1407에서 `require_scope("account:write")`로 마이그레이션 예정. | #1407 |
| accounts | POST | `/api/accounts/{account_id}/suspend` | `require_master_caller` | `<scope>` | `account:write` | spec `account:write` 정합 (계좌 상태 전이). 현재 master_caller → #1407 마이그레이션. | #1407 |
| accounts | POST | `/api/accounts/{account_id}/activate` | `require_master_caller` | `<scope>` | `account:write` | spec `account:write` 정합 (계좌 상태 전이). 현재 master_caller → #1407 마이그레이션. | #1407 |
| accounts | DELETE | `/api/accounts/{account_id}` | (none) | `<scope>` | `account:write` | spec `account:write` 정합. 계좌 삭제는 cold-path지만 런타임에서도 인증 필요. | #1407 |
| accounts | GET | `/api/accounts/{account_id}/rules` | (none) | `<scope>` | `rule:read` | spec `rule` 도메인 read (룰 조회). account 도메인이 아님 — 룰은 별개 도메인. | #1407 |
| accounts | PUT | `/api/accounts/{account_id}/rules/{rule_type}` | `require_master_caller` | `<scope>` | `rule:admin` | spec `rule:admin` (룰 활성화/비활성화/수정). 현재 master_caller → #1407에서 `require_scope("rule:admin")`로 마이그레이션. | #1407 |

## approvals (`/api/approvals`, 3 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| approvals | GET | `/api/approvals` | (none) | `<scope>` | `approval:read` | spec `approval:read` 정합 (결재 조회). | #1407 |
| approvals | GET | `/api/approvals/{approval_id}` | (none) | `<scope>` | `approval:read` | spec `approval:read` 정합 (결재 상세 조회). | #1407 |
| approvals | PATCH | `/api/approvals/{approval_id}/status` | (none) | `<scope>` | `approval:admin` | spec `approval:admin` 정합 (결재 승인/거부). `approval:write`(요청/철회)와 구별. | #1407 |

## audit (`/api/audit`, 1 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| audit | GET | `/api/audit` | `require_audit_read` | `<scope>` | `audit:read` | spec `audit:read` 정합. 이미 코드 부착됨 (#1359). | — |

## auth (`/api/auth`, 3 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| auth | POST | `/api/auth/login` | (none) | `public` | — | PUBLIC_PATHS allowlist ([09-public-paths.md](09-public-paths.md)). 인증 자체를 수행. | — |
| auth | POST | `/api/auth/logout` | (none) | `public` | — | PUBLIC_PATHS allowlist. 세션 만료 상태에서도 호출 가능해야 함. | — |
| auth | GET | `/api/auth/me` | (none) | `gate-exempt-self-auth` | — | 미들웨어 게이트만 면제, 라우트가 자체적으로 세션/토큰 검증해 본인 정보만 응답. dashboard 초기 로딩 호환. | — |

## bots (`/api/bots`, 8 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| bots | GET | `/api/bots` | (none) | `<scope>` | `bot:read` | spec `bot:read` 정합 (봇 상태 조회). | #1407 |
| bots | POST | `/api/bots` | `require_master_caller` | `<scope>` | `bot:admin` | spec `bot:admin` 정합 (봇 생성). 현재 master_caller → #1407 마이그레이션. spec 도메인 표에 `bot:write`는 없음, mutation은 `bot:admin`. | #1407 |
| bots | GET | `/api/bots/{bot_id}` | (none) | `<scope>` | `bot:read` | spec `bot:read` 정합. | #1407 |
| bots | POST | `/api/bots/{bot_id}/start` | (none) | `<scope>` | `bot:admin` | spec `bot:admin` 정합 (봇 운영 제어). | #1407 |
| bots | POST | `/api/bots/{bot_id}/stop` | (none) | `<scope>` | `bot:admin` | spec `bot:admin` 정합 (봇 운영 제어). | #1407 |
| bots | DELETE | `/api/bots/{bot_id}` | `require_master_caller` | `<scope>` | `bot:admin` | spec `bot:admin` 정합 (봇 삭제). 현재 master_caller → #1407 마이그레이션. | #1407 |
| bots | PUT | `/api/bots/{bot_id}` | `require_master_caller` | `<scope>` | `bot:admin` | spec `bot:admin` 정합 (봇 설정 변경). 현재 master_caller → #1407 마이그레이션. | #1407 |
| bots | GET | `/api/bots/{bot_id}/logs` | (none) | `<scope>` | `bot:read` | spec `bot:read` 정합 (봇 상태/로그 조회). | #1407 |

## config (`/api/config`, 2 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| config | GET | `/api/config` | (none) | `<scope>` | `config:read` | spec `config:read` 정합. | #1407 |
| config | PUT | `/api/config/{key:path}` | `require_config_write` | `<scope>` | `config:write` | spec `config:write` 정합. 이미 코드 부착됨 (#1373). | — |

## data (`/api/data`, 6 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| data | GET | `/api/data/datasets` | (none) | `<scope>` | `data:read` | spec `data:read` 정합. | #1407 |
| data | GET | `/api/data/datasets/{dataset_id}` | (none) | `<scope>` | `data:read` | spec `data:read` 정합. | #1407 |
| data | GET | `/api/data/schema` | (none) | `<scope>` | `data:read` | spec `data:read` 정합. data 도메인은 trading-sensitive하므로 스키마도 인증 필요. `/api/reports/schema`(public)와 구별: reports schema는 폼 메타데이터, data schema는 운영 데이터 구조. | #1407 |
| data | GET | `/api/data/storage` | (none) | `<scope>` | `data:read` | spec `data:read` 정합 (용량 현황 조회). | #1407 |
| data | DELETE | `/api/data/datasets/{dataset_id}` | (none) | `<scope>` | `data:write` | spec `data:write` 정합 (데이터셋 삭제 = mutation). | #1407 |
| data | GET | `/api/data/feed-status` | (none) | `<scope>` | `data:read` | spec `data:read` 정합 (Feed 파이프라인 상태 조회). | #1407 |

## members (`/api/members`, 9 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| members | GET | `/api/members` | (none) | `<scope>` | `member:read` | spec `member:read` 정합 (멤버 목록). | #1407 |
| members | POST | `/api/members` | (none) | `master-only` | — | **master-only** (멤버 등록). MemberService `_assert_master`가 1.0 계약 invariant. `member:admin` scope는 reserved (1.0 미사용). 표면 가드 정렬은 #1543. (#1511 oracle drift, #1542 결정 방향 B) | #1543 |
| members | GET | `/api/members/{member_id}` | (none) | `<scope>` | `member:read` | spec `member:read` 정합. | #1407 |
| members | POST | `/api/members/{member_id}/suspend` | (none) | `master-only` | — | **master-only** (멤버 정지). `_assert_master` 강제. (#1511 oracle drift, #1542 결정 방향 B) | #1543 |
| members | POST | `/api/members/{member_id}/reactivate` | (none) | `master-only` | — | **master-only** (멤버 재활성화). `_assert_master` 강제. (#1511 oracle drift, #1542 결정 방향 B) | #1543 |
| members | POST | `/api/members/{member_id}/revoke` | (none) | `master-only` | — | **master-only** (멤버 영구 폐기). `_assert_master` 강제. (#1511 oracle drift, #1542 결정 방향 B) | #1543 |
| members | POST | `/api/members/{member_id}/rotate-token` | (none) | `master-only` | — | **master-only** (토큰 재발급). `_assert_master` 강제. (#1511 oracle drift, #1542 결정 방향 B) | #1543 |
| members | PATCH | `/api/members/{member_id}/password` | `require_master_caller` | `master-only` | — | **master-only** (패스워드 변경). 현재 `require_master_caller` 부착됨 → #1543에서 master-only dependency 정합. (#1511 oracle drift, #1542 결정 방향 B) | #1543 |
| members | PUT | `/api/members/{member_id}/scopes` | (none) | `master-only` | — | **master-only** (권한 범위 변경). `_assert_master` 강제. (#1511 oracle drift, #1542 결정 방향 B) | #1543 |

## portfolio (`/api/portfolio`, 2 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| portfolio | GET | `/api/portfolio/value` | (none) | `<scope>` | `treasury:read` | portfolio는 `treasury_daily_snapshots` 테이블을 읽어 응답한다. 데이터 출처가 treasury이므로 spec `treasury:read` 정합. 별도 `portfolio` 도메인 신설 안 함. | #1407 |
| portfolio | GET | `/api/portfolio/history` | (none) | `<scope>` | `treasury:read` | portfolio history도 동일 `treasury_daily_snapshots` 시계열 출처. spec `treasury:read` 정합. | #1407 |

## reports (`/api/reports`, 4 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| reports | GET | `/api/reports/schema` | (none) | `public` | — | 리포트 제출 폼 스키마(필드명 + 예시). 비밀값 없음. 클라이언트가 폼 렌더링용으로 사용. `/api/data/schema`(data:read)와 구별: reports schema는 폼 메타데이터, data schema는 운영 데이터 구조. 본 이슈에서 결정. [09-public-paths.md](09-public-paths.md) PUBLIC_PATHS 목록에 추가됨. | — (면제 라우트, #1407 대상 아님) |
| reports | POST | `/api/reports` | `require_report_write` | `<scope>` | `report:write` | spec `report:write` 정합. 이미 코드 부착됨. | — |
| reports | GET | `/api/reports/{report_id}` | (none) | `<scope>` | `report:read` | spec `report:read` 정합. | #1407 |
| reports | GET | `/api/reports` | (none) | `<scope>` | `report:read` | spec `report:read` 정합. | #1407 |

## strategies (`/api/strategies`, 9 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| strategies | POST | `/api/strategies/validate` | (none) | `<scope>` | `strategy:write` | spec `strategy:write` 정합 (전략 등록/검증). | #1407 |
| strategies | GET | `/api/strategies` | (none) | `<scope>` | `strategy:read` | spec `strategy:read` 정합. | #1407 |
| strategies | PATCH | `/api/strategies/{strategy_id}/status` | `require_strategy_write` | `<scope>` | `strategy:write` | spec `strategy:write` 정합 (전략 상태 변경). 이미 코드 부착됨. | — |
| strategies | GET | `/api/strategies/{strategy_id}` | (none) | `<scope>` | `strategy:read` | spec `strategy:read` 정합. | #1407 |
| strategies | GET | `/api/strategies/{strategy_id}/performance` | (none) | `<scope>` | `strategy:read` | spec `strategy:read` 정합 (전략 성과 지표 조회). | #1407 |
| strategies | GET | `/api/strategies/{strategy_id}/daily-summary` | (none) | `<scope>` | `strategy:read` | spec `strategy:read` 정합. | #1407 |
| strategies | GET | `/api/strategies/{strategy_id}/weekly-summary` | (none) | `<scope>` | `strategy:read` | spec `strategy:read` 정합. | #1407 |
| strategies | GET | `/api/strategies/{strategy_id}/monthly-summary` | (none) | `<scope>` | `strategy:read` | spec `strategy:read` 정합. | #1407 |
| strategies | GET | `/api/strategies/{strategy_id}/trades` | (none) | `<scope>` | `strategy:read` | spec `strategy:read` 정합 (전략 거래 내역). | #1407 |

## system (`/api/system`, 4 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| system | GET | `/api/system/health` | (none) | `public` | — | PUBLIC_PATHS allowlist ([09-public-paths.md](09-public-paths.md)). reverse proxy / 모니터링 헬스체크. 인증 요구 시 운영 인프라가 헬스 판정 불가. | — |
| system | GET | `/api/system/status` | (none) | `<scope>` | `system:read` | spec `system:read` 정합 (시스템 상태 조회). 운영 정보(account_count, last_health_check 등) 노출은 인증 토큰 보유자만. 모니터링도 system:read 토큰 사용. `/api/system/health`만 public. 본 이슈에서 결정. | #1407 |
| system | POST | `/api/system/halt` | `require_master_caller` | `<scope>` | `system:admin` | spec `system:admin` 정합 (시스템 상태 변경 — kill switch). 현재 master_caller → #1407 마이그레이션. | #1407 |
| system | POST | `/api/system/clear-halt` | `require_master_caller` | `<scope>` | `system:admin` | spec `system:admin` 정합 (kill switch 해제). 현재 master_caller → #1407 마이그레이션. | #1407 |

## trades (`/api/trades`, 1 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| trades | GET | `/api/trades` | (none) | `<scope>` | `trade:read` | spec `trade:read` 정합 (거래 내역 조회). spec 도메인 표에 `trade:write`/`trade:admin`은 없음 — 거래 내역은 시스템이 기록, 사용자 mutation 라우트 없음. | #1407 |

## treasury (`/api/treasury`, 9 라우트)

| Module | Method | Path | 현재 부착 dependency | 결정 카테고리 | Scope | 근거 | 후속 이슈 |
|--------|--------|------|---------------------|--------------|-------|------|----------|
| treasury | GET | `/api/treasury` | (none) | `<scope>` | `treasury:read` | spec `treasury:read` 정합 (자금 현황 조회). | #1407 |
| treasury | GET | `/api/treasury/transactions` | (none) | `<scope>` | `treasury:read` | spec `treasury:read` 정합. | #1407 |
| treasury | POST | `/api/treasury/bots/{bot_id}/allocate` | `require_master_caller` | `<scope>` | `treasury:admin` | spec `treasury:admin` 정합 (예산 설정/자금 투입). spec 도메인 표에 `treasury:write`는 없음, mutation은 `treasury:admin`. 현재 master_caller → #1407 마이그레이션. | #1407 |
| treasury | POST | `/api/treasury/bots/{bot_id}/deallocate` | `require_master_caller` | `<scope>` | `treasury:admin` | spec `treasury:admin` 정합 (예산 회수). 현재 master_caller → #1407 마이그레이션. | #1407 |
| treasury | GET | `/api/treasury/budgets` | (none) | `<scope>` | `treasury:read` | spec `treasury:read` 정합 (봇별 예산 목록). | #1407 |
| treasury | POST | `/api/treasury/balance` | `require_master_caller` | `<scope>` | `treasury:admin` | spec `treasury:admin` 정합 (계좌 잔고 수동 설정). 현재 master_caller → #1407 마이그레이션. | #1407 |
| treasury | GET | `/api/treasury/snapshots/latest` | (none) | `<scope>` | `treasury:read` | spec `treasury:read` 정합. | #1407 |
| treasury | GET | `/api/treasury/snapshots` | (none) | `<scope>` | `treasury:read` | spec `treasury:read` 정합. | #1407 |
| treasury | GET | `/api/treasury/snapshots/{date}` | (none) | `<scope>` | `treasury:read` | spec `treasury:read` 정합. | #1407 |

## Scope vocabulary 정합

본 표에서 사용한 모든 scope는 [../member/02-design-decisions.md](../member/02-design-decisions.md)
도메인별 read/write/admin/run 표에 이미 정의되어 있다.
**신규 scope vocabulary 도입은 없다.**

사용 scope 목록 (1.0 기준):
- `account:read`, `account:write`
- `approval:read`, `approval:admin`
- `audit:read`
- `bot:read`, `bot:admin`
- `config:read`, `config:write`
- `data:read`, `data:write`
- `member:read` (mutation은 `master-only` 카테고리 사용 — 아래 메모 참조)
- `report:read`, `report:write`
- `rule:read`, `rule:admin`
- `strategy:read`, `strategy:write`
- `system:read`, `system:admin`
- `trade:read`
- `treasury:read`, `treasury:admin`

(`portfolio` 도메인은 신설하지 않고 `treasury:read`에 묶었다. portfolio 라우트가 `treasury_daily_snapshots` 데이터를 직접 읽는 view 성격이기 때문이다.)

> `member:admin` scope는 vocabulary([../member/02-design-decisions.md](../member/02-design-decisions.md))에
> 정의되어 있으나 1.0 계약에서는 **reserved (현재 미사용)**다. member admin
> mutation 7종(`POST /api/members`, `/suspend`, `/reactivate`, `/revoke`,
> `/rotate-token`, `PATCH .../password`, `PUT .../scopes`)은 본 표에서
> `master-only` 카테고리로 결정되며, agent에게 위임하지 않는다.
> (#1511 oracle drift, #1542 결정 방향 B)

## 경계 케이스 결정

본 이슈에서 사용자/오케스트레이터 정책 판단이 필요했던 경계 케이스 3건:

| Path | 결정 | 근거 |
|------|------|------|
| `GET /api/system/status` | `system:read` | 운영 정보(account_count, last_health_check 등) 노출은 인증 토큰 보유자만. 모니터링도 system:read 토큰 사용. `/api/system/health`(public)와 구별. |
| `GET /api/reports/schema` | `public` | 리포트 제출 폼 스키마. 비밀값 없음. 클라이언트가 폼 렌더링용으로 사용. `/api/data/schema`(data:read)와 다른 정책 — data 도메인은 trading-sensitive. |
| `GET /api/auth/me` | `gate-exempt-self-auth` | 미들웨어 게이트는 면제하되 라우트가 자체 세션/토큰 검증해 본인 정보만 응답. dashboard 초기 로딩 호환. |

## 후속 작업 (#1407 / #1543)

#1407 코드 마이그레이션 대상은 **scope 라우트 48개 + master_caller 마이그레이션
13개**였다. 면제 라우트 5개(public 4 + gate-exempt-self-auth 1)는 #1407 대상이
**아니며**, [09-public-paths.md](09-public-paths.md) PUBLIC_PATHS allowlist로 처리한다
(4개는 #1403 머지로 이미 처리, `/api/reports/schema`는 본 이슈에서 09에 추가됨).

#1542 결정 방향 B에 따라 member admin mutation 7종은 본 표에서 `master-only`
카테고리로 분리되었으며, 표면 가드 정렬은 #1543이 담당한다 (#1407 scope dependency
대상에서 제외).

- 미부착 **scope 라우트**에 `require_scope("<scope>")` 부착.
- 이미 부착된 `require_master_caller` 라우트를 `require_scope("<scope>")`로 마이그레이션:
  - `PUT /api/accounts/{id}` → `account:write`
  - `POST /api/accounts/{id}/suspend` → `account:write`
  - `POST /api/accounts/{id}/activate` → `account:write`
  - `PUT /api/accounts/{id}/rules/{type}` → `rule:admin`
  - `POST /api/bots` → `bot:admin`
  - `DELETE /api/bots/{id}` → `bot:admin`
  - `PUT /api/bots/{id}` → `bot:admin`
  - `POST /api/system/halt` → `system:admin`
  - `POST /api/system/clear-halt` → `system:admin`
  - `POST /api/treasury/bots/{id}/allocate` → `treasury:admin`
  - `POST /api/treasury/bots/{id}/deallocate` → `treasury:admin`
  - `POST /api/treasury/balance` → `treasury:admin`
- `PATCH /api/members/{id}/password`는 현재 `require_master_caller`로 부착되어
  있으며, #1543에서 master-only dependency로 정합한다(scope vocabulary 매핑이
  아닌 master-only 정렬). #1542 결정 방향 B로 본 라우트는 `member:admin` scope
  대상에서 제외됨.
- `GET /api/reports/schema`를 [09-public-paths.md](09-public-paths.md) PUBLIC_PATHS allowlist에 추가.
- 이미 부착된 4개 (`audit:read`, `config:write`, `report:write`, `strategy:write`)는 표 결정과 일치 — 변경 없음.

### #1543 master-only 정렬 대상 (member admin mutation 7종)

#1542 결정에 따라 다음 라우트는 표면 dependency를 master-only로 정렬한다.

- `POST /api/members`
- `POST /api/members/{id}/suspend`
- `POST /api/members/{id}/reactivate`
- `POST /api/members/{id}/revoke`
- `POST /api/members/{id}/rotate-token`
- `PATCH /api/members/{id}/password`
- `PUT /api/members/{id}/scopes`

`member:admin` scope는 reserved (1.0 미사용)로 vocabulary에서 유지하되, agent
token에 부여되어도 service layer `_assert_master`에서 거부된다. 정렬 코드 변경,
`frontend/openapi.json` / `frontend/src/types/api.generated.ts` 재생성, oracle host
probe 기대값 정렬은 #1543 / #1544 후속 이슈에서 처리한다.

## Spec-Code Drift 처리

본 이슈 작업 중 발견한 [05-resource-endpoints.md](05-resource-endpoints.md) drift 2건을 같이 정정한다:

- `GET /api/accounts/{account_id}/credentials` — spec 표에 있으나 코드에 라우트 없음 → 코드 SSOT 원칙에 따라 spec에서 제거. 다음 spec 위치를 모두 정정한다:
  - [05-resource-endpoints.md](05-resource-endpoints.md) account 리소스 표 (정정 완료)
  - [../account/10-web-api.md](../account/10-web-api.md) 계좌 전용 엔드포인트 목록 (정정 완료)
  - [../account/13-cross-module-notes.md](../account/13-cross-module-notes.md) Web API 런타임 허용 엔드포인트 나열 (정정 완료)
  - [../account/02-design-decisions.md](../account/02-design-decisions.md) D-ACC-07 런타임 중 허용 표 — CLI(`account credentials`)는 보존하고 Web API 컬럼만 "미제공"으로 표시 (정정 완료)
  - 실제 인증정보 마스킹 조회는 CLI `account credentials`만 제공한다. Web API 구현이 필요해지면 별도 follow-up 이슈로 추가한다.
- `PATCH /api/strategies/{strategy_id}/status` — 코드에 있으나 spec 표에 없음 → spec 표에 추가.
