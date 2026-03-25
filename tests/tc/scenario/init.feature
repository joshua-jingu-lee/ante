Feature: 최초 설치 및 초기화
  QA 컨테이너 기동 후 시스템이 올바르게 초기화되었는지 검증한다.
  전수 검사 시 가장 먼저 실행되어야 하며, 다른 모든 TC의 전제 조건을 보장한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다

  # ── 시스템 헬스체크 ──────────────────────────────────

  Scenario: 1. 시스템 헬스체크
    When GET /api/system/health
    Then 응답 상태는 200
    And 응답 body.ok 은 true

  Scenario: 2. 시스템 상태 확인
    When GET /api/system/status
    Then 응답 상태는 200
    And 응답 body.status 는 null이 아니다
    And 응답 body.version 은 null이 아니다

  # ── Master 계정 ──────────────────────────────────────

  Scenario: 3. QA Admin 멤버 존재 확인
    When GET /api/members
    Then 응답 상태는 200
    And 응답 body.members 배열 길이는 1 이상이다

  Scenario: 4. QA Admin 로그인
    When POST /api/auth/login 요청:
      | field     | value        |
      | member_id | qa-admin     |
      | password  | qa-password  |
    Then 응답 상태는 200
    And 응답 body.member_id 는 "qa-admin"

  # ── 시드 계좌 ────────────────────────────────────────

  Scenario: 5. 시드 계좌 존재 확인
    When GET /api/accounts
    Then 응답 상태는 200
    And 응답 body.accounts 배열 길이는 1 이상이다

  Scenario: 6. test 계좌 상세 확인
    When GET /api/accounts/test
    Then 응답 상태는 200
    And 응답 body.account.account_id 는 "test"
    And 응답 body.account.broker_type 는 "test"
    And 응답 body.account.exchange 는 "TEST"
    And 응답 body.account.status 는 "active"

  # ── Treasury 초기화 ──────────────────────────────────

  Scenario: 7. Treasury 모듈 정상 응답
    When GET /api/treasury?account_id=test
    Then 응답 상태는 200

  # ── 동적 설정 시드 ───────────────────────────────────

  Scenario: 8. 동적 설정 시드 확인
    When GET /api/config
    Then 응답 상태는 200

  # ── 전략 레지스트리 ──────────────────────────────────

  Scenario: 9. QA 전략 등록 확인
    When GET /api/strategies
    Then 응답 상태는 200
    And 응답 body.strategies 배열 길이는 1 이상이다
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다

  Scenario: 10. QA 전략 상세 확인
    When GET /api/strategies/{strategy_id}
    Then 응답 상태는 200
    And 응답 body.status 는 null이 아니다

  # ── CLI 동작 확인 ────────────────────────────────────

  Scenario: 11. CLI 시스템 상태 확인
    When 컨테이너에서 실행: ante system status --format json
    Then 종료 코드는 0
    And stdout JSON의 .trading_state 는 null이 아니다

  Scenario: 12. CLI 계좌 목록 확인
    When 컨테이너에서 실행: ante account list --format json
    Then 종료 코드는 0
    And stdout JSON의 .accounts 배열 길이는 1 이상이다
