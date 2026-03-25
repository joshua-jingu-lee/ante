Feature: 봇 CRUD
  봇 생성, 목록 조회, 상세 조회, 설정 수정, 삭제를 검증한다.
  관련 이슈: #792 (strategy_name), #795 (PUT 봇 수정)

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: 계좌 + 전략 + 잔고 확보 ──

  Scenario: 봇 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value              |
      | account_id          | qa-bot-crud-01     |
      | name                | 봇 CRUD 테스트     |
      | exchange            | KRX                |
      | currency            | KRW                |
      | timezone            | Asia/Seoul         |
      | trading_hours_start | 09:00              |
      | trading_hours_end   | 15:30              |
      | trading_mode        | virtual            |
      | broker_type         | test               |
      | credentials         | {"app_key":"test","app_secret":"test"} |
    Then 응답 상태는 201 또는 응답 상태는 409
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  Scenario: 잔고 설정 (API)
    When POST /api/treasury/balance 요청:
      | field   | value    |
      | balance | 10000000 |
    Then 응답 상태는 200

  Scenario: QA 전략 확보
    When GET /api/strategies
    Then 응답 상태는 200
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다
    And 첫 번째 항목의 name 을 {strategy_name}으로 저장한다

  # ── 봇 생성 ──

  Scenario: 봇 생성 (API)
    When POST /api/bots 요청:
      | field       | value              |
      | bot_id      | qa-bot-crud-bot-01 |
      | account_id  | {account_id}       |
      | strategy_id | {strategy_id}      |
      | name        | CRUD 테스트 봇     |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  # ── 봇 목록 조회 + strategy_name 검증 (#792) ──

  Scenario: 봇 목록 조회 — strategy_name 포함 (API)
    When GET /api/bots
    Then 응답 상태는 200
    And 응답 body.bots 배열 길이는 1 이상이다
    And 응답 body.bots[0].strategy_name 은 null이 아니다

  Scenario: 봇 목록 조회 (CLI)
    When 컨테이너에서 실행: ante bot list
    Then 종료 코드는 0

  # ── 봇 상세 조회 ──

  Scenario: 봇 상세 조회 (API)
    When GET /api/bots/{bot_id}
    Then 응답 상태는 200
    And 응답 body.bot.bot_id 는 {bot_id}
    And 응답 body.bot.name 은 "CRUD 테스트 봇"
    And 응답 body.bot.strategy_id 는 null이 아니다

  Scenario: 봇 상세 조회 (CLI)
    When 컨테이너에서 실행: ante bot info {bot_id}
    Then 종료 코드는 0
    And stdout에 {bot_id} 가 포함되어 있다

  # ── 봇 설정 수정 (#795) ──

  Scenario: 봇 이름 수정 (API)
    When PUT /api/bots/{bot_id} 요청:
      | field | value          |
      | name  | 수정된 봇 이름 |
    Then 응답 상태는 200
    And 응답 body.bot.name 은 "수정된 봇 이름"

  Scenario: 봇 실행 주기 수정 (API)
    When PUT /api/bots/{bot_id} 요청:
      | field            | value |
      | interval_seconds | 120   |
    Then 응답 상태는 200
    And 응답 body.bot.interval_seconds 는 120

  Scenario: 봇 예산 수정 (API)
    When PUT /api/bots/{bot_id} 요청:
      | field  | value   |
      | budget | 2000000 |
    Then 응답 상태는 200

  # ── 봇 수정 에러 케이스 (#795) ──

  Scenario: 실행 중 봇 수정 거부 (API)
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200 또는 응답 상태는 409
    When PUT /api/bots/{bot_id} 요청:
      | field | value      |
      | name  | 거부될이름 |
    Then 응답 상태는 409
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200 또는 응답 상태는 409

  Scenario: 존재하지 않는 봇 수정 (API)
    When PUT /api/bots/nonexistent-bot-99999 요청:
      | field | value  |
      | name  | 실패봇 |
    Then 응답 상태는 404

  Scenario: 유효하지 않은 interval_seconds (API)
    When PUT /api/bots/{bot_id} 요청:
      | field            | value |
      | interval_seconds | 1     |
    Then 응답 상태는 422

  # ── 봇 삭제 ──

  Scenario: 봇 삭제 (API)
    When DELETE /api/bots/{bot_id}
    Then 응답 상태는 204

  Scenario: 존재하지 않는 봇 조회 (API)
    When GET /api/bots/nonexistent-bot-99999
    Then 응답 상태는 404

  Scenario: 존재하지 않는 봇 삭제 (API)
    When DELETE /api/bots/nonexistent-bot-99999
    Then 응답 상태는 404
