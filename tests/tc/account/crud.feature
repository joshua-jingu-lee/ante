Feature: 계좌 CRUD
  Ante 시스템의 계좌 생성, 조회, 수정, 삭제를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  Scenario: 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value              |
      | account_id          | qa-test-account-01 |
      | name                | QA 테스트 계좌     |
      | exchange            | KRX                |
      | currency            | KRW                |
      | timezone            | Asia/Seoul         |
      | trading_hours_start | 09:00              |
      | trading_hours_end   | 15:30              |
      | trading_mode        | virtual            |
      | broker_type         | test               |
      | credentials         | {"app_key": "test", "app_secret": "test"} |
    Then 응답 상태는 201
    And 응답 body.account.account_id 는 null이 아니다
    And 응답 body.account.name 은 "QA 테스트 계좌"
    And 응답 body.account.status 는 "active"
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  Scenario: 생성된 계좌 조회 (API)
    When GET /api/accounts/{account_id}
    Then 응답 상태는 200
    And 응답 body.account.name 은 "QA 테스트 계좌"
    And 응답 body.account.exchange 은 "KRX"
    And 응답 body.account.currency 은 "KRW"
    And 응답 body.account.status 는 "active"

  Scenario: 계좌 목록 조회 (CLI)
    When 컨테이너에서 실행: ante account list --format json
    Then 종료 코드는 0
    And stdout JSON의 .accounts 배열 길이는 1 이상이다

  Scenario: 계좌 정보 조회 (CLI)
    When 컨테이너에서 실행: ante account info {account_id} --format json
    Then 종료 코드는 0
    And stdout에 {account_id} 가 포함되어 있다
    And stdout JSON의 .name 은 "QA 테스트 계좌"

  Scenario: 계좌 이름 수정 (API)
    When PUT /api/accounts/{account_id} 요청:
      | field | value          |
      | name  | 수정된 QA 계좌 |
    Then 응답 상태는 200
    And 응답 body.account.name 은 "수정된 QA 계좌"
    And 응답 body.account.status 는 "active"

  Scenario: 계좌 삭제 (CLI)
    When 컨테이너에서 실행: ante account delete {account_id} --yes
    Then 종료 코드는 0

  Scenario: 존재하지 않는 계좌 조회
    When GET /api/accounts/nonexistent-id-12345
    Then 응답 상태는 404

  Scenario: 필수 필드 누락 계좌 생성
    When POST /api/accounts 요청:
      | field | value  |
      | name  | 불완전 |
    Then 응답 상태는 422
