Feature: 계좌 생명주기
  계좌의 상태 전이(active → suspended → active → deleted)를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 사전 준비: 테스트용 계좌 생성 ──

  Scenario: 생명주기 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-lifecycle-acct-01 |
      | name                | 생명주기 테스트 계좌 |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | test                 |
    Then 응답 상태는 201
    And 응답 body.account.status 는 "active"
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  # ── 정상 흐름: 정지 → 활성화 → 삭제 ──

  Scenario: 계좌 정지 (API)
    When POST /api/accounts/{account_id}/suspend
    Then 응답 상태는 200
    And 응답 body.account.status 는 "suspended"

  Scenario: 정지된 계좌 확인 (CLI)
    When 컨테이너에서 실행: ante account info {account_id} --format json
    Then 종료 코드는 0
    And stdout JSON의 .status 는 "suspended"

  Scenario: 정지된 계좌 활성화 (API)
    When POST /api/accounts/{account_id}/activate
    Then 응답 상태는 200
    And 응답 body.account.status 는 "active"

  Scenario: 활성화된 계좌 확인 (CLI)
    When 컨테이너에서 실행: ante account info {account_id} --format json
    Then 종료 코드는 0
    And stdout JSON의 .status 는 "active"

  Scenario: 계좌 삭제 (API)
    When DELETE /api/accounts/{account_id}
    Then 응답 상태는 204

  Scenario: 삭제된 계좌 조회 시 상태 확인
    When GET /api/accounts/{account_id}
    Then 응답 상태는 404 또는 응답 body.account.status 는 "deleted"

  # ── 에러 케이스 ──

  Scenario: 정지된 계좌에서 봇 생성 거부
    # 새 계좌 생성 후 정지 → 봇 생성 시도
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-lifecycle-acct-02 |
      | name                | 봇거부 테스트 계좌   |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | test                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {suspended_account_id}로 저장한다
    When POST /api/accounts/{suspended_account_id}/suspend
    Then 응답 상태는 200
    When GET /api/strategies
    Then 응답 상태는 200
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다
    When POST /api/bots 요청:
      | field      | value                  |
      | bot_id     | qa-lifecycle-bot-01    |
      | account_id | {suspended_account_id} |
      | name       | 거부될 봇              |
      | strategy_id| {strategy_id}          |
    Then 응답 상태는 409

  Scenario: 삭제된 계좌 재활성화 불가
    # 계좌 생성 → 삭제 → 활성화 시도
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-lifecycle-acct-03 |
      | name                | 삭제후 활성화 테스트  |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | test                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {deleted_account_id}로 저장한다
    When DELETE /api/accounts/{deleted_account_id}
    Then 응답 상태는 204
    When POST /api/accounts/{deleted_account_id}/activate
    Then 응답 상태는 404 또는 응답 상태는 409

  Scenario: 이미 정지된 계좌 재정지
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-lifecycle-acct-04 |
      | name                | 재정지 테스트 계좌   |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | test                 |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {dup_suspend_id}로 저장한다
    When POST /api/accounts/{dup_suspend_id}/suspend
    Then 응답 상태는 200
    When POST /api/accounts/{dup_suspend_id}/suspend
    Then 응답 상태는 409
