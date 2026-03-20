Feature: 계좌 인증정보 관리
  계좌의 인증정보(credentials) 설정, 조회, 미설정 시 봇 시작 에러를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

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
      | broker_type         | mock                |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {account_id}로 저장한다

  # ── 정상 흐름: 인증정보 설정 및 조회 ──

  Scenario: 인증정보 설정 (CLI)
    When 컨테이너에서 실행: ante account set-credentials {account_id} --app-key test-app-key --app-secret test-app-secret --format json
    Then 종료 코드는 0

  Scenario: 인증정보 조회 (CLI)
    When 컨테이너에서 실행: ante account credentials {account_id} --format json
    Then 종료 코드는 0
    And stdout JSON의 .app_key 는 null이 아니다

  Scenario: 인증정보 설정 후 봇 생성 및 시작 가능
    When POST /api/bots 요청:
      | field      | value              |
      | account_id | {account_id}       |
      | name       | 인증정보 있는 봇   |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {bot_id}로 저장한다

  # ── 에러 케이스 ──

  Scenario: 인증정보 없는 계좌로 봇 시작 시 에러
    # 인증정보 없는 새 계좌 생성
    When POST /api/accounts 요청:
      | field               | value                |
      | account_id          | qa-cred-acct-02      |
      | name                | 인증정보 없는 계좌   |
      | exchange            | KRX                  |
      | currency            | KRW                  |
      | timezone            | Asia/Seoul           |
      | trading_hours_start | 09:00                |
      | trading_hours_end   | 15:30                |
      | trading_mode        | live                 |
      | broker_type         | kis                  |
    Then 응답 상태는 201
    And 응답 body.account.account_id 를 {no_cred_account_id}로 저장한다
    # 봇 생성
    When POST /api/bots 요청:
      | field      | value                 |
      | account_id | {no_cred_account_id}  |
      | name       | 인증정보 없는 봇      |
    Then 응답 상태는 201
    And 응답 body.bot.bot_id 를 {no_cred_bot_id}로 저장한다
    # 봇 시작 시도 → 인증정보 미설정 에러
    When POST /api/bots/{no_cred_bot_id}/start
    Then 응답 상태는 422
