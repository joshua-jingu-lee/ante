# Gherkin TC 컨벤션 가이드

Ante QA 테스트 케이스(TC) 작성을 위한 Gherkin 컨벤션 가이드.
사람과 AI 에이전트 모두 이 문서를 기준으로 `.feature` 파일을 작성한다.

---

## 1. 디렉토리 구조

모듈별로 디렉토리를 나누고, 기능 단위로 `.feature` 파일을 배치한다.

```
tests/tc/
├── README.md                     # 본 문서 (TC 작성 가이드)
├── account/
│   ├── crud.feature              # 계좌 CRUD
│   ├── lifecycle.feature         # 생성 → 정지 → 활성화 → 삭제
│   └── credentials.feature       # 인증정보 관리
├── bot/
│   ├── crud.feature
│   ├── lifecycle.feature         # 생성 → 시작 → 정지 → 삭제
│   └── budget.feature            # 자금 할당/회수
├── treasury/
│   ├── balance.feature
│   └── allocation.feature
├── strategy/
│   ├── validate-submit.feature
│   └── registry.feature
├── member/
│   ├── auth.feature              # 로그인/로그아웃
│   └── management.feature        # 등록/정지/권한
├── config/
│   └── dynamic.feature           # 동적 설정 CRUD
├── trade/
│   └── query.feature             # 거래 조회
└── scenario/
    ├── install.feature           # 대화형 설치 프로세스 (ante init, 별도 컨테이너)
    ├── init.feature              # 설치 후 초기화 상태 검증 (전수 검사 시 최우선)
    ├── full-pipeline.feature     # 계좌→전략→봇→거래→성과
    └── multi-account.feature     # 복수 계좌 독립성
```

### 배치 규칙

- **모듈 디렉토리**: `src/ante/` 하위 모듈명과 일치시킨다 (account, bot, treasury 등).
- **Feature 파일**: 기능 단위로 분리한다 (crud, lifecycle, auth 등).
- **API + CLI 공존**: 하나의 `.feature` 파일 안에 API Scenario와 CLI Scenario를 함께 배치한다. 별도 디렉토리로 분리하지 않는다.
- **시나리오 디렉토리**: `scenario/`에는 모듈 횡단 복합 흐름을 배치한다.

---

## 2. QA 환경 기본값

TC 작성 및 실행 시, 아래 기본값을 사용한다.

### 브로커 인증정보

QA 환경의 `test` 브로커는 더미 인증정보를 사용한다. 크레덴셜이 필요한 TC에서는 아래 값을 입력한다.

| 필드 | 값 |
|------|-----|
| `app_key` | `test` |
| `app_secret` | `test` |

test 브로커는 GBM(기하 브라운 운동) 기반 가격 시뮬레이션으로 가상 캔들/시세를 반환한다.
슬리피지, 부분 체결, 인메모리 잔고/포지션 관리를 지원한다.

- 구현: [`src/ante/broker/test.py`](../../src/ante/broker/test.py) — `TestBrokerAdapter`, `PriceSimulator`
- 스펙: [`docs/specs/broker-adapter.md`](../../docs/specs/broker-adapter.md)
- 가상 종목 6종 (`000001`~`000006`) 프리셋 내장, seed 고정(42)으로 재현 가능

```gherkin
# 예시: 인증정보 설정
When POST /api/accounts/{account_id}/credentials 요청:
  | field      | value |
  | app_key    | test  |
  | app_secret | test  |
```

### QA 전략 파일

`strategies/` 디렉토리에 QA 전용 더미 전략이 배치되어 있다. TC 목적에 맞는 전략을 선택하여 사용한다.

| 전략 이름 | 파일 | 용도 | exchange |
|-----------|------|------|----------|
| `qa_sample` | `qa_sample.py` | 기본 검증 (시그널 없음) | KRX |
| `qa_buy_signal` | `qa_buy_signal.py` | 매수 시그널 발생 → 거래 TC | KRX |
| `qa_multi_symbol` | `qa_multi_symbol.py` | 다중 종목 → 포트폴리오 TC | KRX |
| `qa_invalid_meta` | `qa_invalid_meta.py` | 메타 검증 실패 → validate 에러 TC | (누락) |
| `qa_nyse` | `qa_nyse.py` | 해외 시장 호환성 TC | NYSE |
| `qa_external_signal` | `qa_external_signal.py` | 외부 시그널 수신 → 에이전트 매매 TC | KRX |

