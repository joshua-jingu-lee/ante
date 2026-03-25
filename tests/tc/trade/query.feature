Feature: 거래 내역 조회
  거래 목록 조회와 봇별 거래 필터링을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # --- 거래 목록 조회 ---

  Scenario: 거래 목록 조회 (API)
    When GET /api/trades
    Then 응답 상태는 200
    And 응답 body.trades 는 null이 아니다

  Scenario: 거래 목록 조회 (CLI)
    When 컨테이너에서 실행: ante trade list --format json
    Then 종료 코드는 0
    And stdout에 "trades" 가 포함되어 있다

  # --- 봇별 거래 필터링 ---

  Scenario: 봇별 거래 필터링 (API)
    When GET /api/trades?bot_id=qa-test-bot-01
    Then 응답 상태는 200
    And 응답 body.trades 는 null이 아니다

  Scenario: 봇별 거래 필터링 (CLI)
    When 컨테이너에서 실행: ante trade list --bot qa-test-bot-01 --format json
    Then 종료 코드는 0
    And stdout에 "trades" 가 포함되어 있다

  # --- 종목별 거래 필터링 ---

  Scenario: 종목별 거래 필터링 (API)
    When GET /api/trades?symbol=000001
    Then 응답 상태는 200
    And 응답 body.trades 는 null이 아니다

  # --- 계좌별 거래 필터링 ---

  Scenario: 계좌별 거래 필터링 (API)
    When GET /api/trades?account_id=qa-trade-exec-01
    Then 응답 상태는 200
    And 응답 body.trades 는 null이 아니다

  # --- 거래 목록 limit 제한 ---

  Scenario: 거래 목록 limit 제한 (API)
    When GET /api/trades?limit=1
    Then 응답 상태는 200
    And 응답 body.trades 배열 길이는 1 이하이다

  # --- 거래 상세 조회 (CLI) ---

  Scenario: 존재하지 않는 거래 조회 (CLI)
    When 컨테이너에서 실행: ante trade info nonexistent-trade-99999 --format json
    Then 종료 코드는 0
    And stdout에 "찾을 수 없습니다" 가 포함되어 있다
