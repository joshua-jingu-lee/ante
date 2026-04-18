# 리뷰 수용 스킬

> branch review나 PR approval에서 finding을 받았을 때, 곧바로 코드를 고치지 않고 먼저 사실과 영향 범위를 정리하는 스킬이다.

## 언제 사용하나

- `codex-branch-review` 실패 직후
- `claude-pr-approve` 또는 `codex-pr-approve`가 `content` FAIL을 반환했을 때
- 자동 재수정 전에 finding을 이해하고 수정 순서를 다시 잡아야 할 때

`quota`, `script_error`, `auth_error`, `infra_error`는 이 스킬의 대상이 아니다. 그런 경우는 구현이 아니라 인프라 복구가 먼저다.

## 기본 절차

### 1. 실패 유형을 먼저 분류한다

- `content`: 실제 blocking finding
- `quota` / `script_error` / `auth_error` / `infra_error`: 코드 수정 금지, 워커 복구 우선

`content`가 아니면 구현 루프를 시작하지 않는다.

### 2. finding을 재서술한다

각 finding마다 다음 네 줄만 남긴다.

- **무엇이 깨졌는가**
- **왜 문제인가**
- **어떤 경로가 영향받는가**
- **어떤 테스트가 이를 증명할 수 있는가**

### 3. 사실과 추론을 분리한다

- 리뷰가 직접 증명한 사실
- 아직 코드 독해로만 추론한 부분

이 둘을 섞지 않는다.

### 4. 영향 범위를 다시 그린다

아래를 빠르게 다시 확인한다.

- producer
- consumer
- cache / factory / reconnect path
- generated artifact
- runtime invariant

### 5. 수정 전략을 고른다

아래 중 하나를 고른다.

- `patch-now`: 현재 브랜치에서 최소 수정
- `add-test-first`: failing test를 먼저 추가
- `invoke-code-reviewer`: 계획/구조 재검토 필요
- `split-issue`: 현재 PR 범위를 넘는다
- `invoke-human`: 스펙/정책 충돌

### 6. 수정 후 결과를 다시 요약한다

- 어떤 finding을 해소했는지
- 어떤 검증을 실행했는지
- 무엇이 아직 추론 상태인지

## 중단 규칙

아래 중 하나면 더 깊게 patch하지 말고 escalation 한다.

- 같은 `risk class`가 2회 반복
- finding을 한 문장으로 재서술할 수 없음
- 영향 범위가 새 모듈로 계속 확장됨
- failing test를 정의할 수 없음
- 스펙과 리뷰 finding이 충돌함

## 짧은 출력 형식

```markdown
## 리뷰 수용 메모
- Finding:
  - 브로커 캐시 무효화 후 재연결 누락
- Facts:
  - 설정 변경 후 stale broker 제거는 수행됨
  - 새 broker connect 보장은 없음
- Inferred:
  - 첫 조회/주문 실패 가능성
- Action:
  - add-test-first
  - invoke-code-reviewer
```

## 원칙

1. 리뷰를 그대로 코드 diff로 번역하지 않는다
2. 영향 범위를 다시 그린 뒤 수정한다
3. 실행 검증과 추론을 구분한다
4. 반복되는 구조 리스크는 사람이나 `@code-reviewer`로 넘긴다
