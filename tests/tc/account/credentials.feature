Feature: 계좌 인증정보 관리
  계좌의 인증정보(credentials) 설정, 조회, 필수 누락 에러를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 환경 정리: 이전 실행 잔여 데이터 삭제 ──
  # API DELETE로 서버 메모리 캐시 정리 → DB 물리 삭제로 soft-delete 레코드 제거

  Scenario: 이전 테스트 봇 삭제 (API+DB)
    When DELETE /api/bots/qa-cred-bot-01
    Then 응답 상태는 204 또는 응답 상태는 404
    When DELETE /api/bots/qa-no-cred-bot-01
    Then 응답 상태는 204 또는 응답 상태는 404
    When 컨테이너에서 실행: sqlite3 /app/db/ante.db "DELETE FROM bots WHERE bot_id IN ('qa-cred-bot-01','qa-no-cred-bot-01')"
    Then 종료 코드는 0

  Scenario: 이전 테스트 계좌 삭제 (API+DB)
    When DELETE /api/accounts/qa-cred-acct-01
    Then 응답 상태는 204 또는 응답 상태는 404
    When DELETE /api/accounts/qa-cred-acct-02
    Then 응답 상태는 204 또는 응답 상태는 404
    When 컨테이너에서 실행: sqlite3 /app/db/ante.db "DELETE FROM accounts WHERE account_id IN ('qa-cred-acct-01','qa-cred-acct-02')"
    Then 종료 코드는 0

  # ── 사전 준비: 테스트용 계좌 생성 ──

  Scenario: 인증정보 테스트용 계좌 생성 (API)
    When POST /api/accounts 요청:
      | field               | value               |
      | account_id          | qa-cred-acct-01     |
      | name                | 인증정보 테스트 계좌 |
      | exchange            | KRX                 |
      | currency            | KRW                 |
      | timezone            | Asia/Seoul          |
      | trading_hours_start | 09:00               |
      | trading_hours_end   | 15:30               |
      | trading_mode        | virtual             |
      | broker_type         | test                |
      | credentials         | {"app_key": "test", "app_secret": "test"} |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  # ── 정상 흐름: 인증정보 설정 및 조회 ──

  Scenario: 인증정보 설정 (CLI)
    When 컨테이너에서 실행: ante account set-credentials {account_id} --app-key test-app-key --app-secret test-app-secret --format json
    Then 종료 코드는 0

  Scenario: 인증정보 조회 (CLI)
    When 컨테이너에서 실행: ante account credentials {account_id} --format json
    Then 종료 코드는 0
    And stdout JSON의 .credentials.app_key 는 null이 아니다

  Scenario: 인증정보 설정 후 봇 생성 및 시작 가능
    When GET /api/strategies?name=qa_sample
    Then 응답 상태는 200
    And 첫 번째 항목의 id 를 {strategy_id}로 저장한다
    When POST /api/bots 요청:
      | field       | value              |
      | bot_id      | qa-cred-bot-01     |
      | account_id  | {account_id}       |
      | name        | 인증정보 있는 봇   |
      | strategy_id | {strategy_id}      |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  # ── 에러 케이스 ──

  Scenario: 인증정보 누락 계좌 생성 시 422 에러
    # PR #850 이후 credentials 필수 — 누락 시 422 반환
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-cred-acct-02      |
      | name                | 인증정보 없는 계좌   |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | virtual              |
      | broker_type         | test                 |
    Then 응답 상태는 422
