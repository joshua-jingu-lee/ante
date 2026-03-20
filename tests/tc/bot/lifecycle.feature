Feature: 봇 생명주기
  봇의 상태 전이(생성 → 시작 → 정지 → 재시작 → 삭제)를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: 테스트용 계좌 + 전략 + 봇 ──

  Scenario: 생명주기 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-bot-life-acct     |
      | name                | 봇 생명주기 테스트 계좌 |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | mock                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  Scenario: 생명주기 테스트용 인증정보 설정 (CLI)
    When 컨테이너에서 실행: ante account set-credentials {account_id} --app-key test-key --app-secret test-secret --format json
    Then 종료 코드는 0

  Scenario: 생명주기 테스트용 전략 확인 (API)
    When GET /api/strategies
    Then 응답 상태는 200
    And 첫 번째 항목의 strategy_id 를 {strategy_id}로 저장한다

  Scenario: 생명주기 테스트용 봇 생성 (API)
    When POST /api/bots 요청:
      | field            | value            |
      | bot_id           | qa-bot-life-01   |
      | strategy_id      | {strategy_id}    |
      | name             | 생명주기 테스트 봇 |
      | account_id       | {account_id}     |
      | interval_seconds | 60               |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  # ── 정상 흐름: 시작 → 정지 → 재시작 ──

  Scenario: 봇 시작 (API)
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200
    And 응답 body.bot.bot_id 는 "{bot_id}"

  Scenario: 봇 시작 후 상태 확인 (API)
    And 3초 대기
    When GET /api/bots/{bot_id}
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "running"

  Scenario: 봇 정지 (API)
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200
    And 응답 body.bot.bot_id 는 "{bot_id}"

  Scenario: 봇 정지 후 상태 확인 (API)
    When GET /api/bots/{bot_id}
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "stopped"

  Scenario: 정지된 봇 재시작 (API)
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200
    And 응답 body.bot.bot_id 는 "{bot_id}"

  Scenario: 재시작 후 정지 (API)
    And 3초 대기
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200

  # ── CLI: Signal Key / 포지션 ──

  Scenario: Signal Key 조회 (CLI)
    When 컨테이너에서 실행: ante bot signal-key {bot_id} --format json
    Then 종료 코드는 0
    And stdout에 {bot_id} 가 포함되어 있다

  Scenario: 봇 포지션 조회 (CLI)
    When 컨테이너에서 실행: ante bot positions {bot_id} --format json
    Then 종료 코드는 0

  # ── 에러 케이스 ──

  Scenario: 이미 실행 중인 봇 재시작 시도 (API)
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200
    And 3초 대기
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 409

  Scenario: 이미 정지된 봇 재정지 시도 (API)
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200
    And 3초 대기
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 409
