Feature: 전체 파이프라인
  계좌 생성 → 전략 확인 → 잔고 설정 → 봇 생성 → 자금 할당 → 봇 시작 → 거래 발생 → 봇 정지 → 거래 조회 → 성과 확인까지의 전체 흐름을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 1. 계좌 생성 ──

  Scenario: 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                  |
      | account_id          | qa-pipeline-account-01 |
      | name                | 파이프라인 테스트 계좌 |
      | exchange            | KRX                    |
      | currency            | KRW                    |
      | timezone            | Asia/Seoul             |
      | trading_hours_start | 09:00                  |
      | trading_hours_end   | 15:30                  |
      | trading_mode        | virtual                |
      | broker_type         | mock                   |
    Then 응답 상태는 201
    And 응답 body.account.account_id 는 null이 아니다
    And 응답 body.account.status 는 "active"
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  # ── 2. 전략 조회 ──

  Scenario: 전략 조회 (API)
    When GET /api/strategies
    Then 응답 상태는 200
    And 응답 body.strategies 배열 길이는 1 이상이다
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다

  Scenario: 전략 조회 (CLI)
    When 컨테이너에서 실행: ante strategy list --format json
    Then 종료 코드는 0
    And stdout JSON 배열 길이는 1 이상이다

  # ── 3. Treasury 잔고 설정 ──

  Scenario: Treasury 잔고 설정 (API)
    When POST /api/treasury/balance 요청:
      | field   | value    |
      | balance | 10000000 |
    Then 응답 상태는 200
    And 응답 body.total_balance 는 10000000

  Scenario: 잔고 반영 확인 (CLI)
    When 컨테이너에서 실행: ante treasury status --format json
    Then 종료 코드는 0
    And stdout JSON의 .account_balance 는 10000000

  # ── 4. 봇 생성 및 자금 할당 ──

  Scenario: 봇 생성 (API)
    When POST /api/bots 요청:
      | field       | value                |
      | account_id  | {account_id}         |
      | name        | 파이프라인 테스트 봇 |
      | strategy_id | {strategy_id}        |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 는 null이 아니다
    And 응답 body.bot.status 는 "stopped"
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  Scenario: 봇 자금 할당 (API)
    When POST /api/treasury/bots/{bot_id}/allocate 요청:
      | field  | value   |
      | amount | 5000000 |
    Then 응답 상태는 200
    And 응답 body.allocated 는 5000000

  # ── 5. 봇 시작 및 거래 확인 ──

  Scenario: 봇 시작 (API)
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "running"
    And 3초 대기

  Scenario: 거래 발생 확인 (API)
    When GET /api/trades?bot_id={bot_id}
    Then 응답 상태는 200
    And 응답 body.trades 는 null이 아니다

  Scenario: 봇 정지 (API)
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "stopped"

  # ── 6. 성과 조회 ──

  Scenario: 거래 내역 조회 (API)
    When GET /api/trades?bot_id={bot_id}
    Then 응답 상태는 200
    And 응답 body.trades 는 null이 아니다

  Scenario: 전략 성과 조회 (API)
    When GET /api/strategies/{strategy_id}/performance
    Then 응답 상태는 200
    And 응답 body.total_trades 는 null이 아니다
    And 응답 body.win_rate 는 null이 아니다

  Scenario: 성과 조회 (CLI)
    When 컨테이너에서 실행: ante trade list --bot {bot_id} --format json
    Then 종료 코드는 0
    And stdout에 "trades" 가 포함되어 있다
