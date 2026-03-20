Feature: 봇 자금 관리
  봇에 대한 자금 할당(allocate) 및 회수(deallocate)를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: 계좌 + 잔고 + 봇 ──

  Scenario: 자금 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-bot-budget-acct   |
      | name                | 봇 자금 테스트 계좌  |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | mock                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  Scenario: 자금 테스트용 잔고 설정 (API)
    When POST /api/treasury/balance 요청:
      | field   | value    |
      | balance | 10000000 |
    Then 응답 상태는 200
    And 응답 body.total_balance 는 0보다 크다

  Scenario: 자금 테스트용 전략 확인 (API)
    When GET /api/strategies
    Then 응답 상태는 200
    And 첫 번째 항목의 strategy_id 를 {strategy_id}로 저장한다

  Scenario: 자금 테스트용 봇 생성 (API)
    When POST /api/bots 요청:
      | field            | value              |
      | bot_id           | qa-bot-budget-01   |
      | strategy_id      | {strategy_id}      |
      | name             | 자금 테스트 봇     |
      | account_id       | {account_id}       |
      | interval_seconds | 60                 |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  # ── 정상 흐름: 할당 → 회수 ──

  Scenario: 봇에 자금 할당 (API)
    When POST /api/treasury/bots/{bot_id}/allocate 요청:
      | field  | value   |
      | amount | 1000000 |
    Then 응답 상태는 200
    And 응답 body.bot_id 는 "{bot_id}"
    And 응답 body.allocated 는 0보다 크다

  Scenario: 자금 회수 (API)
    When POST /api/treasury/bots/{bot_id}/deallocate 요청:
      | field  | value  |
      | amount | 500000 |
    Then 응답 상태는 200
    And 응답 body.bot_id 는 "{bot_id}"
    And 응답 body.allocated 는 0보다 크다

  # ── 에러 케이스 ──

  Scenario: 할당 초과 시 에러 (API)
    When POST /api/treasury/bots/{bot_id}/allocate 요청:
      | field  | value         |
      | amount | 999999999999  |
    Then 응답 상태는 400

  Scenario: 실행 중 봇 자금 회수 거부 (API)
    # 봇 시작
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200
    And 3초 대기
    # 실행 중 자금 회수 시도 → 거부
    When POST /api/treasury/bots/{bot_id}/deallocate 요청:
      | field  | value  |
      | amount | 100000 |
    Then 응답 상태는 409
    # 정리: 봇 정지
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200

  Scenario: 가용 예산 초과 회수 시 에러 (API)
    When POST /api/treasury/bots/{bot_id}/deallocate 요청:
      | field  | value         |
      | amount | 999999999999  |
    Then 응답 상태는 400
