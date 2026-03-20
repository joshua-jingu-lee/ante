Feature: 전략 성과 및 거래 내역 조회
  전략별 성과 지표, 거래 내역, 일간/주간/월간 요약을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # --- 사전 데이터 확보 ---

  Scenario: 전략 ID 확보
    When GET /api/strategies
    Then 응답 상태는 200
    And 응답 body.strategies 배열 길이는 1 이상이다
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다

  # --- 전략 성과 조회 ---

  Scenario: 전략 성과 조회 (API)
    When GET /api/strategies/{strategy_id}/performance
    Then 응답 상태는 200
    And 응답 body.total_trades 는 null이 아니다
    And 응답 body.win_rate 는 null이 아니다

  Scenario: 존재하지 않는 전략 성과 조회 (API)
    When GET /api/strategies/nonexistent-strategy-99999/performance
    Then 응답 상태는 404

  # --- 전략별 거래 내역 ---

  Scenario: 전략별 거래 내역 조회 (API)
    When GET /api/strategies/{strategy_id}/trades
    Then 응답 상태는 200
    And 응답 body.trades 는 null이 아니다

  Scenario: 존재하지 않는 전략 거래 내역 조회 (API)
    When GET /api/strategies/nonexistent-strategy-99999/trades
    Then 응답 상태는 404

  # --- 일간/주간/월간 요약 ---

  Scenario: 일간 요약 조회 (API)
    When GET /api/strategies/{strategy_id}/daily-summary
    Then 응답 상태는 200
    And 응답 body.items 는 null이 아니다

  Scenario: 주간 요약 조회 (API)
    When GET /api/strategies/{strategy_id}/weekly-summary
    Then 응답 상태는 200
    And 응답 body.items 는 null이 아니다

  Scenario: 월간 요약 조회 (API)
    When GET /api/strategies/{strategy_id}/monthly-summary
    Then 응답 상태는 200
    And 응답 body.items 는 null이 아니다

  Scenario: 존재하지 않는 전략 일간 요약 조회 (API)
    When GET /api/strategies/nonexistent-strategy-99999/daily-summary
    Then 응답 상태는 404
