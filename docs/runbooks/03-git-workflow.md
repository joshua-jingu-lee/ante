# 03. Git 워크플로우

> 커밋 컨벤션, PR 규칙을 정의한다. 브랜치 전략과 Worktree 운용은 [01-development-process.md §3](01-development-process.md#3-작업-실행-체계) 참조.

---

## 1. 브랜치 네이밍 규칙

```
feat/#42-symbol-validation
fix/#57-treasury-rounding
refactor/#63-broker-interface
docs/#70-api-reference
epic/#300-datafeed              ← 에픽 통합 브랜치
```

## 2. 커밋 컨벤션

[Conventional Commits](https://www.conventionalcommits.org/) 기반:

```
<type>(<scope>): <subject>

<body>        # 선택
<footer>      # 선택
```

### Type과 버전 범프

[python-semantic-release](https://python-semantic-release.readthedocs.io/)가 커밋 메시지를 분석하여 자동으로 버전을 범프한다.
설정: `pyproject.toml`의 `[tool.semantic_release]` 섹션.

| Type | 설명 | 버전 범프 |
|------|------|-----------|
| `feat` | 새 기능 추가 | **minor** (0.1.0 → 0.2.0) |
| `fix` | 버그 수정 | **patch** (0.1.0 → 0.1.1) |
| `perf` | 성능 개선 | **patch** (0.1.0 → 0.1.1) |
| `refactor` | 리팩토링 (기능 변경 없음) | 없음 |
| `test` | 테스트 추가/수정 | 없음 |
| `docs` | 문서 변경 | 없음 |
| `style` | 포맷팅, 세미콜론 등 | 없음 |
| `build` | 빌드 시스템, 의존성 변경 | 없음 |
| `ci` | CI/CD 설정 변경 | 없음 |
| `chore` | 기타 잡무 | 없음 |

### Breaking Change (메이저 버전 범프)

호환성이 깨지는 변경은 메이저 버전을 올린다 (0.x → 1.0.0):

```
feat!: remove legacy broker adapter

BREAKING CHANGE: BrokerAdapter 인터페이스의 execute_order() 시그니처가 변경되었습니다.
기존 어댑터는 새 인터페이스에 맞게 수정이 필요합니다.
```

- `feat!:` 또는 `fix!:` — 타입 뒤에 `!`를 붙이거나
- 커밋 body/footer에 `BREAKING CHANGE:` 라인을 포함

### Scope (모듈명)

`eventbus`, `config`, `bot`, `strategy`, `rule`, `treasury`, `broker`, `gateway`, `data`, `feed`, `backtest`, `report`, `notification`, `web`, `cli`

### 예시

```
feat(eventbus): add EventBus with publish/subscribe support
fix(broker): handle KIS API timeout on order execution
perf(data): optimize Parquet read with column pruning
test(bot): add unit tests for BotManager lifecycle
refactor(treasury): extract allocation logic to separate method
docs(specs): update strategy interface specification
ci: add semantic-release workflow
chore: add pytest configuration to pyproject.toml
```

## 3. PR 규칙

### PR 생성 시

- **제목**: 커밋 컨벤션과 동일한 형식 (70자 이내)
- **본문**: Summary (변경 사항) + Test Plan (검증 방법)
- **라벨**: `core`, `web`, `cli`, `docs`, `fix` 중 해당 항목
- **base 브랜치**: 에픽 하위 이슈는 에픽 브랜치, 그 외는 main

### PR 머지 조건

1. `@code-reviewer` APPROVE (체크리스트 A~F 전체 통과)
2. CI 파이프라인 통과 (린트 + 테스트)
3. 충돌 없음
4. squash merge로 머지

### PR 크기 가이드

- 모듈 1개 단위로 PR 생성 (너무 크지 않게)
- 300줄 이하 권장, 500줄 초과 시 분할 고려
- 테스트 코드는 줄 수 제한에서 제외
