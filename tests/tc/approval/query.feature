Feature: 결재 조회 및 검색
  결재 목록 조회, 필터링, 키워드 검색을 검증한다.
  관련 이슈: #794 (search 파라미터)

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 결재 목록 조회 ──

  Scenario: 결재 목록 조회 (API)
    When GET /api/approvals
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다

  Scenario: 결재 상태 필터 (API)
    When GET /api/approvals?status=pending
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다

  Scenario: 결재 유형 필터 (API)
    When GET /api/approvals?type=strategy_submit
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다

  # ── 키워드 검색 (#794) ──

  Scenario: 제목 키워드 검색 (API)
    When GET /api/approvals?search=momentum
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다

  Scenario: 빈 검색어 — 전체 반환 (API)
    When GET /api/approvals?search=
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다

  Scenario: 매칭 없는 검색어 — 빈 목록 (API)
    When GET /api/approvals?search=zzz_nonexistent_keyword_999
    Then 응답 상태는 200
    And 응답 body.approvals 배열 길이는 0

  Scenario: 검색 + 상태 필터 복합 조건 (API)
    When GET /api/approvals?search=momentum&status=pending
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다

  # ── 페이지네이션 ──

  Scenario: 페이지네이션 (API)
    When GET /api/approvals?offset=0&limit=5
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다
