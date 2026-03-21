Feature: Treasury 예산 할당·회수
  봇 예산 할당, 회수, 예산 목록 조회, 거래 내역 조회, 잔고 초과 에러를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: 계좌 + 잔고 + 전략 확보 + 봇 생성 ──

  Scenario: 할당 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                  |
      | account_id          | qa-treasury-alloc-01   |
      | name                | 할당 테스트 계좌       |
      | exchange            | KRX                    |
      | currency            | KRW                    |
      | timezone            | Asia/Seoul             |
      | trading_hours_start | 09:00                  |
      | trading_hours_end   | 15:30                  |
      | trading_mode        | virtual                |
      | broker_type         | test                   |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  Scenario: 잔고 설정 (API)
    When POST /api/treasury/balance 요청:
      | field   | value    |
      | balance | 10000000 |
    Then 응답 상태는 200
    And 응답 body.total_balance 는 10000000

  Scenario: QA 전략 확보
    When GET /api/strategies
    Then 응답 상태는 200
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다

  Scenario: 할당 테스트용 봇 생성 (API)
    When POST /api/bots 요청:
      | field       | value                |
      | bot_id      | qa-alloc-bot-01      |
      | account_id  | {account_id}         |
      | strategy_id | {strategy_id}        |
      | name        | 할당 테스트 봇       |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  # ── 정상 흐름: 예산 할당 ──

  Scenario: 봇 예산 할당 (API)
    When POST /api/treasury/bots/{bot_id}/allocate 요청:
      | field  | value   |
      | amount | 3000000 |
    Then 응답 상태는 200
    And 응답 body.bot_id 는 null이 아니다
    And 응답 body.allocated 는 3000000

  Scenario: 전체 예산 목록 조회 (API)
    When GET /api/treasury/budgets
    Then 응답 상태는 200
    And 응답 body.budgets 배열 길이는 1 이상이다

  # ── 정상 흐름: 예산 회수 ──

  Scenario: 봇 예산 회수 (API)
    When POST /api/treasury/bots/{bot_id}/deallocate 요청:
      | field  | value   |
      | amount | 1000000 |
    Then 응답 상태는 200
    And 응답 body.allocated 는 2000000

  Scenario: Treasury 거래 내역 조회 (API)
    When GET /api/treasury/transactions
    Then 응답 상태는 200
    And 응답 body.items 배열 길이는 1 이상이다
    And 응답 body.total 는 0보다 크다

  # ── 에러 케이스 ──

  Scenario: 잔고 초과 할당 시 에러
    When POST /api/treasury/bots/{bot_id}/allocate 요청:
      | field  | value      |
      | amount | 9999999999 |
    Then 응답 상태는 400

  Scenario: 가용 예산 초과 회수 시 에러
    When POST /api/treasury/bots/{bot_id}/deallocate 요청:
      | field  | value      |
      | amount | 9999999999 |
    Then 응답 상태는 400

  Scenario: 존재하지 않는 봇 예산 할당 시 에러
    When POST /api/treasury/bots/nonexistent-bot-99999/allocate 요청:
      | field  | value  |
      | amount | 100000 |
    Then 응답 상태는 404 또는 응답 상태는 400
