Feature: 동적 설정 관리
  동적 설정의 조회, 변경, 변경 이력 조회를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # --- 설정 목록 조회 ---

  Scenario: 동적 설정 목록 조회 (API)
    When GET /api/config
    Then 응답 상태는 200
    And 응답 body.configs 는 null이 아니다

  Scenario: 설정 목록 조회 (CLI)
    When 컨테이너에서 실행: ante config get --format json
    Then 종료 코드는 0
    And stdout에 "configs" 가 포함되어 있다

  # --- 설정 변경 ---

  Scenario: 동적 설정 변경 (API)
    When PUT /api/config/risk.test_qa_key 요청:
      | field | value |
      | value | 42    |
    Then 응답 상태는 200
    And 응답 body.key 은 "risk.test_qa_key"
    And 응답 body.new_value 는 null이 아니다

  Scenario: 동적 설정 변경 (CLI)
    When 컨테이너에서 실행: ante config set risk.test_qa_key 99 --format json
    Then 종료 코드는 0
    And stdout에 "success" 가 포함되어 있다

  # --- 설정 변경 이력 ---

  Scenario: 설정 변경 이력 조회 (CLI)
    When 컨테이너에서 실행: ante config history risk.test_qa_key --format json
    Then 종료 코드는 0
    And stdout에 "history" 가 포함되어 있다

  # --- 에러 케이스 ---

  Scenario: 존재하지 않는 설정 키 변경 (API)
    When PUT /api/config/nonexistent.key.12345 요청:
      | field | value |
      | value | 1     |
    Then 응답 상태는 404
