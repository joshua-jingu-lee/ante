Feature: 데이터 피드 및 저장 관리
  데이터 저장 현황, 스키마, Feed 상태를 검증한다.

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # --- 저장 용량 ---

  Scenario: 저장 용량 현황 조회 (API)
    When GET /api/data/storage
    Then 응답 상태는 200
    And 응답 body.total_bytes 는 null이 아니다

  # --- 데이터 스키마 ---

  Scenario: OHLCV 스키마 조회
    When GET /api/data/schema?data_type=ohlcv
    Then 응답 상태는 200

  Scenario: Fundamental 스키마 조회
    When GET /api/data/schema?data_type=fundamental
    Then 응답 상태는 200

  # --- Feed 상태 ---

  Scenario: Feed 파이프라인 상태 조회
    When GET /api/data/feed-status
    Then 응답 상태는 200
    And 응답 body.initialized 는 null이 아니다

  # --- 에러 케이스 ---

  Scenario: 존재하지 않는 데이터셋 삭제
    When DELETE /api/data/datasets/nonexistent__1d
    Then 응답 상태는 404

  Scenario: 잘못된 dataset_id 형식 조회
    When GET /api/data/datasets/invalid-format
    Then 응답 상태는 404
