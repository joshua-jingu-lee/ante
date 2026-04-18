# PR 코드 리뷰 스킬

> Claude PR 승인 워커와 Codex PR 승인 워커가 공유하는 **최종 승인 체크 계약**이다.
> 일반적인 메타 리뷰나 계획 정합성 리뷰는 `.agent/agents/code-reviewer.md`가 담당한다.

## 트리거

- `pull_request` opened / synchronize / ready_for_review / reopened
- 수동 재검증이 필요한 경우 해당 PR 번호를 입력으로 실행

## 인자

$ARGUMENTS — PR 번호 (예: 42)

## 이 스킬이 하는 일과 하지 않는 일

- **한다**: PR head SHA 기준으로 approve / fail 판단을 내린다.
- **한다**: blocking finding, follow-up, executed / inferred 검증을 구조화해서 남긴다.
- **하지 않는다**: 계획 자체를 새로 짜지 않는다.
- **하지 않는다**: 반복 failure의 근본 원인 분석을 끝까지 맡지 않는다.
  - 그 상황은 `.agent/agents/code-reviewer.md`의 메타 리뷰 범위다.

## 실행 절차

### 0단계: 원래 의도 정렬

PR diff를 보기 전에 먼저 아래를 맞춘다.

1. 이슈 번호, 유저스토리, 수용 조건
2. PR 본문 요약과 변경 의도
3. 관련 스펙 문서
4. 최근 branch review / approval에서 지적된 핵심 finding

이 단계의 질문은 하나다.

`이 PR은 원래 무엇을 바꾸려는 것이었나?`

이 질문에 답하지 못하면 diff 리뷰를 깊게 진행하지 않는다.

### 1단계: PR 정보 수집

```bash
gh pr view #{PR번호} --json title,body,baseRefName,headRefName,labels,files
gh pr diff #{PR번호} --name-only
gh pr diff #{PR번호}
```

연관 이슈 번호를 PR 본문에서 추출한다. 패턴은 `Closes #N`, `Refs #N`을 우선 사용한다.

### 2단계: 컨텍스트 로딩

기본 문서는 항상 읽는다.

- 관련 GitHub 이슈
- 관련 `docs/specs/{모듈}/{모듈}.md`
- `docs/architecture/`

추가 컨텍스트는 변경 성격에 따라 읽는다.

| 변경 영역 / 신호 | 로딩 대상 |
|---|---|
| `src/ante/web/` | `docs/specs/web-api/web-api.md`, `.agent/skills/contract-drift-review.md` |
| `src/ante/{모듈}/` | `docs/specs/{모듈}/{모듈}.md`, `.agent/skills/module-conventions.md` |
| `frontend/` | `docs/dashboard/architecture.md`, `.agent/skills/frontend-conventions.md`, `.agent/skills/generated-artifact-sync.md` |
| async 코드 포함 | `.agent/skills/asyncio-patterns.md` |
| DB/DML/DDL 포함 | `.agent/skills/sqlite-patterns.md`, `.agent/skills/generated-artifact-sync.md` |
| 캐시/세션/클라이언트/브로커/게이트웨이/설정 변경 | `.agent/skills/lifecycle-review.md` |
| OpenAPI, schema, 생성 타입, CLI/DB 생성 문서 변경 | `.agent/skills/contract-drift-review.md`, `.agent/skills/generated-artifact-sync.md` |

### 3단계: 리뷰 확장 조건

아래 red flag가 보이면 **수정된 파일만 읽고 끝내지 않는다.**

- mutable config가 long-lived adapter에 주입된다
- 캐시 무효화, 재연결, 재초기화, 재생성이 포함된다
- endpoint / schema / field / CLI 인자 이름이 바뀐다
- 생성 산출물을 함께 갱신해야 할 가능성이 있다
- 테스트가 상태 전이보다 단순 snapshot에 치우쳐 있다
- 최근 review failure와 같은 `risk class`가 반복된다

이 경우 생성자, 팩토리, 캐시 보관소, 호출자, 소비자, 생성 산출물까지 따라간다.

### 4단계: 체크리스트 검증

각 항목은 `PASS / FAIL / N/A`로 판정한다.

#### A. 계획 및 이슈 정합성

| # | 검증 항목 | 판정 기준 |
|---|---|---|
| A1 | 원래 의도 일치 | 이슈 수용 조건과 PR 설명이 같은 변경을 말하는가 |
| A2 | 유저스토리 충족 | 이슈의 모든 US가 구현되었는가 |
| A3 | 수용 조건 충족 | 완료 조건이 모두 만족되는가 |
| A4 | 범위 초과 변경 없음 | 이슈에 없는 구조 변경이 숨어 있지 않은가 |

#### B. 계약 및 표류 방지

| # | 검증 항목 | 판정 기준 |
|---|---|---|
| B1 | 스펙 문서 일치 | 구현이 `docs/specs/`와 일치하는가 |
| B2 | 계약 표류 없음 | API/CLI/schema/field rename이 소비자와 함께 반영되었는가 |
| B3 | 생성 산출물 동기화 | OpenAPI, generated types, 생성 문서가 함께 갱신되었는가 |

