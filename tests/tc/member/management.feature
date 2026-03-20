Feature: 멤버 관리
  Ante 시스템의 멤버 등록, 조회, 상태 변경, 비밀번호 변경, 권한 설정, 토큰 갱신을 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 멤버 등록 ──

  Scenario: 멤버 등록 (API)
    When POST /api/members 요청:
      | field       | value              |
      | member_id   | qa-test-agent-01   |
      | member_type | agent              |
      | role        | default            |
      | org         | qa-org             |
      | name        | QA 테스트 에이전트 |
      | scopes      | []                 |
    Then 응답 상태는 201
    And 응답 body.member.member_id 는 "qa-test-agent-01"
    And 응답 body.member.status 는 "active"
    And 응답 body.token 은 null이 아니다
    And 응답 body.member.member_id 를 {agent_member_id}로 저장한다

  Scenario: 멤버 등록 (CLI)
    When 컨테이너에서 실행: ante member register --id qa-test-human-01 --type human --org qa-org --name "QA 테스트 사용자" --format json
    Then 종료 코드는 0
    And stdout JSON의 .member_id 는 "qa-test-human-01"
    And stdout에 "token" 가 포함되어 있다

  # ── 멤버 목록 조회 ──

  Scenario: 멤버 목록 조회 (API)
    When GET /api/members
    Then 응답 상태는 200
    And 응답 body.members 배열 길이는 1 이상이다

  Scenario: 멤버 목록 조회 (CLI)
    When 컨테이너에서 실행: ante member list --format json
    Then 종료 코드는 0
    And stdout JSON의 .members 배열 길이는 1 이상이다

  # ── 멤버 상세 조회 ──

  Scenario: 멤버 상세 조회 (API)
    When GET /api/members/{agent_member_id}
    Then 응답 상태는 200
    And 응답 body.member.member_id 는 "qa-test-agent-01"
    And 응답 body.member.name 은 "QA 테스트 에이전트"
    And 응답 body.member.org 은 "qa-org"

  # ── 멤버 정지 / 재활성화 / 철회 ──

  Scenario: 멤버 정지 (API)
    When POST /api/members/{agent_member_id}/suspend
    Then 응답 상태는 200
    And 응답 body.member.status 는 "suspended"

  Scenario: 멤버 재활성화 (API)
    When POST /api/members/{agent_member_id}/reactivate
    Then 응답 상태는 200
    And 응답 body.member.status 는 "active"

  Scenario: 멤버 철회 (API)
    When POST /api/members/{agent_member_id}/revoke
    Then 응답 상태는 200
    And 응답 body.member.status 는 "revoked"

  # ── 비밀번호 변경 ──

  Scenario: 비밀번호 변경 (API)
    When PATCH /api/members/qa-test-human-01/password 요청:
      | field        | value        |
      | old_password | qa-password  |
      | new_password | new-password |
    Then 응답 상태는 200
    And 응답 body.ok 는 true

  # ── 권한(scopes) 설정 ──

  Scenario: 권한 범위 설정 (API)
    When PUT /api/members/qa-test-human-01/scopes 요청:
      | field  | value                          |
      | scopes | ["member:read", "account:read"] |
    Then 응답 상태는 200
    And 응답 body.member.member_id 는 "qa-test-human-01"

  # ── 토큰 갱신 ──

  Scenario: 토큰 갱신 (API)
    When POST /api/members/qa-test-human-01/rotate-token
    Then 응답 상태는 200
    And 응답 body.token 은 null이 아니다
    And 응답 body.member.member_id 는 "qa-test-human-01"

  # ── 에러 케이스 ──

  Scenario: 존재하지 않는 멤버 조회
    When GET /api/members/nonexistent-member-id
    Then 응답 상태는 404

  Scenario: 중복 멤버 등록
    When POST /api/members 요청:
      | field       | value            |
      | member_id   | qa-test-human-01 |
      | member_type | human            |
    Then 응답 상태는 400
