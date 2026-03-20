Feature: 봇 CRUD
  Ante 시스템의 봇 생성, 조회, 목록, 삭제를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: 테스트용 계좌 + 전략 ──

  Scenario: CRUD 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value              |
      | account_id          | qa-bot-crud-acct   |
      | name                | 봇 CRUD 테스트 계좌 |
      | exchange            | KRX                |
      | currency            | KRW                |
      | timezone            | Asia/Seoul         |
      | trading_hours_start | 09:00              |
      | trading_hours_end   | 15:30              |
      | trading_mode        | virtual            |
      | broker_type         | mock               |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  Scenario: CRUD 테스트용 전략 등록 확인 (API)
    When GET /api/strategies
    Then 응답 상태는 200
    And 응답 body 배열 길이는 1 이상이다
    And 첫 번째 항목의 strategy_id 를 {strategy_id}로 저장한다

  # ── 정상 흐름: 봇 CRUD ──

  Scenario: 봇 생성 (API)
    When POST /api/bots 요청:
      | field            | value            |
      | bot_id           | qa-bot-crud-01   |
      | strategy_id      | {strategy_id}    |
      | name             | QA 테스트 봇     |
      | account_id       | {account_id}     |
      | interval_seconds | 60               |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 는 null이 아니다
    And 응답 body.bot.name 은 "QA 테스트 봇"
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  Scenario: 봇 생성 (CLI)
    When 컨테이너에서 실행: ante bot create --name "CLI 테스트 봇" --strategy {strategy_id} --account {account_id} --id qa-bot-crud-02 --format json
    Then 종료 코드는 0
    And stdout에 "qa-bot-crud-02" 가 포함되어 있다

  Scenario: 봇 목록 조회 (API)
    When GET /api/bots
    Then 응답 상태는 200
    And 응답 body.bots 배열 길이는 2 이상이다

  Scenario: 봇 목록 조회 (CLI)
    When 컨테이너에서 실행: ante bot list --format json
    Then 종료 코드는 0
    And stdout JSON 배열 길이는 1 이상이다

  Scenario: 봇 상세 조회 (API)
    When GET /api/bots/{bot_id}
    Then 응답 상태는 200
    And 응답 body.bot.bot_id 는 "{bot_id}"
    And 응답 body.bot.name 은 "QA 테스트 봇"

  Scenario: 봇 상세 조회 (CLI)
    When 컨테이너에서 실행: ante bot info {bot_id} --format json
    Then 종료 코드는 0
    And stdout에 {bot_id} 가 포함되어 있다
    And stdout JSON의 .name 은 "QA 테스트 봇"

  # ── 삭제 ──

  Scenario: 봇 삭제 (API)
    When DELETE /api/bots/qa-bot-crud-02
    Then 응답 상태는 204

  Scenario: 봇 삭제 (CLI)
    When 컨테이너에서 실행: ante bot remove {bot_id} --yes
    Then 종료 코드는 0

  # ── 에러 케이스 ──

  Scenario: 존재하지 않는 봇 조회 (API)
    When GET /api/bots/nonexistent-bot-12345
    Then 응답 상태는 404

  Scenario: 잘못된 strategy_id로 봇 생성 (API)
    When POST /api/bots 요청:
      | field            | value                     |
      | bot_id           | qa-bot-crud-bad           |
      | strategy_id      | nonexistent-strategy-9999 |
      | name             | 잘못된 전략 봇            |
      | account_id       | {account_id}              |
      | interval_seconds | 60                        |
    Then 응답 상태는 404
