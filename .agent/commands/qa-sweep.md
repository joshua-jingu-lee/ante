전체 TC를 순차적으로 실행하는 QA 전수 검사 모드.

각 카테고리의 TC 실행은 `/qa-test`의 작업 흐름(QA 에이전트 위임)을 따른다. 이 문서는 카테고리 선택 로직과 전수 검사 고유 규칙만 정의한다.

## 인자

$ARGUMENTS — 옵션 (생략 가능)
- `--fix`: FAIL 발견 시 자동 수정 시도 (각 `/qa-test`에 전달)
- `--skip-on-fail`: 한 카테고리 FAIL 시 다음 카테고리로 이동 (기본: 계속 진행)

## 에이전트 역할 분담

| 단계 | 담당 | 에이전트 |
|------|------|----------|
| TC 실행 | QA 에이전트 | `@qa-engineer` (카테고리별 `/qa-test` 위임) |
| 버그 수정 (--fix) | 개발 에이전트 | `@backend-dev` 또는 `@frontend-dev` (`/implement-issue` 위임) |
| 인프라 장애 복구 | DevOps 에이전트 | `@devops` (Docker 빌드/기동 실패 시) |

## QA 전수 검사 규칙

1. **카테고리 단위 완결**: `/qa-test {카테고리}`로 실행 → 완료 후 다음 카테고리로 이동
2. **실패 시 계속 진행**: 한 카테고리에서 FAIL이 나와도 나머지 카테고리는 계속 실행한다. 단, ERROR(컨테이너 다운 등)는 중단 후 복구 시도.
3. **컨테이너 재시작**: 카테고리 전환 시 필요하면 컨테이너를 재시작하여 DB를 초기 상태로 돌린다.
4. **변경 금지**: TC 파일(.feature)은 수정하지 않는다. --fix 모드에서도 소스 코드만 수정.

## 사전 조건

```
1. Docker 컨테이너 기동
   docker compose -f docker-compose.qa.yml up -d --wait
   헬스체크 통과 확인: curl -s http://localhost:8000/api/system/health

2. .feature 파일 존재 확인
   tests/tc/ 하위에 .feature 파일이 최소 1개 이상 존재해야 한다.
   없으면 "TC 파일이 없습니다. tests/tc/ 디렉토리를 확인하세요." 보고 후 종료.
```

## 작업 흐름

```
1. 카테고리 목록 수집
   tests/tc/ 하위 디렉토리를 탐색하여 .feature 파일이 있는 카테고리를 수집한다.

   실행 순서 (의존성 고려):
   a. scenario   — 설치/초기화 (init, install)
   b. member     — 인증 기반, 다른 모듈의 전제
   c. account    — 최상위 엔티티
   d. treasury   — 계좌 자금 관리
   e. strategy   — 전략 등록
   f. bot        — 봇 생성 (계좌 + 전략 + 자금 필요)
   g. config     — 동적 설정
   h. trade      — 거래 조회

   존재하지 않는 카테고리는 건너뛴다.

2. 카테고리별 실행
   각 카테고리에 대해:

   a. 컨테이너 상태 확인 (다운되었으면 재시작)
      docker ps --filter name=ante-qa --format '{{.Status}}'
      필요 시: docker compose -f docker-compose.qa.yml restart
      헬스체크 대기 (최대 30초)

   b. /qa-test {카테고리} [--fix] 실행
      → @qa-engineer 에이전트가 TC를 실행하고 리포트를 반환

   c. 결과 수집 — PASS/FAIL/ERROR/SKIP 카운트 기록

   d. 다음 카테고리로 이동

3. 전체 리포트 출력
```

## 전체 리포트 형식

모든 카테고리 실행 완료 후 다음 형식으로 최종 리포트를 출력한다:

```
## QA 전수 검사 리포트
- 실행 시각: {시작 시각} ~ {종료 시각}
- 소요 시간: {총 소요}

### 카테고리별 결과

| 카테고리 | Feature | PASS | FAIL | ERROR | SKIP | 결과 |
|---------|---------|------|------|-------|------|------|
| member  | 2       | 14   | 0    | 0     | 0    | ✅   |
| account | 3       | 18   | 2    | 0     | 0    | ❌   |
| treasury| 2       | 10   | 0    | 0     | 0    | ✅   |
| ...     |         |      |      |       |      |      |

### 전체 요약
- 총 Scenario: {총수}
- PASS: {수} ({비율}%)
- FAIL: {수}
- ERROR: {수}
- SKIP: {수}

### FAIL 목록
1. [account/crud.feature] 존재하지 않는 계좌 조회 → #이슈번호
2. [account/lifecycle.feature] 정지된 계좌 봇 생성 거부 → #이슈번호

### 등록된 버그 이슈
- #700 QA: account/crud — 존재하지 않는 계좌 조회 실패
- #701 QA: account/lifecycle — 정지된 계좌 봇 생성 거부 실패
```

## 에러 복구

| 상황 | 대응 |
|------|------|
| 컨테이너 다운 | `docker compose restart` 후 현재 카테고리 재실행 (1회) |
| 빌드/기동 실패 | `@devops`에 해결 위임 → 수정 후 재빌드·기동하여 속행. 동일 원인 2회 연속 실패 시 중단 |
| 인증 토큰 만료 | 재로그인 후 계속 |
| curl 타임아웃 | 해당 Scenario ERROR 처리, 다음으로 진행 |
| 3회 연속 ERROR | 전수 검사 중단, 현재까지 결과 리포트 후 사용자에게 보고 |

## 컨테이너 재시작 정책

카테고리 간 데이터 격리를 위해 다음 시점에 컨테이너를 재시작한다:

```
- 이전 카테고리에서 ERROR가 발생한 경우
- 그 외에는 재시작하지 않고 누적 실행
```

## /autopilot 통합

autopilot에서 구현 이슈 완료 후 자동으로 `/qa-sweep --fix`를 실행한다:

```
autopilot 루프:
  Phase 1. 오픈 이슈 순회 → /implement-issue → 자동 머지
  Phase 2. /qa-sweep --fix → FAIL 시 버그 이슈 등록 → Phase 1 재진입
  반복: 새 버그 이슈가 0건이 될 때까지 (최대 5라운드)
```
