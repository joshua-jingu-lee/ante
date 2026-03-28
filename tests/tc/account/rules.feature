Feature: 계좌 리스크 룰 관리
  계좌별 리스크 룰 조회 및 수정을 검증한다.
  관련 이슈: #798 (GET/PUT rules)

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다
    # setup — 이전 실행 잔존 데이터 정리 (실패 무시)
    And DELETE /api/accounts/qa-rules-acct-01 요청 (실패 무시)

  # ── 사전 준비: 테스트용 계좌 생성 ──

  Scenario: 룰 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value              |
      | account_id          | qa-rules-acct-01   |
      | name                | 룰 테스트 계좌     |
      | exchange            | KRX                |
      | currency            | KRW                |
      | timezone            | Asia/Seoul         |
      | trading_hours_start | 09:00              |
      | trading_hours_end   | 15:30              |
      | trading_mode        | virtual            |
      | broker_type         | test               |
      | credentials         | {"app_key": "test", "app_secret": "test"} |
    Then 응답 상태는 201 또는 응답 상태는 409
    # 409 시 body.account 가 없으므로 리터럴 account_id를 직접 사용한다

  # ── 룰 수정 ──

  Scenario: daily_loss_limit 룰 수정 (API)
    When PUT /api/accounts/qa-rules-acct-01/rules/daily_loss_limit 요청:
      | field   | value |
      | enabled | true  |
      | params  | {"max_loss_pct": 5.0} |
    Then 응답 상태는 200
    And 응답 body.rule.type 은 "daily_loss_limit"
    And 응답 body.rule.enabled 는 true

  # ── 룰 목록 조회 ──

  Scenario: 계좌 리스크 룰 목록 조회 (API)
    When GET /api/accounts/qa-rules-acct-01/rules
    Then 응답 상태는 200
    And 응답 body.rules 는 null이 아니다
    And 응답 body.rules 배열 길이는 1 이상이다

  Scenario: 룰 항목에 type 필드 확인 (API)
    When GET /api/accounts/qa-rules-acct-01/rules
    Then 응답 상태는 200
    And 응답 body.rules[0].type 은 null이 아니다

  Scenario: 수정된 룰 반영 확인 (API)
    When GET /api/accounts/qa-rules-acct-01/rules
    Then 응답 상태는 200

  # ── 에러 케이스 ──

  Scenario: 존재하지 않는 계좌 룰 조회 (API)
    When GET /api/accounts/nonexistent-acct-99999/rules
    Then 응답 상태는 404

  Scenario: 존재하지 않는 룰 타입 수정 (API)
    When PUT /api/accounts/qa-rules-acct-01/rules/nonexistent_rule 요청:
      | field   | value |
      | enabled | true  |
      | params  | {}    |
    Then 응답 상태는 400

  Scenario: 유효하지 않은 룰 params (API)
    When PUT /api/accounts/qa-rules-acct-01/rules/daily_loss_limit 요청:
      | field   | value |
      | enabled | true  |
      | params  | {"max_loss_pct": -1} |
    Then 응답 상태는 422