#### C. 상태 전이 및 수명주기

| # | 검증 항목 | 판정 기준 |
|---|---|---|
| C1 | 캐시 무효화 후 일관성 | 캐시 삭제 뒤 다음 호출에서 새 인스턴스가 올바르게 동작하는가 |
| C2 | 재연결 / 재초기화 보장 | 설정 변경 후 장기 생존 객체가 새 설정으로 재초기화되는가 |
| C3 | 호출자 영향 추적 | 직접 수정되지 않은 소비자 경로까지 확인했는가 |
| C4 | 운영 헬스 / 후속 동작 정합성 | health, readiness, background task, retry 등 운영 경로가 새 계약을 따르는가 |

#### D. 코드 품질

| # | 검증 항목 | 판정 기준 |
|---|---|---|
| D1 | 컨벤션 준수 | 대상 영역의 skills/ 컨벤션을 따르는가 |
| D2 | 사이드이펙트 통제 | 다른 모듈에 의도하지 않은 영향이 없는가 |
| D3 | 에러 처리 | 예외 계층, HTTP 상태 코드, 에러 경로가 적절한가 |
| D4 | 보안 | OWASP 성격 취약점이 없는가 |

#### E. 검증 증거

| # | 검증 항목 | 판정 기준 |
|---|---|---|
| E1 | 테스트 존재 | 변경을 지키는 테스트가 있는가 |
| E2 | 상태 전이 / 엣지 케이스 | 경계값, 에러 경로, 설정 변경 후 동작까지 커버되는가 |
| E3 | 실행 검증 명시 | 실제로 돌린 검증과 추론만 한 검증이 구분되어 남는가 |

#### F. PR 형식

| # | 검증 항목 | 판정 기준 |
|---|---|---|
| F1 | 커밋 메시지 | Conventional Commits 형식을 따르는가 |
| F2 | PR 크기 | 변경 규모가 한 번에 검토 가능한 수준인가 |
| F3 | base 브랜치 | 독립 이슈는 `main`, 에픽 하위는 `epic/*`인가 |

#### G. 프론트엔드

`frontend/`가 바뀐 경우에만 적용한다.

| # | 검증 항목 | 판정 기준 |
|---|---|---|
| G1 | 디자인 토큰 준수 | 시맨틱 토큰만 사용했는가 |
| G2 | 타이포그래피 체계 | 프로젝트가 정한 타입 스케일을 따르는가 |
| G3 | API 임의 생성 금지 | 백엔드에 없는 엔드포인트를 만들지 않았는가 |
| G4 | 자동 생성 타입 사용 | 수동 API 응답 타입 정의가 없는가 |
| G5 | 데이터 흐름 | `api -> hooks -> pages -> components` 패턴을 따르는가 |
| G6 | 빌드 통과 | `npm run build` 또는 동등 검증이 성공하는가 |

### 5단계: 결과 구조화

승인 워커는 GitHub review 제출보다 **구조화된 결과 반환**을 우선한다.
자동화 래퍼가 이 결과를 status check와 PR 코멘트로 변환한다.

```json
{
  "approved": false,
  "summary": "헬스체크 계약은 맞췄지만, 브로커 캐시 재생성 후 재연결이 보장되지 않아 운영 회귀가 남아 있습니다.",
  "blocking_findings": [
    {
      "title": "브로커 캐시 무효화 후 재연결이 누락됨",
      "severity": "critical",
      "risk_class": "lifecycle",
      "explanation": "credentials 변경 후 첫 조회/주문이 실패할 수 있습니다.",
      "files": [
        "src/ante/account/service.py",
        "src/ante/gateway/gateway.py"
      ],
      "suggested_fix": "캐시 제거 후 새 broker 인스턴스의 connect 경로를 보장하고 회귀 테스트를 추가합니다."
    }
  ],
  "followups": [
    "generated artifact sync 확인"
  ],
  "executed_checks": [
    "pytest tests/unit/test_account.py -q"
  ],
  "inferred_checks": [
    "KIS reconnect path는 코드 독해로만 확인"
  ],
  "risk_flags": [
    "lifecycle",
    "contract-drift"
  ],
  "recommended_next_step": "invoke-code-reviewer"
}
```

## 판정 원칙

1. **객관적 기준만 적용**
   - 애매한 취향 차이는 FAIL 사유가 아니다.
2. **스펙이 SSOT**
   - 구현과 스펙이 다르면 구현이 틀린 것이다.
3. **수정된 파일만 보지 않는다**
   - red flag가 있으면 생성자, 호출자, 소비자까지 넓힌다.
4. **실행과 추론을 구분한다**
   - 실제 실행한 검증과 코드 독해 추론을 섞어 쓰지 않는다.
5. **반복 risk class는 에스컬레이션 신호다**
   - 같은 `risk class`가 2회 반복되면 `.agent/agents/code-reviewer.md` 호출을 권고한다.
