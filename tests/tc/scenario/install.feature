Feature: 비대화형 설치 프로세스 (ante init)
  깨끗한 환경에서 ante init 비대화형 설치가 정상 동작하는지 검증한다.
  기존 QA 컨테이너(ante-qa)와 독립된 일회용 컨테이너를 사용한다.
  재설계 2026-04 (issue #1125): 대화형 프롬프트 전면 제거, 플래그 기반 동작.

  Background:
    Given ante-qa 이미지가 빌드되어 있다

  # ── 정상 설치 흐름 ───────────────────────────────────

  Scenario: 1. 기본 플래그로 비대화형 초기 설정 실행
    When 별도 컨테이너에서 실행: ante init --dir /tmp/test-init
    Then 종료 코드는 0
    And stdout에 "완료" 가 포함되어 있다
    And stdout에 "owner" 가 포함되어 있다
    And stdout에 "패스워드" 가 포함되어 있다

  Scenario: 2. 설정 파일 생성 확인
    When 별도 컨테이너에서 실행: ls /tmp/test-init/system.toml /tmp/test-init/secrets.env
    Then 종료 코드는 0

  Scenario: 3. DB 파일 생성 확인
    When 별도 컨테이너에서 실행: ls /tmp/test-init/db/ante.db
    Then 종료 코드는 0

  Scenario: 4. secrets.env 파일 권한이 0600
    When 별도 컨테이너에서 실행: stat -c '%a' /tmp/test-init/secrets.env
    Then 종료 코드는 0
    And stdout에 "600" 가 포함되어 있다

  Scenario: 5. 토큰·Recovery Key·패스워드 발급 확인
    When 별도 컨테이너에서 실행: ante init --dir /tmp/test-init2
    Then 종료 코드는 0
    And stdout에 "토큰" 가 포함되어 있다
    And stdout에 "Recovery Key" 가 포함되어 있다
    And stdout에 "패스워드" 가 포함되어 있다

  # ── 플래그로 정체성 지정 ─────────────────────────────

  Scenario: 6. --member-id / --name 플래그 반영
    When 별도 컨테이너에서 실행: ante init --dir /tmp/test-init3 --member-id alice --name Alice
    Then 종료 코드는 0
    And stdout에 "alice" 가 포함되어 있다
    And stdout에 "Alice" 가 포함되어 있다

  # ── 멱등성 검증 ──────────────────────────────────────

  Scenario: 7. 이미 설치된 환경에서 재실행 시 거부
    When 별도 컨테이너에서 실행: ante init --dir /tmp/test-init
    Then 종료 코드는 0 아님
    And stdout에 "init이 이미 완료된 상태입니다" 가 포함되어 있다

  # ── 제거된 기능 검증 ─────────────────────────────────

  Scenario: 8. 제거된 --seed 플래그 거부
    When 별도 컨테이너에서 실행: ante init --dir /tmp/test-init4 --seed
    Then 종료 코드는 0 아님

  Scenario: 9. 제거된 ante member bootstrap 커맨드 부재
    When 별도 컨테이너에서 실행: ante member bootstrap --help
    Then 종료 코드는 0 아님

  # ── 테스트 계좌 자동 생성 검증 ──────────────────────

  Scenario: 10. default test account 자동 생성 확인
    When 별도 컨테이너에서 실행: sqlite3 /tmp/test-init/db/ante.db "SELECT account_id, broker_type FROM accounts"
    Then 종료 코드는 0
    And stdout에 "test" 가 포함되어 있다
