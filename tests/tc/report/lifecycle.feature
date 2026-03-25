Feature: 리포트 제출 및 조회
  전략 성과 리포트의 스키마 확인, 제출, 조회를 검증한다.
  관련 이슈: #1045

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 스키마 조회 ──

  Scenario: 리포트 스키마 조회 (API)
    When GET /api/reports/schema
    Then 응답 상태는 200
    And 응답 body.required_fields 는 null이 아니다

  Scenario: 리포트 스키마 조회 (CLI)
    When 컨테이너에서 실행: ante report schema --format json
    Then 종료 코드는 0
    And stdout에 "required_fields" 가 포함되어 있다

  # ── 리포트 제출 ──

  Scenario: 리포트 제출 (API)
    When POST /api/reports 요청:
      | field              | value                      |
      | strategy_name      | qa_buy_signal              |
      | strategy_version   | 1.0.0                      |
      | strategy_path      | strategies/qa_buy_signal.py |
      | backtest_period    | 2025-04-01~2025-12-31      |
      | total_return_pct   | 15.3                       |
      | total_trades       | 42                         |
      | sharpe_ratio       | 1.2                        |
      | max_drawdown_pct   | 8.5                        |
      | win_rate           | 58.0                       |
      | summary            | QA 테스트 리포트           |
      | rationale          | QA 자동 검증용 리포트      |
    Then 응답 상태는 201
    And 응답 body.report_id 는 null이 아니다
    And 응답 body.report_id 를 {report_id}로 저장한다

  # ── 리포트 조회 ──

  Scenario: 리포트 상세 조회 (API)
    When GET /api/reports/{report_id}
    Then 응답 상태는 200
    And 응답 body.strategy_name 는 "qa_buy_signal"

  Scenario: 리포트 목록 조회 (API)
    When GET /api/reports
    Then 응답 상태는 200
    And 응답 body.reports 배열 길이는 1 이상이다

  Scenario: 리포트 목록 조회 (CLI)
    When 컨테이너에서 실행: ante report list --format json
    Then 종료 코드는 0

  Scenario: 리포트 상세 조회 (CLI)
    When 컨테이너에서 실행: ante report view {report_id} --format json
    Then 종료 코드는 0

  # ── 에러 케이스 ──

  Scenario: 존재하지 않는 리포트 조회 → 404 (API)
    When GET /api/reports/nonexistent-report-99999
    Then 응답 상태는 404

  Scenario: 필수 필드 누락 리포트 제출 → 422 (API)
    When POST /api/reports 요청:
      | field         | value      |
      | strategy_name | incomplete |
    Then 응답 상태는 422
