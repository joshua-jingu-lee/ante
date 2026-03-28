Feature: 거래 실행 및 포지션 반영
  봇이 매수 시그널을 발생시키고, 주문 → 체결 → 거래 기록 → 포지션 반영까지의 전체 흐름을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다
    # setup — 이전 실행 잔존 데이터 정리 (실패 무시)
    And DELETE /api/bots/qa-trade-bot-01 요청 (실패 무시)

  # --- 사전 준비 ---

  Scenario: 거래 테스트용 계좌 확보
    When POST /api/accounts 요청:
      | field               | value              |
      | account_id          | qa-trade-exec-01   |
      | name                | 거래 실행 테스트   |
      | exchange            | KRX                |
      | currency            | KRW                |
      | timezone            | Asia/Seoul         |
      | trading_hours_start | 09:00              |
      | trading_hours_end   | 15:30              |
      | trading_mode        | virtual            |
      | broker_type         | test               |
      | credentials         | {"app_key":"test","app_secret":"test"} |
    Then 응답 상태는 201 또는 응답 상태는 409

  Scenario: 잔고 설정
    When POST /api/treasury/balance 요청:
      | field   | value    |
      | balance | 10000000 |
    Then 응답 상태는 200

  Scenario: QA 매수 전략 확보
    When GET /api/strategies
    Then 응답 상태는 200
    And name이 "qa_buy_signal"인 항목의 id 를 {strategy_id}로 저장한다

  Scenario: 매수 시그널 봇 생성
    When POST /api/bots 요청:
      | field       | value              |
      | bot_id      | qa-trade-bot-01    |
      | account_id  | qa-trade-exec-01   |
      | strategy_id | {strategy_id}      |
      | name        | 거래 실행 테스트봇 |
    Then 응답 상태는 201 또는 응답 상태는 409
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  Scenario: 봇 시작
    When POST /api/bots/{bot_id}/start
    Then 응답 상태는 200

  Scenario: 거래 발생 대기
    And 10초 대기

  # --- 거래 결과 검증 ---

  Scenario: 거래 기록 생성 확인 (API)
    When GET /api/trades?bot_id={bot_id}
    Then 응답 상태는 200
    And 응답 body.trades 배열 길이는 1 이상이다

  Scenario: 포지션 반영 확인 (봇 상세에서)
    When GET /api/bots/{bot_id}
    Then 응답 상태는 200
    And 응답 body.bot.positions 는 null이 아니다

  Scenario: 봇 정지
    When POST /api/bots/{bot_id}/stop
    Then 응답 상태는 200

  # --- 에러 케이스 ---

  Scenario: 존재하지 않는 거래 상세 조회 (CLI)
    When 컨테이너에서 실행: ante trade info nonexistent-trade-99999 --format json
    Then 종료 코드는 0
    And stdout에 "찾을 수 없습니다" 가 포함되어 있다
