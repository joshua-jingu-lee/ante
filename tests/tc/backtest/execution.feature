Feature: 백테스트 실행
  전략의 과거 데이터 기반 시뮬레이션 실행과 결과 검증.
  관련 이슈: #1044

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # --- 데이터 확보 확인 ---

  Scenario: 백테스트용 데이터셋 존재 확인
    When GET /api/data/datasets
    Then 응답 상태는 200
    And 응답 body.items 배열 길이는 1 이상이다

  # --- 백테스트 실행 ---

  Scenario: 백테스트 실행 (기본 옵션)
    When 컨테이너에서 실행: ante --format json backtest run strategies/qa_buy_signal.py --start 2025-04-01 --end 2025-12-31
    Then 종료 코드는 0
    And stdout에 "run_id" 가 포함되어 있다
    And stdout JSON의 .run_id 를 {run_id}로 저장한다

  Scenario: 백테스트 실행 (초기 잔고 지정)
    When 컨테이너에서 실행: ante --format json backtest run strategies/qa_buy_signal.py --start 2025-04-01 --end 2025-09-30 --balance 50000000
    Then 종료 코드는 0

  Scenario: 백테스트 실행 (심볼 지정)
    When 컨테이너에서 실행: ante --format json backtest run strategies/qa_buy_signal.py --start 2025-04-01 --end 2025-09-30 --symbols 005930
    Then 종료 코드는 0

  # --- 이력 조회 ---

  Scenario: 백테스트 이력 조회
    When 컨테이너에서 실행: ante --format json backtest history qa_buy_signal
    Then 종료 코드는 0

  # --- 성과 지표 검증 ---

  Scenario: 성과 지표 필드 존재 확인
    When 컨테이너에서 실행: ante --format json backtest run strategies/qa_buy_signal.py --start 2025-04-01 --end 2025-12-31
    Then 종료 코드는 0
    And stdout에 "metrics" 가 포함되어 있다

  # --- 에러 케이스 ---

  Scenario: 존재하지 않는 전략으로 백테스트
    When 컨테이너에서 실행: ante backtest run strategies/nonexistent_strategy.py --start 2025-04-01 --end 2025-12-31
    Then 종료 코드는 2

  Scenario: 시작일이 종료일 이후
    When 컨테이너에서 실행: ante backtest run strategies/qa_buy_signal.py --start 2026-01-01 --end 2025-01-01
    Then 종료 코드는 1
