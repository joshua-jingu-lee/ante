# Gherkin Step 해석 가이드

QA 테스트 에이전트가 `.feature` 파일의 Step을 실제 명령으로 변환하는 규칙을 정의한다.

TC 작성 컨벤션은 [tests/tc/README.md](../../../tests/tc/README.md)를 참조한다.

---

## 1. API Step 변환 규칙

### HTTP 요청 실행

`When {METHOD} /api/{path}` 패턴의 Step은 curl 명령으로 변환한다.

```gherkin
When POST /api/accounts 요청:
  | field    | value          |
  | name     | QA 테스트 계좌 |
  | exchange | KRX            |
```

변환 결과:

```bash
curl -s -w '\n%{http_code}' -X POST http://localhost:8000/api/accounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "QA 테스트 계좌", "exchange": "KRX"}'
```

### curl 옵션 규칙

| 옵션 | 용도 |
|------|------|
| `-s` | 진행률 출력 억제 |
| `-w '\n%{http_code}'` | 응답 본문 뒤에 HTTP 상태 코드 출력 |
| `-X {METHOD}` | HTTP 메서드 지정 |
| `-H "Authorization: Bearer $TOKEN"` | 인증 헤더 (Background에서 확보한 토큰) |
| `-H "Content-Type: application/json"` | JSON 요청 본문이 있는 경우 |
| `-d '{...}'` | JSON 요청 본문 |

### Data Table에서 JSON 변환

Data Table의 `field | value` 행을 JSON 객체로 변환한다.

**타입 추론 규칙:**

| value 형태 | JSON 타입 | 예시 |
|-----------|-----------|------|
| 정수 패턴 (`^\d+$`) | number | `10000000` -> `10000000` |
| 소수점 패턴 (`^\d+\.\d+$`) | number | `0.05` -> `0.05` |
| `true` / `false` | boolean | `true` -> `true` |
| `null` | null | `null` -> `null` |
| `{변수명}` | 변수 치환 후 원래 타입 유지 | `{account_id}` -> 저장된 값 |
| 그 외 | string | `"QA 테스트 계좌"` |

### `(실패 무시)` 접미사

`(실패 무시)` 접미사가 붙은 API Step은 HTTP 오류 응답(4xx, 5xx)을 받아도 PASS로 처리한다.
주로 Background의 데이터 정리에 사용되며, `docs/runbooks/05-testing.md` 7.5에 정의된 패턴이다.

```gherkin
# setup — 이전 실행 잔존 데이터 정리 (실패 무시)
And DELETE /api/members/qa-test-agent-01 요청 (실패 무시)
And DELETE /api/accounts/qa-test-acct-01 요청 (실패 무시)
```

실행 로직:
1. 일반 API Step과 동일하게 curl 요청을 실행한다.
2. HTTP 상태 코드와 무관하게 (2xx, 4xx, 5xx 모두) PASS로 처리한다.
3. 응답 내용은 로그에 기록하되, 판정에는 영향을 주지 않는다.

### 요청 본문 없는 요청

Step이 콜론(`:`)으로 끝나지 않으면 요청 본문이 없는 요청이다.

```gherkin
When GET /api/accounts/{account_id}
When DELETE /api/accounts/{account_id}
```

변환 결과:

```bash
curl -s -w '\n%{http_code}' -X GET http://localhost:8000/api/accounts/abc-123 \
  -H "Authorization: Bearer $TOKEN"
```

---

## 2. CLI Step 변환 규칙

`When 컨테이너에서 실행: {명령}` 패턴의 Step은 docker exec로 변환한다.

```gherkin
When 컨테이너에서 실행: ante account list --format json
```

변환 결과:

```bash
docker exec ante-qa ante account list --format json
```

### 별도 컨테이너 실행 (일회용)

`When 별도 컨테이너에서 실행: {명령}` 패턴의 Step은 `docker run`으로 변환한다.
기존 QA 컨테이너(ante-qa)와 독립된 일회용 컨테이너에서 실행되며, 종료 후 자동 삭제된다.
주로 `ante init` 등 깨끗한 환경이 필요한 설치 프로세스 검증에 사용한다.

```gherkin
When 별도 컨테이너에서 실행: printf 'input\n' | ante init --dir /tmp/test
```

변환 결과:

```bash
docker run -i --rm \
  -e ANTE_DB_ENCRYPTION_KEY="$ANTE_DB_ENCRYPTION_KEY" \
  ante-qa sh -c "printf 'input\n' | ante init --dir /tmp/test"
```

**환경변수 전달:** 별도 컨테이너는 QA 컨테이너의 환경변수를 상속하지 않는다.
`ANTE_DB_ENCRYPTION_KEY` 등 시스템 필수 환경변수를 `-e` 옵션으로 명시적으로 전달해야 한다.
`docker-compose.qa.yml`에 정의된 환경변수 값을 참조한다.

**주의:** 각 Scenario마다 새 컨테이너가 생성되는 것이 아니라, Feature 내에서 동일 컨테이너를 유지해야 하는 경우 `docker run -d` + `docker exec` + `docker rm` 패턴을 사용한다.
단, install.feature처럼 각 시나리오가 독립적인 경우는 매번 `docker run --rm`으로 충분하다.

