# QA 테스트 리포트 출력 포맷

QA 테스트 에이전트가 TC 실행 완료 후 출력하는 리포트의 포맷을 정의한다.

---

## 1. 리포트 구조

리포트는 다음 순서로 구성한다:

1. 요약 헤더
2. FAIL 상세 (있는 경우)
3. ERROR 상세 (있는 경우)
4. SKIP 상세 (있는 경우)
5. PASS 목록

---

## 2. 요약 헤더

```
## QA 테스트 리포트

- 실행 시각: 2026-03-20 14:30
- 대상: account (3 feature files)
- 결과: 18/22 PASS, 2 FAIL, 1 ERROR, 1 SKIP
```

| 필드 | 설명 |
|------|------|
| 실행 시각 | 테스트 시작 시각 (YYYY-MM-DD HH:MM) |
| 대상 | 실행한 카테고리 또는 Feature 파일명 |
| 결과 | 전체 Scenario 수 대비 각 상태 건수 |

---

## 3. FAIL 상세

FAIL은 검증 불일치가 발생한 경우다. 디버깅에 필요한 정보를 모두 포함한다.

```
### FAIL (2)

**[FAIL] account/crud.feature -- 존재하지 않는 계좌 조회**
- Step: `When GET /api/accounts/nonexistent-id-12345`
- 검증: `Then 응답 상태는 404`
- 기대: 404
- 실제: 500 -- {"detail": "Internal server error"}

**[FAIL] account/crud.feature -- 필수 필드 누락 계좌 생성**
- Step: `When POST /api/accounts 요청`
- 검증: `Then 응답 상태는 422`
- 기대: 422
- 실제: 500 -- {"detail": "Internal server error"}
```

### FAIL 항목 필수 필드

| 필드 | 설명 |
|------|------|
| Feature/Scenario | 파일 경로와 Scenario 제목 |
| Step | 실패가 발생한 When Step 원문 |
| 검증 | 실패한 Then/And Step 원문 |
| 기대 | 기대한 값 |
| 실제 | 실제로 받은 값 (응답 상태 코드 + 본문 요약) |

---

## 4. ERROR 상세

ERROR는 실행 자체가 실패한 경우다 (타임아웃, 연결 오류 등).

```
### ERROR (1)

**[ERROR] bot/lifecycle.feature -- 봇 시작 및 거래 확인**
- Step: `When POST /api/bots/{bot_id}/start`
- 오류: Connection refused -- http://localhost:8000 연결 불가
```

---

## 5. SKIP 상세

SKIP은 선행 Scenario 실패로 필요한 변수가 확보되지 않은 경우다.

```
### SKIP (1)

**[SKIP] account/crud.feature -- 생성된 계좌 조회 (API)**
- 사유: 변수 {account_id} 미확보 (선행 Scenario "계좌 생성 (API)" 실패)
```

---

## 6. PASS 목록

PASS는 간결하게 목록으로 출력한다.

```
### PASS (18)

- [PASS] account/crud.feature -- 계좌 생성 (API)
- [PASS] account/crud.feature -- 계좌 목록 조회 (CLI)
- [PASS] account/crud.feature -- 계좌 정보 조회 (CLI)
- [PASS] account/crud.feature -- 계좌 이름 수정 (API)
- [PASS] account/crud.feature -- 계좌 삭제 (CLI)
- [PASS] account/lifecycle.feature -- 계좌 정지 (API)
...
```

---

## 7. GitHub Issue 본문 템플릿

FAIL 항목에 대해 자동 생성하는 GitHub Issue의 본문 형식:

```markdown
## TC 정보
- Feature: tests/tc/account/crud.feature
- Scenario: 존재하지 않는 계좌 조회

## 실패 Step
When GET /api/accounts/nonexistent-id-12345

## 기대
응답 상태는 404

## 실제
응답 상태 500 -- {"detail": "Internal server error"}

## 재현 명령
curl -s -X GET http://localhost:8000/api/accounts/nonexistent-id-12345 \
  -H "Authorization: Bearer $TOKEN"
```

### Issue 제목 형식

```
QA: {Feature명} -- {Scenario명} 실패
```

예시: `QA: 계좌 CRUD -- 존재하지 않는 계좌 조회 실패`

### Issue 라벨

자동 생성 Issue에는 `bug` 라벨을 부여한다.

---

## 8. 복수 Feature 실행 시 리포트

`/qa-test all`처럼 여러 Feature를 실행하는 경우, Feature별로 섹션을 나누어 출력한다.

```
## QA 테스트 리포트

- 실행 시각: 2026-03-20 14:30
- 대상: all (8 feature files)
- 결과: 95/102 PASS, 5 FAIL, 1 ERROR, 1 SKIP

---

### account/ (3 files, 22 scenarios)
- 결과: 20/22 PASS, 2 FAIL

### bot/ (3 files, 20 scenarios)
- 결과: 18/20 PASS, 1 FAIL, 1 ERROR

### treasury/ (2 files, 10 scenarios)
- 결과: 10/10 PASS

...

---

### FAIL (5)
(FAIL 상세 항목들)

### ERROR (1)
(ERROR 상세 항목들)

### SKIP (1)
(SKIP 상세 항목들)

### PASS (95)
(PASS 목록)
```

Feature 별 요약을 먼저 보여준 뒤, 전체 FAIL/ERROR/SKIP/PASS 상세를 아래에 출력한다.
