Feature: 감사 로그
  시스템 감사 로그 조회 및 필터링을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # --- 감사 로그 조회 ---

  Scenario: 전체 감사 로그 조회 (API)
    When GET /api/audit
    Then 응답 상태는 200
    And 응답 body.logs 배열 길이는 1 이상이다
    And 응답 body.total 는 0보다 크다

  Scenario: 멤버별 필터링
    When GET /api/audit?member_id=qa-admin
    Then 응답 상태는 200
    And 응답 body.logs 배열 길이는 1 이상이다

  Scenario: 액션별 필터링 (접두사)
    When GET /api/audit?action=account.
    Then 응답 상태는 200

  Scenario: 페이지네이션
    When GET /api/audit?limit=5&offset=0
    Then 응답 상태는 200
    And 응답 body.logs 배열 길이는 5 이하이다

  # --- CLI ---

  Scenario: 감사 로그 조회 (CLI)
    When 컨테이너에서 실행: ante audit list --format json
    Then 종료 코드는 0

  Scenario: 멤버별 조회 (CLI)
    When 컨테이너에서 실행: ante audit list --member qa-admin --format json
    Then 종료 코드는 0

  # --- 에러 케이스 ---

  Scenario: CLI limit 최대값 초과
    When 컨테이너에서 실행: ante audit list --limit 201
    Then 종료 코드는 2
