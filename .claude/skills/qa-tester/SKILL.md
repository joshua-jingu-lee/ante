# QA 테스트 Gherkin Step 해석 가이드

> `/qa-test` 및 `/qa-sweep` 커맨드 실행 시 이 스킬을 참조한다.
> 이 문서는 **지식(Step 해석 규칙)**만 정의한다. 실행 워크플로우는 커맨드에 정의되어 있다.
> - 단일 실행: `.claude/commands/qa-test.md`
> - 전수 검사: `.claude/commands/qa-sweep.md`

## 1. Step 해석 총칙

Gherkin의 각 Step을 자연어로 해석하여 실제 명령으로 변환한다.
Step definitions 코드 없이, 에이전트가 패턴 매칭으로 실행한다.

상세 변환 규칙은 [gherkin-guide.md](gherkin-guide.md)를 참조한다.

### 주요 Step 패턴 요약

| Step 패턴 | 실행 방식 |
|-----------|----------|
| `When POST/GET/PUT/DELETE /api/...` | curl로 HTTP 요청 |
| `When 컨테이너에서 실행: ...` | `docker exec ante-qa {명령}` |
| `Then 응답 상태는 {코드}` | HTTP 상태 코드 검증 |
| `And 응답 body.{path} 는 ...` | JSON 응답 값 검증 |
| `And ...를 {변수}로 저장한다` | 응답값을 변수에 저장 |
| `And N초 대기` | `sleep N` |

## 2. 결과 판정 기준

| 결과 | 조건 |
|------|------|
| **PASS** | Scenario 내 모든 Then/And 검증 통과 |
| **FAIL** | 하나라도 검증 불일치 — 기대값 vs 실제값을 상세 기록 |
| **ERROR** | Step 실행 자체 실패 (curl 연결 거부, docker exec 에러, 타임아웃) |
| **SKIP** | 필요한 변수가 선행 Scenario에서 미확보 (선행 FAIL/ERROR) |

**FAIL 기록 시 반드시 포함할 정보:**
1. 실패한 Step 원문
2. 실행한 실제 명령 (curl/docker exec 전체)
3. 기대 결과 (Then 문)
4. 실제 결과 (status code + response body 또는 stdout + exit code)

## 3. 변수 스코프

- Feature 내 모든 Scenario에서 공유
- Feature 간에는 공유하지 않음 (새 .feature 시작 시 초기화)
- `{변수명}` 형태로 Step 어디서든 치환 가능
- 미확보 변수 참조 시 해당 Scenario를 SKIP 처리

## 4. 관련 문서

| 문서 | 역할 |
|------|------|
| [gherkin-guide.md](gherkin-guide.md) | Step별 상세 변환 규칙 (API, CLI, 검증, 변수) |
| [report-format.md](report-format.md) | 리포트 출력 포맷 + 버그 이슈 템플릿 |
| [tests/tc/README.md](../../../tests/tc/README.md) | TC 작성 컨벤션 |