- **봇 생성 TC**: `qa_sample` 또는 `qa_buy_signal` 사용
- **전략 검증 에러 TC**: `qa_invalid_meta` 사용
- **교차 시장 TC**: `qa_nyse` 사용
- **외부 시그널 TC**: `qa_external_signal` 사용 (`accepts_external_signals=True`)

> 전략 파일은 QA 시드 리셋 시 레지스트리에 자동 등록된다 (GitHub #650 참조).

---

## 3. Step 키워드 컨벤션

### 2.1 API 호출

HTTP 메서드와 경로를 Step에 직접 기술한다.

```gherkin
# 요청 본문이 있는 경우 — 콜론(:)으로 끝내고 Data Table 첨부
When POST /api/accounts 요청:
  | field    | value          |
  | name     | QA 테스트 계좌 |
  | exchange | KRX            |

# 요청 본문이 없는 경우
When GET /api/accounts/{account_id}

# PUT (부분 수정)
When PUT /api/accounts/{account_id} 요청:
  | field | value      |
  | name  | 수정된 계좌 |

# DELETE
When DELETE /api/accounts/{account_id}
```

### 2.2 CLI 실행

`컨테이너에서 실행:` 접두어 뒤에 CLI 커맨드를 기술한다.

```gherkin
When 컨테이너에서 실행: ante account list --format json
When 컨테이너에서 실행: ante bot info {bot_id} --format json
When 컨테이너에서 실행: ante account delete {account_id} --yes
```

### 2.3 응답 검증

```gherkin
# HTTP 상태 코드
Then 응답 상태는 201

# 정확한 값 비교
And 응답 body.name 은 "QA 테스트 계좌"
And 응답 body.status 는 "active"

# null 아님
And 응답 body.account_id 는 null이 아니다

# 숫자 비교
And 응답 body.count 는 0보다 크다

# 배열 길이
And 응답 body 배열 길이는 1 이상이다

# 복합 조건 (OR)
Then 응답 상태는 404 또는 응답 body.status 는 "deleted"
```

### 2.4 변수 저장

응답값을 변수에 저장하여 후속 Scenario에서 참조한다.

```gherkin
# API 응답에서 저장
And 응답 body.account_id 를 {account_id}로 저장한다
And 첫 번째 항목의 strategy_id 를 {strategy_id}로 저장한다
```

### 2.5 CLI 검증

```gherkin
# 종료 코드
Then 종료 코드는 0

# stdout 내용 포함 여부
And stdout에 {account_id} 가 포함되어 있다

# stdout JSON 파싱 후 값 검증
And stdout JSON의 .status 는 "active"
And stdout JSON의 .name 은 "QA 테스트 계좌"

# stdout JSON 배열 길이
And stdout JSON 배열 길이는 1 이상이다
```

### 2.6 대기

봇 실행 등 비동기 동작이 필요한 경우 명시적으로 대기한다.

```gherkin
And 3초 대기
```

---

## 4. Data Table 사용법

API 요청 본문은 Data Table로 표현한다. `field | value` 2열 구조를 사용한다.

```gherkin
When POST /api/accounts 요청:
  | field               | value          |
  | name                | QA 테스트 계좌 |
  | exchange            | KRX            |
  | currency            | KRW            |
  | timezone            | Asia/Seoul     |
  | trading_hours_start | 09:00          |
  | trading_hours_end   | 15:30          |
  | trading_mode        | virtual        |
  | broker_type         | test           |
```

QA 에이전트는 Data Table을 JSON 객체로 변환하여 요청 본문에 사용한다:

```json
{
  "name": "QA 테스트 계좌",
  "exchange": "KRX",
  "currency": "KRW",
  "timezone": "Asia/Seoul",
  "trading_hours_start": "09:00",
  "trading_hours_end": "15:30",
  "trading_mode": "virtual",
  "broker_type": "test"
}
```

### 주의사항

- 숫자 값은 문자열 따옴표 없이 적는다: `| balance | 10000000 |`
- 변수 참조는 중괄호로 감싼다: `| account_id | {account_id} |`
- Data Table이 있는 When Step은 반드시 콜론(`:`)으로 끝낸다.

---

## 5. 변수 스코프

### Feature 내 공유

하나의 Feature 파일 안에서 Scenario는 위에서 아래로 순서대로 실행되며, 변수를 공유한다.

```gherkin
Feature: 계좌 CRUD

  Scenario: 계좌 생성
    When POST /api/accounts 요청:
      | field | value     |
      | name  | 테스트    |
    Then 응답 상태는 201
    And 응답 body.account_id 를 {account_id}로 저장한다

  Scenario: 생성된 계좌 조회
    # 위 Scenario에서 저장한 {account_id}를 사용
    When GET /api/accounts/{account_id}
    Then 응답 상태는 200
```

### Feature 간 독립

서로 다른 `.feature` 파일 간에는 변수를 공유하지 않는다.
`account/crud.feature`에서 저장한 `{account_id}`는 `bot/crud.feature`에서 사용할 수 없다.

### 변수 미확보 시

선행 Scenario가 실패하여 변수가 저장되지 않은 경우, 해당 변수를 참조하는 후속 Scenario는 `SKIP` 처리된다.

---

## 6. Background 활용

Feature 내 모든 Scenario에 공통으로 적용되는 전제조건은 `Background`에 기술한다.

```gherkin
Feature: 계좌 CRUD

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  Scenario: 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field | value     |
      | name  | 테스트    |
    Then 응답 상태는 201
```

### Background 작성 규칙

- **인증**: 인증이 필요한 Feature에는 반드시 `And QA Admin 인증 토큰이 확보되어 있다`를 포함한다.
- **컨테이너**: `Given ante-qa 컨테이너가 실행 중이다`로 Docker 컨테이너 상태를 보장한다.
- **간결하게**: Background에는 공통 전제조건만 넣는다. Scenario 고유의 설정은 Scenario 안에 기술한다.

---

## 7. 네이밍 규칙

### 파일명

- 소문자 kebab-case: `crud.feature`, `validate-submit.feature`, `full-pipeline.feature`
- 확장자는 반드시 `.feature`

### Feature 제목

- 한국어로 기능 영역을 명시한다.
- 선택적으로 보충 설명을 줄바꿈하여 추가한다.

```gherkin
Feature: 계좌 CRUD
  Ante 시스템의 계좌 생성, 조회, 수정, 삭제를 검증한다.
```

### Scenario 제목

- `동작 + (채널)` 형식으로 작성한다.
- 채널(API/CLI)을 괄호로 구분하여 명시한다.
- 에러 케이스는 기대 상황을 제목에 포함한다.

```gherkin
Scenario: 계좌 생성 (API)
Scenario: 계좌 목록 조회 (CLI)
Scenario: 존재하지 않는 계좌 조회
Scenario: 필수 필드 누락 계좌 생성
```

---

## 8. 에러 케이스 작성법

기대하는 에러 상태 코드별로 Scenario를 작성한다.

### 404 Not Found

존재하지 않는 리소스 접근:

```gherkin
Scenario: 존재하지 않는 계좌 조회
  When GET /api/accounts/nonexistent-id-12345
  Then 응답 상태는 404
```

### 422 Unprocessable Entity

필수 필드 누락 또는 유효성 검증 실패:

```gherkin
Scenario: 필수 필드 누락 계좌 생성
  When POST /api/accounts 요청:
    | field | value  |
    | name  | 불완전 |
  Then 응답 상태는 422
```

### 409 Conflict

중복 리소스 생성 또는 상태 충돌:

```gherkin
Scenario: 이미 정지된 계좌 재정지
  # 사전 조건: {account_id}가 이미 suspended 상태
  When POST /api/accounts/{account_id}/suspend
  Then 응답 상태는 409
```

### 에러 케이스 작성 원칙

- 에러 Scenario는 정상 흐름 Scenario 뒤에 배치한다.
- Scenario 제목에 기대하는 에러 상황을 명시한다.
- 응답 상태 코드만 검증해도 충분하지만, 에러 메시지가 중요한 경우 body도 검증한다:

```gherkin
Scenario: 필수 필드 누락 계좌 생성
  When POST /api/accounts 요청:
    | field | value  |
    | name  | 불완전 |
  Then 응답 상태는 422
  And 응답 body.detail 에 "exchange" 가 포함되어 있다
```
