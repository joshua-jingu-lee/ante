Feature: 멤버 인증
  Ante 시스템의 로그인, 로그아웃, 현재 사용자 조회를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  Scenario: 로그인 성공 (API)
    When POST /api/auth/login 요청:
      | field     | value       |
      | member_id | qa-admin    |
      | password  | qa-password |
    Then 응답 상태는 200
    And 응답 body.member_id 는 "qa-admin"
    And 응답 body.name 은 null이 아니다
    And 응답 body.type 은 null이 아니다
    And 응답 헤더 Set-Cookie 에 "ante_session" 이 포함되어 있다

  Scenario: 잘못된 비밀번호 로그인 거부 (API)
    When POST /api/auth/login 요청:
      | field     | value          |
      | member_id | qa-admin       |
      | password  | wrong-password |
    Then 응답 상태는 401

  Scenario: 현재 사용자 조회 (API)
    When GET /api/auth/me
    Then 응답 상태는 200
    And 응답 body.member_id 는 null이 아니다
    And 응답 body.name 은 null이 아니다
    And 응답 body.type 은 null이 아니다
    And 응답 body.role 은 null이 아니다

  Scenario: 인증 토큰 없이 API 접근 거부
    When 인증 없이 GET /api/auth/me
    Then 응답 상태는 401

  Scenario: 로그아웃 (API)
    When POST /api/auth/logout
    Then 응답 상태는 200
    And 응답 body.ok 는 true
