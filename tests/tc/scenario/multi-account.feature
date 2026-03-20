Feature: 복수 계좌 독립성
  복수 계좌 간 봇·Treasury가 서로 독립적으로 동작하는지 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 1. 계좌 A, B 각각 생성 ──

  Scenario: 계좌 A 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-multi-account-a   |
      | name                | 멀티 계좌 A          |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | mock                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id_a}로 저장한다

  Scenario: 계좌 B 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-multi-account-b   |
      | name                | 멀티 계좌 B          |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | mock                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id_b}로 저장한다

  # ── 2. 각 계좌에 독립 봇 배치 ──

  Scenario: 전략 ID 확보
    When GET /api/strategies
    Then 응답 상태는 200
    And 응답 body.strategies 배열 길이는 1 이상이다
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다

  Scenario: 계좌 A 봇 생성 (API)
    When POST /api/bots 요청:
      | field       | value            |
      | account_id  | {account_id_a}   |
      | name        | 멀티 봇 A        |
      | strategy_id | {strategy_id}    |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id_a}로 저장한다

  Scenario: 계좌 B 봇 생성 (API)
    When POST /api/bots 요청:
      | field       | value            |
      | account_id  | {account_id_b}   |
      | name        | 멀티 봇 B        |
      | strategy_id | {strategy_id}    |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id_b}로 저장한다

  Scenario: 봇 A, B 각각 시작 (API)
    When POST /api/bots/{bot_id_a}/start
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "running"
    When POST /api/bots/{bot_id_b}/start
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "running"

  # ── 3. 계좌 A 정지 시 계좌 B 봇 영향 없음 ──

  Scenario: 계좌 A 정지 시 계좌 B 봇 영향 없음 (API)
    When POST /api/accounts/{account_id_a}/suspend
    Then 응답 상태는 200
    When GET /api/bots/{bot_id_b}
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "running"

  # ── 4. 각 계좌 Treasury 독립 확인 ──

  Scenario: 각 계좌 Treasury 독립 확인 (API)
    When POST /api/treasury/balance 요청:
      | field      | value            |
      | account_id | {account_id_a}   |
      | balance    | 5000000          |
    Then 응답 상태는 200
    When POST /api/treasury/balance 요청:
      | field      | value            |
      | account_id | {account_id_b}   |
      | balance    | 8000000          |
    Then 응답 상태는 200
    When GET /api/treasury?account_id={account_id_a}
    Then 응답 상태는 200
    And 응답 body.account_balance 는 5000000
    When GET /api/treasury?account_id={account_id_b}
    Then 응답 상태는 200
    And 응답 body.account_balance 는 8000000
