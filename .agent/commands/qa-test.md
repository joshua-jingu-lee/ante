지정된 Gherkin TC(.feature)를 Docker 서버에서 실행하고 결과를 리포트한다.

## 인자

$ARGUMENTS — 테스트 대상 (예: account, bot/lifecycle, scenario/full-pipeline)
- 카테고리명: `account` → tests/tc/account/*.feature 전체
- 특정 파일: `bot/lifecycle` → tests/tc/bot/lifecycle.feature
- `--fix` 플래그 추가 시 FAIL 발견 즉시 수정 시도

## 에이전트 역할 분담

| 단계 | 담당 | 에이전트 |
|------|------|----------|
| 1~5 (TC 실행) | QA 에이전트 | `@qa-engineer` |
| 6 (버그 수정) | 개발 에이전트 | `@backend-dev` 또는 `@frontend-dev` |

## 작업 흐름

### 1단계: 사전 조건 확인 (오케스트레이터)

```
1. Docker 컨테이너 확인
   docker ps --filter name=ante-qa --format '{{.Status}}'

   - 실행 중이 아니면:
     docker compose -f docker-compose.qa.yml up -d --wait
     최대 30초 대기 후 헬스체크 확인

   - 빌드 실패 또는 기동 실패 시: @devops에 해결 위임
     Agent(
       subagent_type="devops",
       prompt="QA Docker 환경이 기동되지 않는다. 해결하라.
       ## 실패 로그
       {docker compose 출력 로그}"
     )
     @devops가 수정하면 재빌드 → 기동 → 헬스체크를 거쳐 TC 실행을 속행한다.
     코드 변경에 의한 빌드 깨짐은 빈번하므로 원인이 다르면 새 시도로 카운트한다.
     동일 원인으로 2회 연속 실패 시에만 ERROR 처리하고 종료.

2. .feature 파일 존재 확인
   $ARGUMENTS를 해석하여 대상 파일이 있는지 확인한다.
   없으면 "TC 파일이 없습니다: tests/tc/{$ARGUMENTS}" 보고 후 종료.
```

### 2단계: TC 실행 위임 (QA 에이전트)

`@qa-engineer`에 TC 실행을 위임한다. 에이전트는 `qa-tester` 스킬을 내장하고 있으므로 별도 스킬 참조 지시는 불필요하다.

```
Agent(
  subagent_type="qa-engineer",
  prompt="""
다음 TC를 실행하고 리포트를 반환하라.

## 대상
{$ARGUMENTS 해석 결과 — 카테고리명 또는 파일 경로}

## 실행 규칙
- Feature 내 Scenario는 위에서 아래 순서로 실행, 변수 공유
- Feature 간 변수는 공유하지 않음
- Background는 각 Scenario 시작 전 매번 확인
- Data Table의 field-value 쌍은 JSON body로 변환

## 반환 형식
Feature별 PASS/FAIL/ERROR/SKIP 카운트와 FAIL 상세를 포함한 리포트.
"""
)
```

### 3단계: 버그 처리 (오케스트레이터)

QA 에이전트 리포트에서 FAIL이 있는 경우:

```bash
gh issue create \
  --title "QA: {Feature명} — {Scenario명} 실패" \
  --label bug \
  --body "## TC 정보
- Feature: {파일 경로}
- Scenario: {이름}

## 실패 Step
{step 원문}

## 기대 결과
{Then 문}

## 실제 결과
{응답 상세 — status code + body}

## 재현 명령
{실행한 curl/docker exec 명령 그대로}"
```

**--fix 플래그가 있으면:**
1. 위 이슈 등록 후 즉시 `/implement-issue #{이슈번호}` 호출 (개발 에이전트에 위임)
2. 수정 완료 후 해당 Scenario만 `@qa-engineer`에 재검증 위임
3. PASS 시 이슈 자동 close, 여전히 FAIL이면 이슈를 열어둔 채 다음 Scenario로 진행

## 주의사항

- Feature 내 Scenario는 순서 의존적 — 위에서 아래로 실행, 변수 공유
- Feature 간 변수는 공유하지 않음 — 각 .feature 시작 시 변수 초기화
- `또는`이 포함된 Then문: 앞 조건 FAIL 시 뒤 조건으로 재검증
