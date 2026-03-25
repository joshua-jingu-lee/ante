Feature: 성과 집계 조회
  거래 성과를 일별/월별로 집계 조회한다. (CLI 전용)
  관련 이슈: #1048

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 일별 성과 ──

  Scenario: 일별 성과 조회
    When 컨테이너에서 실행: ante --format json report performance --period daily --start 2025-01-01 --end 2025-12-31
    Then 종료 코드는 0

  # ── 월별 성과 ──

  Scenario: 월별 성과 조회
    When 컨테이너에서 실행: ante --format json report performance --period monthly --year 2025
    Then 종료 코드는 0

  # ── 에러 케이스 ──

  Scenario: daily인데 start/end 누락 → 종료 코드 1
    When 컨테이너에서 실행: ante --format json report performance --period daily
    Then 종료 코드는 1

  Scenario: monthly인데 year 누락 → 종료 코드 1
    When 컨테이너에서 실행: ante --format json report performance --period monthly
    Then 종료 코드는 1

  Scenario: 잘못된 period 값 → 종료 코드 2
    When 컨테이너에서 실행: ante --format json report performance --period invalid
    Then 종료 코드는 2
