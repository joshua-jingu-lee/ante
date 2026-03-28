Feature: 봇 생명주기
  봇 시작, 정지, 실행 로그 조회, 삭제(포지션 처리)를 검증한다.
  관련 이슈: #786 (봇 로그 API), #796 (handle_positions)

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다
    # setup — 이전 실행 잔존 데이터 정리 (실패 무시)
    And DELETE /api/bots/qa-bot-life-bot-01 요청 (실패 무시)
    And DELETE /api/bots/qa-bot-life-bot-02 요청 (실패 무시)
    And DELETE /api/bots/qa-bot-life-bot-03 요청 (실패 무시)

  # ── 사전 준비: 계좌 + 잔고 + 전략 + 크레덴셜 + 봇 생성 ──

  Scenario: 생명주기 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value              |
      | account_id          | qa-bot-life-01     |
      | name                | 봇 생명주기 테스트 |
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

  Scenario: QA 샘플 전략 확보
    When GET /api/strategies
    Then 응답 상태는 200
    And name이 "qa_sample"인 항목의 id 를 {strategy_id}로 저장한다

  Scenario: 생명주기 테스트 봇 생성 (API)
    When POST /api/bots 요청:
      | field       | value              |
      | bot_id      | qa-bot-life-bot-01 |
      | account_id  | {account_id}       |
      | strategy_id | {strategy_id}      |
      | name        | 생명주기 봇        |
    Then 응답 상태는 201 또는 응답 상태는 409
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  # ── 봇 시작/정지 ──

  Scenario: 봇 시작 (API)
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "running"

  Scenario: 봇 실행 대기
    And 5초 대기

  Scenario: 봇 정지 (API)
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200
    And 응답 body.bot.status 는 "stopped"

  # ── 봇 실행 로그 조회 (#786) ──

  Scenario: 봇 실행 로그 조회 (API)
    When GET /api/bots/{bot_id}/logs
    Then 응답 상태는 200
    And 응답 body.logs 는 null이 아니다

  Scenario: 봇 실행 로그 limit 파라미터 (API)
    When GET /api/bots/{bot_id}/logs?limit=5
    Then 응답 상태는 200
    And 응답 body.logs 는 null이 아니다

  Scenario: 존재하지 않는 봇 로그 조회 (API)
    When GET /api/bots/nonexistent-bot-99999/logs
    Then 응답 상태는 404

  # ── 봇 시작/정지 에러 케이스 ──

  Scenario: 이미 정지된 봇 재정지 (API)
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200

  Scenario: 존재하지 않는 봇 시작 (API)
    When POST /api/bots/nonexistent-bot-99999/start
    Then 응답 상태는 404

  # ── 봇 삭제 + handle_positions (#796) ──

  Scenario: handle_positions=keep 봇 삭제 (API)
    # 새 봇 생성 후 keep 모드로 삭제
    When POST /api/bots 요청:
      | field       | value              |
      | bot_id      | qa-bot-life-bot-02 |
      | account_id  | {account_id}       |
      | strategy_id | {strategy_id}      |
      | name        | keep 삭제 봇       |
    Then 응답 상태는 201 또는 응답 상태는 409
    And 응답 body.bot.bot_id 를 {keep_bot_id}로 저장한다
    When DELETE /api/bots/{keep_bot_id}?handle_positions=keep
    Then 응답 상태는 204

  Scenario: handle_positions=liquidate 봇 삭제 (API)
    # 새 봇 생성 후 liquidate 모드로 삭제
    When POST /api/bots 요청:
      | field       | value              |
      | bot_id      | qa-bot-life-bot-03 |
      | account_id  | {account_id}       |
      | strategy_id | {strategy_id}      |
      | name        | liquidate 삭제 봇  |
    Then 응답 상태는 201 또는 응답 상태는 409
    And 응답 body.bot.bot_id 를 {liq_bot_id}로 저장한다
    When DELETE /api/bots/{liq_bot_id}?handle_positions=liquidate
    Then 응답 상태는 204

  Scenario: handle_positions 기본값(keep) 봇 삭제 (API)
    When DELETE /api/bots/{bot_id}
    Then 응답 상태는 204
