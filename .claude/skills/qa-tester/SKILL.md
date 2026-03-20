---
name: qa-tester
description: Docker 서버에서 Gherkin TC를 실행하고 결과를 리포트하는 QA 테스트 에이전트. 버그 발견 시 GitHub Issue 자동 등록.
argument-hint: [카테고리|all] [--fix]
user-invocable: true
allowed-tools: Bash, Read, Write, Grep, Glob, Agent, WebFetch
---

# QA 테스트 에이전트

$ARGUMENTS로 테스트 범위를 지정한다.

- `/qa-test account` — account 카테고리 TC만 실행
- `/qa-test all` — 전체 TC 실행
- `/qa-test scenario/full-pipeline` — 특정 Feature 실행
- `/qa-test account --fix` — 실패 시 자동 수정 시도

## 사전 조건

### 1. Docker 컨테이너 확인

```bash
docker ps --filter name=ante-qa --format '{{.Status}}'
```

컨테이너가 없거나 실행 중이 아니면 자동으로 기동한다:

```bash
docker compose -f docker-compose.qa.yml up -d --wait
```

### 2. 인증 토큰 확보

```bash
# 멤버 ID 확인
docker exec ante-qa ante member list --format json

# 토큰 획득
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"member_id": "<멤버ID>", "password": "<패스워드>"}'
```

응답에서 `access_token`을 추출하여 이후 API 호출에 `Authorization: Bearer $TOKEN` 헤더로 사용한다.

## 실행 흐름

### 1단계: .feature 파일 로드

$ARGUMENTS를 파싱하여 대상 TC 파일을 결정한다.

| 인자 | 대상 |
|------|------|
| `account` | `tests/tc/account/*.feature` |
| `all` | `tests/tc/**/*.feature` (전체 재귀 순회) |
| `scenario/full-pipeline` | `tests/tc/scenario/full-pipeline.feature` |

Glob 도구로 파일 목록을 수집하고, 각 `.feature` 파일을 Read 도구로 읽는다.

### 2단계: Scenario 순차 실행

Feature 파일 내 Scenario를 위에서 아래 순서로 실행한다.
각 Step을 자연어로 해석하여 실제 명령으로 변환한다.

Step 해석 규칙의 상세는 [gherkin-guide.md](gherkin-guide.md)를 참조한다.

**주요 Step 패턴:**

| Step 패턴 | 실행 방식 |
|-----------|----------|
| `When POST/GET/PUT/DELETE /api/...` | curl로 HTTP 요청 |
| `When 컨테이너에서 실행: ...` | `docker exec ante-qa {명령}` |
| `Then 응답 상태는 {코드}` | HTTP 상태 코드 검증 |
| `And 응답 body.{path} 는 ...` | JSON 응답 값 검증 |
| `And ...를 {변수}로 저장한다` | 응답값을 변수에 저장 |
| `And N초 대기` | `sleep N` |

### 3단계: 결과 기록

각 Scenario 실행 후 즉시 결과를 판정한다:

| 결과 | 조건 |
|------|------|
| **PASS** | 모든 Then/And 검증 통과 |
| **FAIL** | 검증 불일치 (실제값 vs 기대값 기록) |
| **ERROR** | 실행 자체 실패 (타임아웃, 연결 오류 등) |
| **SKIP** | 선행 Scenario 실패로 필요한 변수 미확보 |

### 4단계: 리포트 출력

모든 Scenario 실행 완료 후 [report-format.md](report-format.md)에 정의된 형식으로 리포트를 출력한다.

### 5단계: 버그 처리

FAIL인 Scenario에 대해 GitHub Issue를 자동 등록한다:

```bash
gh issue create \
  --title "QA: {Feature명} -- {Scenario명} 실패" \
  --label bug \
  --body "## TC 정보
- Feature: {파일 경로}
- Scenario: {이름}

## 실패 Step
{step 원문}

## 기대
{Then 문}

## 실제
{응답 상세}"
```

`--fix` 플래그가 있으면:
1. 등록된 이슈 번호로 `/implement-issue #{이슈번호}` 호출하여 즉시 수정 시도
2. 수정 후 해당 Scenario만 재실행하여 검증

## 주의사항

- Feature 내 Scenario는 위에서 아래 순서로 실행되며, 변수를 공유한다.
- Feature 간 변수는 공유하지 않는다. 새 Feature 파일 진입 시 변수를 초기화한다.
- 컨테이너 재시작이 필요하면 `docker compose -f docker-compose.qa.yml restart`를 사용한다.
- Background 블록의 Step은 매 Scenario 실행 전에 검증/실행한다.
