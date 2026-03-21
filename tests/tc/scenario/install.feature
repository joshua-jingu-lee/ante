Feature: 대화형 설치 프로세스 (ante init)
  깨끗한 환경에서 ante init 대화형 설치가 정상 동작하는지 검증한다.
  기존 QA 컨테이너(ante-qa)와 독립된 일회용 컨테이너를 사용한다.

  Background:
    Given ante-qa 이미지가 빌드되어 있다

  # ── 정상 설치 흐름 ───────────────────────────────────

  Scenario: 1. 대화형 초기 설정 실행
    # stdin: member_id / name / password / password확인 / 계좌등록(n) / 텔레그램(n) / data.go.kr(n) / DART(n)
    When 별도 컨테이너에서 실행: printf 'qa-admin\nQA Admin\nqa-password\nqa-password\nn\nn\nn\n' | ante init --dir /tmp/test-init
    Then 종료 코드는 0
    And stdout에 "초기 설정 완료" 가 포함되어 있다
    And stdout에 "qa-admin" 가 포함되어 있다

  Scenario: 2. 설정 파일 생성 확인
    When 별도 컨테이너에서 실행: ls /tmp/test-init/system.toml /tmp/test-init/secrets.env
    Then 종료 코드는 0

  Scenario: 3. DB 파일 생성 확인
    When 별도 컨테이너에서 실행: ls /tmp/test-init/db/ante.db
    Then 종료 코드는 0

  Scenario: 4. 토큰 발급 확인
    When 별도 컨테이너에서 실행: printf 'qa-admin\nQA Admin\nqa-password\nqa-password\nn\nn\nn\n' | ante init --dir /tmp/test-init2
    Then 종료 코드는 0
    And stdout에 "토큰" 가 포함되어 있다
    And stdout에 "Recovery Key" 가 포함되어 있다

  # ── 멱등성 검증 ──────────────────────────────────────

  Scenario: 5. 이미 설치된 환경에서 재실행 시 거부
    When 별도 컨테이너에서 실행: printf '\n' | ante init --dir /tmp/test-init
    Then 종료 코드는 0
    And stdout에 "이미 존재합니다" 가 포함되어 있다

  # ── 계좌 자동 생성 검증 ──────────────────────────────

  Scenario: 6. 테스트 계좌 자동 생성 확인
    When 별도 컨테이너에서 실행: sqlite3 /tmp/test-init/db/ante.db "SELECT account_id, broker_type FROM accounts"
    Then 종료 코드는 0
    And stdout에 "test" 가 포함되어 있다
