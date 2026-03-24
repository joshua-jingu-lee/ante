Feature: 데이터셋 관리
  데이터셋 목록 조회, 상세 조회, 삭제를 검증한다.
  관련 이슈: #799 (데이터셋 상세 API)

  Background:
    Given ante-qa 컨테이너가 실행 중이다
    And QA Admin 인증 토큰이 확보되어 있다

  # ── 데이터셋 목록 조회 ──

  Scenario: 데이터셋 목록 조회 (API)
    When GET /api/data/datasets
    Then 응답 상태는 200
    And 응답 body.items 는 null이 아니다

  Scenario: 데이터셋 ID 확보
    When GET /api/data/datasets
    Then 응답 상태는 200
    And 응답 body.items 배열 길이는 1 이상이다
    And 첫 번째 항목의 id 를 {dataset_id}로 저장한다

  # ── 데이터셋 상세 조회 (#799) ──

  Scenario: 데이터셋 상세 조회 (API)
    When GET /api/data/datasets/{dataset_id}
    Then 응답 상태는 200
    And 응답 body.dataset 는 null이 아니다
    And 응답 body.dataset.symbol 은 null이 아니다
    And 응답 body.dataset.timeframe 은 null이 아니다
    And 응답 body.dataset.row_count 는 0보다 크다

  Scenario: 데이터셋 미리보기 포함 확인 (API)
    When GET /api/data/datasets/{dataset_id}
    Then 응답 상태는 200
    And 응답 body.preview 는 null이 아니다
    And 응답 body.preview 배열 길이는 1 이상이다

  Scenario: 데이터셋 상세 — 메타데이터 필드 검증 (API)
    When GET /api/data/datasets/{dataset_id}
    Then 응답 상태는 200
    And 응답 body.dataset.start_date 은 null이 아니다
    And 응답 body.dataset.end_date 은 null이 아니다
    And 응답 body.dataset.data_type 은 null이 아니다

  # ── 저장 용량 ──

  Scenario: 저장 용량 현황 조회 (API)
    When GET /api/data/storage
    Then 응답 상태는 200

  # ── 에러 케이스 ──

  Scenario: 존재하지 않는 데이터셋 상세 조회 (API)
    When GET /api/data/datasets/nonexistent__99d
    Then 응답 상태는 404

  # ── 심볼 필터 ──

  Scenario: 심볼 필터 조회 (API)
    When GET /api/data/datasets?symbol=000001
    Then 응답 상태는 200
    And 응답 body.items 는 null이 아니다
