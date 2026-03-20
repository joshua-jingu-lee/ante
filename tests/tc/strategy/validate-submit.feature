Feature: 전략 검증 및 조회
  전략 파일 검증, 전략 목록 조회, 전략 상세 조회를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # --- 전략 검증 ---

  Scenario: 전략 파일 검증 성공 (API)
    When POST /api/strategies/validate 요청:
      | field | value                        |
      | path  | /app/strategies/qa_sample.py  |
    Then 응답 상태는 200
    And 응답 body.valid 은 true

  Scenario: 존재하지 않는 전략 파일 검증 (API)
    When POST /api/strategies/validate 요청:
      | field | value                       |
      | path  | /app/strategies/no_exist.py  |
    Then 응답 상태는 404

  Scenario: path 누락 전략 검증 (API)
    When POST /api/strategies/validate 요청:
      | field | value |
      | path  |       |
    Then 응답 상태는 400

  # --- 전략 목록 조회 ---

  Scenario: 전략 목록 조회 (API)
    When GET /api/strategies
    Then 응답 상태는 200
    And 응답 body.strategies 는 null이 아니다

  Scenario: 전략 목록 조회 (CLI)
    When 컨테이너에서 실행: ante strategy list --format json
    Then 종료 코드는 0
    And stdout에 "strategies" 가 포함되어 있다

  # --- 전략 상세 조회 ---

  Scenario: 전략 상세 조회 — 사전 데이터 확보 (API)
    When GET /api/strategies
    Then 응답 상태는 200
    And 응답 body.strategies 배열 길이는 1 이상이다
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다
    And 첫 번째 항목의 name 을 {strategy_name}으로 저장한다

  Scenario: 전략 상세 조회 (API)
    When GET /api/strategies/{strategy_id}
    Then 응답 상태는 200
    And 응답 body.strategy 는 null이 아니다
    And 응답 body.strategy.name 은 null이 아니다

  Scenario: 전략 상세 조회 (CLI)
    When 컨테이너에서 실행: ante strategy info {strategy_name} --format json
    Then 종료 코드는 0
    And stdout JSON의 .name 은 null이 아니다

  Scenario: 존재하지 않는 전략 조회 (API)
    When GET /api/strategies/nonexistent-strategy-99999
    Then 응답 상태는 404
