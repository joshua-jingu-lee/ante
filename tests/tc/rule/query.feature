Feature: 리스크 룰 조회
  리스크 룰 목록 조회, 범위 필터링, 에러 케이스를 검증한다.
  관련 이슈: #1043 (Rule Engine TC 보강), #1086 (QA 환경 기본 룰 미시딩 대응)

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 전체 룰 목록 조회 ──

  Scenario: 전체 룰 목록 조회 (CLI)
    When 컨테이너에서 실행: ante --format json rule list
    Then 종료 코드는 0
    And stdout에 "rules" 가 포함되어 있다

  # ── 글로벌 룰 필터링 ──

  Scenario: 글로벌 룰 필터링 (CLI)
    When 컨테이너에서 실행: ante --format json rule list --scope global
    Then 종료 코드는 0
    And stdout에 "rules" 가 포함되어 있다

  # ── 전략별 룰 필터링 ──

  Scenario: 전략별 룰 필터링 (CLI)
    When 컨테이너에서 실행: ante --format json rule list --scope strategy
    Then 종료 코드는 0
    And stdout에 "rules" 가 포함되어 있다

  # ── 에러 케이스 ──

  Scenario: 존재하지 않는 룰 조회 (CLI)
    When 컨테이너에서 실행: ante --format json rule info nonexistent_rule_99999
    Then 종료 코드는 1
    And stdout에 "찾을 수 없습니다" 가 포함되어 있다