### 실행 결과 캡처

CLI 실행 결과에서 다음을 캡처한다:

| 항목 | 용도 |
|------|------|
| stdout | 표준 출력 (JSON 파싱 또는 텍스트 검색 대상) |
| stderr | 에러 메시지 (ERROR 판정 시 참조) |
| exit code | `Then 종료 코드는 {N}` 검증 대상 |

---

## 3. 변수 치환 규칙

### 변수 저장

`{변수명}으로 저장한다` 패턴의 Step에서 응답값을 변수에 저장한다.

```gherkin
And 응답 body.account_id 를 {account_id}로 저장한다
```

실행 로직:
1. 직전 API 응답 JSON에서 `account_id` 필드 값을 추출한다.
2. 변수 저장소에 `account_id = "추출된 값"` 형태로 저장한다.

```gherkin
And 첫 번째 항목의 strategy_id 를 {strategy_id}로 저장한다
```

실행 로직:
1. 직전 API 응답이 배열이면 첫 번째 요소(`[0]`)에서 `strategy_id`를 추출한다.

### 조건부 변수 저장

`{필드명}이 "{값}"인 항목의 {다른필드} 를 {변수명}로 저장한다` 패턴의 Step에서 조건에 맞는 항목의 값을 변수에 저장한다.

```gherkin
And name이 "qa_buy_signal"인 항목의 id 를 {strategy_id}로 저장한다
```

실행 로직:
1. 직전 API 응답이 배열이면, 각 요소에서 `name` 필드가 `"qa_buy_signal"`과 일치하는 첫 번째 항목을 찾는다.
2. 해당 항목에서 `id` 필드 값을 추출한다.
3. 변수 저장소에 `strategy_id = "추출된 값"` 형태로 저장한다.
4. 조건에 맞는 항목이 없으면 해당 Scenario를 SKIP 처리한다.

### 변수 참조

`{변수명}` 패턴이 Step 텍스트나 Data Table value에 나타나면 저장된 값으로 치환한다.

```gherkin
When GET /api/accounts/{account_id}
```

`{account_id}`가 `"abc-123"`으로 저장되어 있으면:

```
When GET /api/accounts/abc-123
```

### 미확보 변수 처리

변수가 저장되어 있지 않은 경우 해당 Scenario를 SKIP 처리한다.
SKIP 사유를 리포트에 명시한다: `SKIP: 변수 {변수명} 미확보 (선행 Scenario 실패)`

---

## 4. 검증 Step 변환 규칙

### HTTP 상태 코드 검증

```gherkin
Then 응답 상태는 201
```

curl 출력의 마지막 줄(http_code)을 파싱하여 기대값과 비교한다.

### 복합 조건 (OR)

```gherkin
Then 응답 상태는 404 또는 응답 body.status 는 "deleted"
```

`또는`으로 분리된 두 조건 중 하나라도 참이면 PASS.

### JSON body 값 검증

```gherkin
And 응답 body.name 은 "QA 테스트 계좌"
And 응답 body.status 는 "active"
```

JSON 응답에서 dot-path로 값을 추출하여 기대값과 비교한다.

### null 검증

```gherkin
And 응답 body.account_id 는 null이 아니다
```

해당 필드가 존재하고 null이 아닌지 검증한다.

### 숫자 비교

```gherkin
And 응답 body.count 는 0보다 크다
```

숫자 값을 추출하여 비교 연산을 수행한다.

### 배열 길이 검증

```gherkin
And 응답 body 배열 길이는 1 이상이다
```

응답이 배열일 때 길이를 검증한다.

### 포함 여부

```gherkin
And 응답 body.detail 에 "exchange" 가 포함되어 있다
And stdout에 {account_id} 가 포함되어 있다
```

문자열 포함 여부를 검증한다.

### CLI 종료 코드

```gherkin
Then 종료 코드는 0
```

docker exec의 종료 코드를 검증한다.

### CLI stdout JSON 검증

```gherkin
And stdout JSON의 .status 는 "active"
And stdout JSON 배열 길이는 1 이상이다
```

stdout을 JSON으로 파싱한 후 값을 검증한다.

---

## 5. Background 처리

Background 블록의 Step은 각 Scenario 실행 전에 실행/검증한다.

```gherkin
Background:
  Given ante-qa 컨테이너가 실행 중이다
  And QA Admin 인증 토큰이 확보되어 있다
```

| Step | 실행 로직 |
|------|----------|
| `Given ante-qa 컨테이너가 실행 중이다` | `docker ps --filter name=ante-qa` 확인. 없으면 `docker compose -f docker-compose.qa.yml up -d --wait` |
| `And QA Admin 인증 토큰이 확보되어 있다` | 토큰이 없으면 로그인 API 호출하여 확보 |

Background 검증 실패 시 해당 Feature 전체를 ERROR 처리한다.

---

## 6. 대기 Step

```gherkin
And 3초 대기
```

`sleep 3`을 실행한다. 봇 실행 사이클 대기 등 비동기 작업에 사용한다.
