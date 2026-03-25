Feature: 결재 워크플로우 승인/거부
  결재 승인, 거부, 상태 전이 및 에러 케이스를 검증한다.
  관련 이슈: #1042

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: pending 결재 확보 ──

  Scenario: pending 결재 목록 조회 (API)
    When GET /api/approvals?status=pending
    Then 응답 상태는 200
    And 응답 body.approvals 는 null이 아니다

  Scenario: 결재 상세 조회 (API)
    # pending 결재가 하나 이상 존재해야 한다 (봇 생성 등에서 자동 생성)
    When GET /api/approvals?status=pending
    Then 응답 상태는 200
    And 첫 번째 항목의 id 를 {approval_id}로 저장한다
    When GET /api/approvals/{approval_id}
    Then 응답 상태는 200
    And 응답 body.approval.id 는 null이 아니다
    And 응답 body.approval.status 는 "pending"

  # ── 승인 플로우 ──

  Scenario: 결재 승인 (API)
    When PATCH /api/approvals/{approval_id}/status 요청:
      | field  | value    |
      | status | approved |
      | memo   |          |
    Then 응답 상태는 200
    And 응답 body.approval.status 는 "approved"

  Scenario: 승인된 결재 재승인 시도 → 404 (API)
    # 이미 approved 상태 — pending/execution_failed만 승인 가능
    When PATCH /api/approvals/{approval_id}/status 요청:
      | field  | value    |
      | status | approved |
      | memo   |          |
    Then 응답 상태는 404

  # ── 거부 플로우: 새 pending 결재 확보 ──

  Scenario: 거부 테스트용 pending 결재 확보 (API)
    When GET /api/approvals?status=pending
    Then 응답 상태는 200
    And 첫 번째 항목의 id 를 {reject_approval_id}로 저장한다

  Scenario: 결재 거부 (API)
    When PATCH /api/approvals/{reject_approval_id}/status 요청:
      | field  | value    |
      | status | rejected |
      | memo   | QA 테스트 거부 |
    Then 응답 상태는 200
    And 응답 body.approval.status 는 "rejected"

  # ── 에러 케이스 ──

  Scenario: 존재하지 않는 결재 승인 → 404 (API)
    When PATCH /api/approvals/nonexistent-approval-99999/status 요청:
      | field  | value    |
      | status | approved |
      | memo   |          |
    Then 응답 상태는 404

  Scenario: 잘못된 상태값 전달 → 400 (API)
    # "approved" / "rejected" 외의 값은 400 반환
    When PATCH /api/approvals/{reject_approval_id}/status 요청:
      | field  | value   |
      | status | invalid |
      | memo   |         |
    Then 응답 상태는 400
