Feature: Treasury 잔고 관리
  Treasury 잔고 조회, 수동 설정, 설정 후 반영을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: 테스트용 계좌 생성 ──

  Scenario: 잔고 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-treasury-bal-01   |
      | name                | 잔고 테스트 계좌     |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | test                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  # ── 정상 흐름: 잔고 조회 및 설정 ──

  Scenario: Treasury 현황 조회 (API)
    When GET /api/treasury
    Then 응답 상태는 200
    And 응답 body.account_balance 는 null이 아니다
    And 응답 body.unallocated 는 null이 아니다
    And 응답 body.total_allocated 는 null이 아니다

  Scenario: Treasury 현황 조회 (CLI)
    When 컨테이너에서 실행: ante treasury status --format json
    Then 종료 코드는 0
    And stdout JSON의 .account_balance 는 null이 아니다
    And stdout JSON의 .unallocated 는 null이 아니다

  Scenario: 잔고 수동 설정 (API)
    When POST /api/treasury/balance 요청:
      | field   | value    |
      | balance | 10000000 |
    Then 응답 상태는 200
    And 응답 body.total_balance 는 10000000

  Scenario: 설정 후 잔고 반영 확인 (API)
    When GET /api/treasury
    Then 응답 상태는 200
    And 응답 body.account_balance 는 10000000
