# 경량 계획 스킬

> 구현을 시작하기 전에 이슈를 작은 작업 단위로 안전하게 쪼개는 스킬이다.
> 별도 `docs/plans/` 문서를 만들지 않고, 이슈 코멘트·작업 프롬프트·PR 본문에 남길 정도의 가벼운 계획만 만든다.

## 언제 사용하나

- `/implement-issue` 시작 직후
- 1개 이상 모듈을 건드리는 이슈
- 캐시, 연결, 생성 산출물, API 계약, 설정 변경이 포함된 이슈
- "무엇을 먼저 고쳐야 하는가"가 바로 떠오르지 않는 이슈

작고 국소적인 수정이라면 머릿속 계획만으로 충분할 수 있다. 그 외에는 이 스킬을 기본으로 사용한다.

## 출력 형식

계획은 아래 다섯 항목만 유지한다.

### 1. File Map

- 수정할 파일
- 반드시 읽을 호출자 / 소비자
- 생성 산출물 / 문서 동기화 대상

### 2. Task Breakdown

- 3~7개 작업으로 쪼갠다
- 각 작업은 한 번의 짧은 검증으로 끝낼 수 있어야 한다
- 가능한 한 `테스트 추가 → 최소 구현 → 소비자 반영 → 생성물 동기화` 순서를 선호한다

### 3. Risk Flags

아래에서 해당 항목만 적는다.

- `lifecycle`
- `contract-drift`
- `generated-artifact-sync`
- `mutable-config`
- `health-path`
- `multi-consumer`

### 4. Verification Plan

- 반드시 실행할 검증만 적는다
- 실제 실행 가능한 명령으로 남긴다
- 실행할 수 없는 검증은 `inferred`로 따로 표시할 준비를 한다

### 5. Stop Conditions

아래 중 해당되는 중단 조건만 남긴다.

- 같은 `risk class` 반복
- 영향 범위가 계속 확장됨
- failing test를 정의할 수 없음
- 스펙과 구현 요구가 충돌함
- generated artifact/consumer 범위를 확정할 수 없음

## 계획 작성 규칙

1. **작업은 이슈보다 더 잘게 쪼갠다**
   - 이슈는 사용자 가치 단위
   - 계획은 구현/검증 단위

2. **문서 대신 실행 순서를 만든다**
   - 긴 설명보다 작업 순서와 검증 포인트를 남긴다

3. **고위험 변경은 즉시 표시한다**
   - 캐시, 연결, 세션, 설정 변경, endpoint rename, schema drift는 숨기지 않는다

4. **조건부 계획 리뷰 여부를 명시한다**
   - risk flag가 걸리면 `@code-reviewer`가 필요한지 바로 표시한다

## 예시

```markdown
## 경량 계획
- File Map:
  - modify: `src/ante/account/service.py`
  - inspect: `src/ante/gateway/gateway.py`, `src/ante/broker/kis.py`
  - test: `tests/unit/test_account.py`
  - generated: `frontend/src/types/api.generated.ts`

- Task Breakdown:
  1. failing test 추가
  2. 최소 구현
  3. 소비자 경로 반영
  4. generated artifact 동기화
  5. 로컬 검증

- Risk Flags:
  - lifecycle
  - contract-drift

- Verification Plan:
  - `pytest tests/unit/test_account.py -q`
  - `ruff check src/ante/account tests/unit`

- Stop Conditions:
  - 같은 `risk class` 반복
  - generated artifact 영향 범위 확장
```

## 조건부 계획 리뷰 연결

아래 신호가 있으면 계획만 만든 뒤 바로 구현하지 말고 `@code-reviewer`에 넘긴다.

- 캐시, 세션, 연결, long-lived adapter, mutable config 변경
- endpoint / schema / field / CLI rename
- OpenAPI, 생성 타입, 생성 문서 drift 가능성
- 둘 이상의 모듈과 소비자 경로 동시 영향
- 운영 health / readiness / background task 연결
