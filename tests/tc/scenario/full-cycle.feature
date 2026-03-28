Feature: 전략 라이프사이클 전체 흐름 (E2E)
  계좌 생성부터 거래 실행, 성과 확인까지 전체 운영 사이클을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다
    # setup — 이전 실행 잔존 데이터 정리 (실패 무시)
    And DELETE /api/bots/qa-e2e-bot 요청 (실패 무시)

  # 1. 계좌 생성
  Scenario: E2E 테스트 계좌 생성
    When POST /api/accounts 요청:
      | field               | value              |
      | account_id          | qa-e2e-cycle       |
      | name                | E2E 테스트         |
      | exchange            | KRX                |
      | currency            | KRW                |
      | timezone            | Asia/Seoul         |
      | trading_hours_start | 09:00              |
      | trading_hours_end   | 15:30              |
      | trading_mode        | virtual            |
      | broker_type         | test               |
      | credentials         | {"app_key":"test","app_secret":"test"} |
    Then 응답 상태는 201 또는 응답 상태는 409

  # 2. 잔고 설정
  Scenario: 잔고 초기화
    When POST /api/treasury/balance 요청:
      | field   | value    |
      | balance | 10000000 |
    Then 응답 상태는 200

  # 3. 전략 확보
  Scenario: QA 매수 전략 확보
    When GET /api/strategies
    Then 응답 상태는 200
    And name이 "qa_buy_signal"인 항목의 id 를 {strategy_id}로 저장한다

  # 4. 봇 생성 및 실행
  Scenario: 봇 생성
    When POST /api/bots 요청:
      | field       | value          |
      | bot_id      | qa-e2e-bot     |
      | account_id  | qa-e2e-cycle   |
      | strategy_id | {strategy_id}  |
      | name        | E2E 봇         |
    Then 응답 상태는 201 또는 응답 상태는 409

  Scenario: 봇 시작
    When POST /api/bots/qa-e2e-bot/start
    Then 응답 상태는 200

  Scenario: 거래 발생 대기
    And 15초 대기

  Scenario: 봇 정지
    When POST /api/bots/qa-e2e-bot/stop
    Then 응답 상태는 200

  # 5. 거래 결과 확인
  Scenario: 거래 기록 존재 확인
    When GET /api/trades?bot_id=qa-e2e-bot
    Then 응답 상태는 200
    And 응답 body.trades 배열 길이는 1 이상이다

  # 6. 포지션 확인
  Scenario: 포지션 반영 확인
    When GET /api/bots/qa-e2e-bot
    Then 응답 상태는 200
    And 응답 body.bot.positions 는 null이 아니다

  # 7. 잔고 변동 확인
  Scenario: 잔고 변동 확인
    When GET /api/treasury
    Then 응답 상태는 200

  # 8. 감사 로그 확인
  Scenario: E2E 흐름 감사 로그 확인
    When GET /api/audit?member_id=qa-admin
    Then 응답 상태는 200
    And 응답 body.logs 배열 길이는 1 이상이다

  # 9. 정리
  Scenario: 봇 삭제
    When DELETE /api/bots/qa-e2e-bot
    Then 응답 상태는 204
