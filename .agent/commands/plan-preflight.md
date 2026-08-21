GitHub 이슈 본문을 구현 가능한 실행계획으로 정비하고, Plan Review 피드백까지 반영해 Plan Preflight를 완료한다.

GitHub 조회/코멘트/이슈 본문 수정 절차는 `.agent/skills/github-ops.md`를 따르고, 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따른다.

## 인자

$ARGUMENTS — GitHub 이슈 번호와 옵션
- `#{번호}` 또는 `{번호}`: Plan Preflight 대상 이슈
- `--refresh`: 이미 `plan-preflight:done`인 이슈라도 이슈 본문/스펙/선행 조건 최신성을 다시 확인하고 필요 시 재작성
- `--dry-run`: 이슈 본문과 라벨을 수정하지 않고 필요한 변경 요약만 보고

## 목적

`/plan-preflight`는 구현 착수 전 이슈 본문을 canonical implementation plan으로 만드는 커맨드다.
계획 작성에는 `superpowers:writing-plans` 원칙을 적용한다. 대화 중 `superpower:write-plan`이라고 부르는 경우도 같은 계획 작성 원칙을 뜻한다.
이 커맨드는 코드 수정, 브랜치 생성, PR 생성을 하지 않는다.
이슈 범위가 너무 크거나 여러 invariant/consumer/계약을 한 번에 건드리면 이 커맨드는 구현계획을 확정하지 않고 `split-issue`로 보류한다. 이때 `/plan-preflight`는 하위 이슈를 직접 만들거나 `/autopilot` 실행을 유도하지 않고, 사람이 후속 이슈로 옮길 수 있는 구조화된 split plan만 남긴다.

완료 조건:

- 이슈 본문에 구현계획이 최신 상태로 정리되어 있음
- Plan Review verdict가 `approve-implement` 또는 `narrow-scope`
- Plan Review 피드백이 이슈 본문 구현계획에 반영되어 있음
- `plan-preflight:started` 라벨이 제거되고 `plan-preflight:done` 라벨이 붙어 있음

## 역할 분담

| 단계 | 담당 | 실행 주체 | GitHub 기록 |
|------|------|-----------|-------------|
| 이슈/스펙 분석 | 오케스트레이터 | Claude 메인 세션 | 시작/보류 이슈 코멘트 |
| 이슈 본문 구현계획 작성/정비 | 오케스트레이터 | Claude 메인 세션 | 이슈 본문 + 계획 정비 완료 이슈 코멘트 |
| 계획 검증 (Gate 0) | `@plan-reviewer` (verdict 반환, read-only) | 별도 컨텍스트 서브에이전트 | verdict → 오케스트레이터가 Plan Review 이슈 코멘트 기록 |
| 피드백 반영/라벨 확정 | 오케스트레이터 | Claude 메인 세션 | 이슈 본문 + 라벨 + 완료/보류 이슈 코멘트 |

## 실행 절차

### 1단계: 대상 이슈 확인

1. `gh issue view #{번호}`로 이슈 본문, 라벨, 코멘트, 연결 PR 여부를 확인한다.
2. `needs-triage`, `blocked`, `blocked:review-loop`, `blocked:pr-review-loop` 라벨이 있으면 Plan Preflight를 시작하지 않는다.
3. 선행 의존 이슈가 닫히지 않았으면 `blocked` 판정으로 중단한다.
4. 이미 open PR이 연결되어 있으면 이 커맨드로 본문 계획을 고치지 않고 `/implement-issue` 또는 PR 루프에서 처리한다.

### 2단계: 스펙 경로 판정

1. 관련 `docs/specs/`, `docs/architecture/`, `docs/decisions/` 문서를 읽는다.
2. 이슈가 스펙에 이미 정의된 구현이면 `1B Issue-First Bundled`로 진행한다.
3. 스펙 충돌, SSOT 불명확, 영향 범위 확장이 있으면 `needs-spec-first`로 판정하고 구현계획을 확정하지 않는다.
4. 이슈 본문에 스펙 경로와 기준 문서 링크를 명시한다.

### 3단계: Plan Preflight 시작 라벨

쓰기 모드에서는 Plan Preflight 시작 시 라벨을 정리한다.

```bash
gh issue edit #{번호} --remove-label "plan-preflight:done" || true
gh issue edit #{번호} --add-label "plan-preflight:started"
```

라벨을 정리한 직후 시작 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 시작**
- status: started
- mode: {default | refresh}
- spec-path: {1A Spec-First | 1B Issue-First Bundled | pending}
- next: 이슈 본문 Implementation Plan 작성/정비 후 Plan Review 요청"
```

`--dry-run`이면 라벨을 바꾸지 않고 필요한 라벨 변경만 보고한다.

### 4단계: 이슈 본문 구현계획 작성/정비

이슈 본문에 아래 섹션을 작성하거나 기존 내용을 최신화한다.

```markdown
## Implementation Plan

### Spec Path
- path: `1A Spec-First | 1B Issue-First Bundled`
- SSOT:
  - `docs/specs/...`

### File Map
- 수정 대상:
- 읽어야 할 호출자/소비자:
- 생성 산출물:

### Tasks
- [ ] ...

### Verification
- failing check:
- passing check:
- commands:
- 집행 규칙 블록: 회귀 락이 있으면 아래 「회귀 락 설계 규칙」 §집행 규칙을 이 자리에 그대로 싣는다

### Risk Flags
- `lifecycle | contract-drift | generated-artifact-sync | mutable-config | health-path | multi-consumer | none`

### Stop Conditions
- 스펙 충돌:
- 영향 범위 확장:
- failing check 불명확:

### Non-Goals
- ...

### Plan Review
- reviewer:
- verdict:
- feedback reflected:
- scope decision:
```

작성 원칙:

- `superpowers:writing-plans` 원칙을 Ante 이슈 본문에 맞게 적용한다.
- task는 개발 에이전트가 순서대로 실행할 수 있는 작은 체크박스 단위로 쓴다.
- 테스트 계획은 추상 문장이 아니라 실제 실행 명령 또는 확인 가능한 check로 쓴다.
- `narrow-scope` 가능성이 있으면 제외 범위와 후속 이슈 후보를 본문에 명시한다.
- 추론은 추론으로 표시하고, 스펙/코드에서 확인한 사실과 섞지 않는다.
- 다음 신호 중 하나가 있으면 계획 확정보다 `split-issue` 판정을 우선 검토한다.
  - 서로 다른 invariant가 한 PR 안에 섞인다.
  - API / CLI / schema / generated artifact / runtime lifecycle 중 둘 이상의 계약 축을 동시에 바꾼다.
  - producer와 consumer 경로를 모두 추적해야 하는데 한 계획 안에서 소비자 목록을 닫을 수 없다.
  - 예상 변경이 `40 files` 또는 `+1000 insertions`를 넘을 가능성이 높다.
  - Non-Goals로 둔 파일/경로를 건드리지 않으면 계획을 성립시킬 수 없다.
  - 선행/후속 관계가 있는 하위 작업을 한 이슈 안에서 동시에 구현해야 한다.

#### 회귀 락 설계 규칙

Verification에 넣는 **회귀 락**(grep·diff 기반 기계적 검사)은 계획이 의도한 변경만 통과시키는 게이트다.
락은 세 계층으로 나눠 쓰고, 계층 경계는 아래 기준으로 가른다. 새 유형이 나오면 이 기준으로 소속 계층을 정한다.

- **(a) 작성 규칙 — 패턴 설계**: 무엇을 어떤 스코프로 판정할지의 문제. 정규식, 범위, 비교 대상이 여기 속한다.
- **(b) 집행 규칙 — 셸 하니스**: 그 패턴을 어떤 셸 절차로 실행할지의 문제. 인용, 전달, 산출물 경로가 여기 속한다.
- **(c) 검증 규칙 — 락 자신의 건전성**: 락이 판별력을 갖는지, 락이 덮을 표면 집합이 닫혔는지의 문제.

##### 작성 규칙 (패턴 설계)

- **전역 grep 금지 — 섹션/행 스코프로 좁힌다.** 형제 이슈가 같은 파일에 텍스트를 더하면 전역 카운트·존재 검사는 아무것도 고치지 않아도 통과한다(vacuous pass). `awk '/^## 8\./,/^## 9\./' "$F" | grep …` 형태로 판정 범위를 절 안에 가둔다. awk 범위 연산자는 **양 끝점을 포함**하므로 종료 헤딩 줄이 판정 범위에 섞인다 — 형제 이슈가 `## 9.` 제목에 세는 토큰을 넣으면 §8을 아무것도 고치지 않아도 카운트가 충족된다. 종료 헤딩을 빼려면 배타형 `awk '/^## 8\./{f=1} /^## 9\./{f=0} f' "$F"`를 쓴다.
- **diff base는 `$(git merge-base origin/main HEAD)`를 쓰고 2-dot `origin/main` 비교는 쓰지 않는다.** 형제 이슈가 먼저 머지되면 역방향 hunk가 잡혀 거짓 중단이 난다. `origin/main`은 로컬 remote-tracking ref라 뒤처진 채로 두면 merge-base가 과거 커밋으로 밀려 그 사이 형제 커밋들의 파일까지 이 브랜치 변경으로 잡히고, 정확 파일 수 락이 FAIL해 「구현을 되돌린다」가 헛발동한다(실측: `origin/main`을 한 커밋 뒤로 둔 클론에서 `git diff --name-only "$B"`가 형제 파일까지 열거, `git fetch origin main` 뒤 사라짐). **base를 잡기 전에 `origin/main`을 갱신하는 것은 실행 시점 절차라 집행 규칙이 소유한다.**
- **diff에 경로 필터를 걸지 말고 전체 열거로 비교한다.** `git diff --name-only "$B" | sort` 결과를 정확한 파일 목록과 등가 비교해 집합을 닫는다. **파일 개수 계수(`-eq K`)로 축약하지 않는다** — 기대 파일 하나가 빠지고 예상 밖 파일 하나가 들어오면 개수가 같아 파일 집합이 통째로 바뀌어도 통과한다(실측: 기대 `a.md b.md c.md`와 실제 `a.md b.md sneaky.md`가 둘 다 개수 3이라 `-eq 3`이 양쪽 PASS인데, 같은 두 목록을 아래 변형으로 비교하면 차이 행 `N=2`로 FAIL). 등가를 표현하는 경로는 집행 규칙의 **「생산자 둘 + 비교 결과 계수」 변형**이다 — 기대 목록과 실제 열거를 각각 스냅샷 생산자로 두고 비교 결과의 차이 행을 `-eq 0`으로 받는다. 이 문서가 「정확 파일 수 락」이라 부르는 것도 개수 계수가 아니라 이 집합 등가 판정을 가리킨다. 경로 필터를 쓰는 락이 있다면 무필터 열거 락이 파일 집합을 닫고 있음을 계획에 함께 밝힌다. **이 생산자는 추적되는 파일만 보므로 실행 전 스테이징이 전제이고, 그 절차는 집행 규칙이 소유한다.**
- **값을 하드코딩하지 말고 패턴을 잠근다.** 버전·라인 번호·SHA는 리뷰가 도는 동안 드리프트하는 표면이다. `# v1.14.1` 대신 `grep -E '@[0-9a-f]{40} # v[0-9]+\.[0-9]+\.[0-9]+'`처럼 형태를 잠근다. **ERE 메타문자를 쓰면 `-E`를 붙인다.** bare `grep`은 basic regex라 ERE 문법이 리터럴로 해석돼 매치가 0건이 된다. 위험 문자를 몇 개 외우는 방식으로 판단하지 말고 **「ERE 문법을 쓰면 `-E`」로 닫는다** — 반복(`{n}`·`+`), 선택(`|`), **옵션 접미사(`?`), 그룹핑(`()`)** 이 모두 같은 함정이며(실측: `grep 'foo(bar)?'`는 `foo(bar)`도 `foobar`도 잡지 못해 0건, `grep -E`로 바꾸면 둘 다 잡는다), 그룹핑·선택 접미사는 이런 락에서 특히 흔하다. 매치 0건이 되면 긍정형 락은 false FAIL, 부정형 락은 조용한 vacuous PASS가 된다. 이 불릿은 **정규식을 쓰기로 정한 뒤**의 규칙이고, 패턴이 리터럴이냐 정규식이냐라는 상위 분기와 그에 따른 계수 매처 선택은 집행 규칙의 정본 형태 절이 정한다.
- **앵커는 파일 안에서 고유한 접두사를 쓴다.** `head -1`로 첫 매치를 집는 방식은 쓰지 않는다. 매치가 늘어나면 조용히 다른 지점을 가리킨다.
- **awk 범위 앵커는 시작 유일성과 종료 존재를 baseline에서 확인한다.** 시작 앵커가 두 번 나오면 범위가 재개방되고, 종료 앵커가 없으면 EOF까지 폭주한다. 시작 앵커 1회는 `grep -cE -e '^앵커'`를 **생산자로 삼아** 그 계수 산출 자체를 정본 형태로 판정한다. **이때 판정 패턴은 앵커된 `-cE`로 쓴다(`^1$`).** 생산자 산출이 맨 숫자라 집행 규칙의 「리터럴이면 `-cF`」를 그대로 적용해 `-cF -e '1'`로 쓰면 부분 문자열이 매치된다(실측: 앵커가 10회 있어 생산자가 `10`을 낼 때 `grep -cF -e '1'`은 `N=1`이라 `-ge 1` 판정이 범위 재개방을 승인하고, `grep -cE -e '^1$'`는 `N=0`으로 올바르게 FAIL한다). 여기서 잠그는 것은 리터럴 토큰이 아니라 **계수값의 형태**라 정규식이 맞고, 계수값을 내는 다른 생산자도 같다. **범위 길이 상한은 `wc -l`을 생산자로 쓸 수 없다** — `wc -l` 산출은 범위가 몇 줄이든 한 줄이라 계수가 언제나 1이 된다(실측: `S=$(seq 1 5000 | wc -l)` 뒤 `N=$(printf '%s\n' "$S" | grep -cE -e '' || true)`가 `N=1`이라 `test "$N" -lt 200`이 실제 길이 5000에도 PASS). **생산자를 추출된 범위 자체로 두고 계수를 `grep -cE -e ''`로 세야** 같은 판정이 동작한다(실측: 같은 상한 락이 5000줄 범위에서 FAIL, 7줄 범위에서 PASS). **이 계수는 범위가 빈 줄로 끝나면 실제 줄 수보다 작다 — 이 붕괴는 `grep -cE -e ''`의 성질이 아니라 명령 치환의 성질이라, 변수에 담은 산출을 세는 모든 계수 형태(`grep -cE -e ''`·`wc -l` 등)가 똑같이 어긋난다.** 명령 치환이 후행 개행을 전부 버리고 `printf '%s\n'`이 하나만 되붙이기 때문이다(실측: `printf 'a\n\n'`이 `wc -l`로 2, 같은 입력을 변수에 담으면 `grep -cE -e ''`·`wc -l` 둘 다 1). 상한(`-lt`) 판정에는 무해하지만 **정확 길이(`-eq N`) 락은 그만큼 어긋나므로**, 길이를 정확히 잠글 계획이면 이 붕괴를 보정해 적는다.
- **토큰 존재가 아니라 「그 문장이 주장하는 바」를 검사한다.** 소제목 개수·항목 수 같은 구조 assertion을 함께 걸어 내용 없는 스텁이 통과하지 못하게 한다.
- **추가 방향 lock을 최소 1개 둔다.** 삭제·불변만 잠그면 아무것도 쓰지 않은 구현이 통과한다. 새 산문이 실제로 들어왔음을 판정하는 락이 하나는 있어야 한다.
- **필터 체인은 검사 단위와 같은 입도로 분절한다.** 여러 판정을 파이프 하나에 몰면 어느 조건이 깨졌는지 알 수 없고, 과광범위 매치도 드러나지 않는다.
- **보조 — `git diff --exit-code -- <경로>`는 조건부 가드다.** 이 비교는 **워크트리 ↔ 인덱스**라 regenerate 순서와 스테이징 시점에 **모두** 의존한다. regenerate 없이 실행하면 양쪽이 같아 통과하고, regenerate한 뒤라도 그 결과를 스테이징하면 다시 통과한다(실측: `git add <경로>` 직후 같은 명령이 rc=0). 이 가드를 락으로 쓰려면 그 두 조건이 실제로 성립하는지를 계획이 직접 확인하고, 판정은 집행 규칙의 정본 형태로 감싼다. **집행 규칙이 두는 `git add -A` 전제와는 동시에 성립하지 않는다** — 전부 스테이징하면 인덱스가 워크트리와 같아져 이 비교가 경로와 무관하게 늘 rc=0이므로, 같은 스크립트 안에서는 이 가드가 생성 산출물 드리프트에 대한 vacuous PASS가 된다(실측: 드리프트가 남은 상태에서 `git add -A` 전 rc=1, 후 rc=0). 이 축과 저장소 기존 처방의 정합은 **#2472**가 소유한다.
- **보조 — `git diff --name-only …`만 두면 락이 아니라 육안 확인이다.** 목록을 출력할 뿐 판정하지 않으므로 그 출력을 집행 규칙 **정본 형태의 생산자**로 넣어 판정한다. 별도 판정 idiom을 만들지 않는다 — 정본 형태의 liveness 줄이 경로·base 오기로 목록이 통째로 비었을 때의 vacuous PASS까지 함께 닫는다.
- **보조 — 섹션 불변은 hunk 파싱이 아니라 두 스냅샷 직접 비교로 잠근다.** 라인 번호가 밀려도 안전하다. **종료 앵커는 다음 헤딩으로 두고 위의 배타형과 결합한다.** **구체 셸 형태는 여기서 정하지 않는다 — 스냅샷을 뽑는 명령을 생산자로, 비교 결과 계수를 판정으로 삼아 계획이 집행 규칙의 정본 형태로 직접 쓴다.** **양쪽 앵커가 다 없으면 두 스냅샷이 모두 비어 비교가 0건이 되므로**(실측: 존재하지 않는 앵커로 양쪽을 뽑으면 `diff`가 rc=0) **두 스냅샷 각각이 비어 있지 않음을 먼저 확인**한다 — 정본 형태의 liveness를 비교 결과가 아니라 **입력 스냅샷 양쪽**에 거는 것이 이 경우다. 이 비교가 잠그는 것은 **바이트 동일성의 유계 근사**다 — 명령 치환이 후행 개행을 전부 버리고 재출력이 하나만 되붙이므로 **섹션 끝 빈 줄이 늘거나 줄어든 변경은 동일로 판정된다**(실측: 후행 빈 줄만 다른 두 입력이 diff 0건인데 `cmp`는 rc=1). 이 근사로 충분한지는 계획이 판단해 적는다.

  **종료 앵커를 `0`으로 두는 `awk '/^## 9\./,0'` 형태는 §9가 파일의 마지막 섹션일 때만 쓴다** — awk의 `0`은 어떤 행에도 매치하지 않아 범위가 EOF까지 폭주한다(실측: `printf '## 9. A\nbody9\n## 10. B\nbody10\n' | awk '/^## 9\./,0'`은 `## 10. B`와 `body10`까지 출력한다). §9 뒤에 다른 섹션이 있으면 이 락이 그 섹션들까지 함께 동결하므로, 계획이 §10 변경을 지시했는데 「§9 불변」 락이 그 구현을 거부하는 양방향 자기모순이 된다. `,0`을 유지하려면 「§9가 마지막 섹션」이라는 전제를 계획에 적고 그 전제 자체를 락으로 확인한다.
- **보조 — 주석/문서 전용 변경은 구조 동일성으로 근사한다.** `yaml.safe_load` 결과 비교는 주석을 버리지만 **주석만 버리는 것이 아니다** — 매핑 키 순서, 인용 스타일, 들여쓰기·줄바꿈 같은 포매팅도 함께 버린다. 따라서 「구조 동일」은 「주석만 변경」의 **유계 근사**이고, 키 순서를 바꾼 변경이나 인용 스타일만 바꾼 변경은 이 비교를 「주석 전용」으로 통과한다. 이 근사로 충분한지는 계획이 판단해 적고, 그 축까지 잠가야 하면 원문 텍스트 락을 따로 둔다.

##### 집행 규칙 (셸 하니스)

- **락 명령은 이슈 본문 원문을 바이트 단위로 추출해 파일로 실행한다.** 셸 명령줄에 옮겨 적으면 인용이 깨지고, 실제로 실행된 것이 계획에 적힌 것과 달라진다.
- **락 스크립트는 `bash <파일>`로 실행한다.** 프로세스 치환·배열 같은 bash 전용 문법이 쓰이므로 `sh`로 돌리면 문법 오류가 나고, 느슨한 하니스에서는 그 오류가 하니스 실패가 아니라 락 실패로 읽힌다. `#!/usr/bin/env bash` shebang은 **보조**다 — 하니스가 인터프리터를 명시해 호출하면 shebang은 읽히지도 않으므로 그것만으로는 이 함정을 막지 못한다. 스크립트 첫머리에 `set -euo pipefail`도 함께 둔다 — `-u`가 base 커밋 변수 같은 미설정 참조를 즉시 드러낸다(실측: `set -u` 아래 unset `"$B"` 참조가 `B: unbound variable`로 중단).
- **판정은 정본 형태 하나로만 쓴다 — 긍정형과 부정형이 같은 모양이고 `test` 비교 연산자만 다르다.** **계수 grep은 패턴 종류로 매처를 고른다 — 리터럴 문자열을 세면 `grep -cF`, 정규식 형태를 잠그면 `grep -cE`이고, 매처 플래그 없는 `grep -c`(BRE)는 쓰지 않는다.** 패턴은 리터럴이거나 정규식이라 제3의 경우가 없고, 어느 한쪽을 기본값으로 두면 반대편이 조용히 깨진다 — `call foo(bar) here`에서 리터럴 `foo(bar)`를 `-cE`로 세면 0이라 부정형 락이 그 리터럴이 실제로 있는데 vacuous PASS이고(`-cF`는 1), `literal start|stop token`·`start alone`·`stop alone` 3줄에서 리터럴 `start|stop`을 `-cE`로 세면 3이라 출현 1줄을 3으로 부풀린다(`-cF`는 1). 이 문서의 락은 `$(git merge-base …)`·`grep -q`·`a|b` 같은 셸·CLI 리터럴을 일상적으로 세므로 두 방향이 다 밟힌다. 빈 패턴 `''`(모든 행 매치)은 이 이분법의 경계라 **정규식 쪽으로 배정한다** — 작성 규칙의 범위 길이 상한이 쓰는 `-cE -e ''`가 그 용례이고, `-cF -e ''`도 결과가 같아 이 배정이 판정을 가르지는 않는다. 0건 rc=1이라는 계수 grep의 rc 시맨틱은 `-cF`·`-cE`가 같아 아래 `|| true` 근거가 양쪽에 그대로 적용된다. **아래 코드블록은 이 선택을 `-c'<F|E>'` 자리표시자로 노출한다 — 어느 쪽도 기본값으로 굳지 않게 하려는 것이고, 고르지 않은 채 복사하면 `grep`이 `invalid option`으로 죽어 `N`이 비고 판정 줄이 그 자리에서 FAIL한다**(실측: `grep -c'<F|E>'`가 usage를 찍고 rc≠0, 이어서 `test "" -eq 0`이 `integer expression expected`로 FAIL 분기 → exit 1). **패턴은 맨 위치 인자가 아니라 `-e`로 넘긴다** — 정본이 일상적으로 세는 셸·CLI 리터럴은 `--exit-code`처럼 `-`로 시작하는 일이 잦고, 위치 인자로 넘기면 `grep`이 그것을 옵션으로 파싱해 죽는다(실측: `git diff --exit-code -- x` 한 줄을 대상으로 `grep -cF '--exit-code'`가 `unrecognized option`으로 rc≠0 → `N`이 빈 문자열 → 판정 줄이 `integer expression expected`로 FAIL 분기; `-e`를 붙이면 `N=1`로 정상 계수). 이 오파싱은 토큰이 실제로 있는데 없다고 보고하므로 검증 규칙의 「정확 파일 수 락이 FAIL하면 구현을 되돌린다」와 겹치면 **올바른 구현이 되돌려진다.** **자리표시자 미치환과 옵션 오파싱은 둘 다 `FAIL:` 문구로 표면화하지만 락 실패가 아니라 하니스 실패다** — 판정 줄 앞에 `grep: invalid option`·`unrecognized option` 줄이 찍혀 있으면 락이 아니라 하니스를 고친다. **이 문서가 싣는 코드 인용 중 실측 근거는 측정 당시 형태를 그대로 둔다** — 바로 위 `grep -cF '--exit-code'`처럼 결함을 시연하는 형태가 위치 인자로 남아 있는 이유이고, **복사해 쓸 처방 형태는 `-e`를 쓴다.**

  ```bash
  # 긍정형 — 있어야 한다 (PRODUCER = 판정 대상을 뽑는 명령, <F|E> = 리터럴이면 F·정규식이면 E)
  S=$(PRODUCER || true)
  test -n "$S" || { echo "FAIL: 생산자 산출 없음 — 경로·앵커 확인"; exit 1; }
  N=$(printf '%s\n' "$S" | grep -c'<F|E>' -e '<패턴>' || true)
  test "$N" -ge 1 || { echo "FAIL: <무엇이 없다>"; exit 1; }

  # 부정형 — 없어야 한다 (PRODUCER = 판정 대상을 뽑는 명령, <F|E> = 리터럴이면 F·정규식이면 E)
  S=$(PRODUCER || true)
  test -n "$S" || { echo "FAIL: 생산자 산출 없음 — 경로·앵커 확인"; exit 1; }
  N=$(printf '%s\n' "$S" | grep -c'<F|E>' -e '<패턴>' || true)
  test "$N" -eq 0 || { echo "FAIL: <무엇이 있다>"; exit 1; }
  ```

  **생산자 산출을 먼저 변수에 담고 비어 있지 않음을 확인하는 것이 정본 형태의 일부다.** `|| true`는 `grep`의 0건뿐 아니라 **생산자 실패까지 함께 삼킨다.** 파일명 오타·rename·앵커 오기로 생산자가 아무것도 내놓지 못하면 `N=0`이 되고, 부정형은 금지 토큰이 **실제로 있어도** 통과한다(실측: `set -euo pipefail` 아래 `N=$(awk '/^x/' /nonexistent.md 2>/dev/null | grep -cF 'FORBIDDEN' || true)`가 `N=0` → 부정형 PASS·exit 0). 긍정형은 같은 상황에서 `-ge 1`이 깨져 fail-loud라 뒤집히지 않지만, **liveness를 부정형에만 붙이면 형태가 둘로 갈라진다** — 어느 쪽인지 고르는 결정이 매번 생기고, 그 결정이 틀리는 쪽이 정확히 vacuous PASS다. 그래서 긍정형에도 같은 줄을 둔다. `test -n "$S"`는 생산자가 **정당하게 빌 수 있는 판정**(예: 위 작성 규칙의 섹션 불변처럼 비교 결과가 비어야 PASS인 경우)에는 비교 결과가 아니라 **그 입력 스냅샷**에 건다.

  **생산자 줄의 `|| true`는 목적이 다르다 — 대입 줄에서 스크립트가 조용히 죽는 것을 막는다.** 계수 grep(0건 rc=1)·`git show`처럼 rc≠0을 낼 수 있는 명령을 생산자로 쓰면 `set -euo pipefail` 아래에서 대입 자체가 스크립트를 끝낸다(실측: `S=$(grep -cE '^## 99\.' CLAUDE.md)`가 아무 출력 없이 exit 1). `FAIL:` 메시지가 없어 **진짜 락 실패와 구분되지 않고**, 「앵커 부재」가 PASS 조건인 락은 PASS 케이스가 중단된다. `|| true`를 붙이면 두 경우가 다음 줄에서 갈린다 — 산출이 있으면(`S=0` 같은 계수) **측정값**으로 판정 줄이 받고, 산출이 진짜 비면 **liveness가 `FAIL:` 메시지와 함께 멈춘다.**

  **그 예외의 정본 변형은 이렇다 — 섹션 불변처럼 생산자가 둘이고 비교 결과가 비어야 PASS인 판정은, 두 입력 스냅샷 각각에 `test -n`을 걸고 비교 결과의 계수를 판정 줄로 받는다.** 이것은 아래 「다른 판정 형태를 쓰지 않는다」가 금지하는 즉흥이 아니라 **정본의 명시된 변형**이다 — 판정 줄은 여전히 `test <비교> || { echo 'FAIL: …'; exit 1; }` 한 꼴이고, 달라지는 것은 생산자 개수와 liveness가 붙는 대상(비교 결과가 아니라 입력 스냅샷 두 개)뿐이다. 이 변형은 두 가지를 함께 지킨다. **(1) `|| true`는 비교 생산자 대입 줄에 붙인다** — `diff`는 락이 FAIL해야 할 바로 그 경우(차이 있음)에 rc=1을 내므로, 없으면 FAIL 케이스가 `FAIL:` 줄 없이 대입에서 중단돼 진짜 락 실패와 구분되지 않는다(실측: `CMP=$(diff <(…) <(…))`가 차이가 있을 때 아무 출력 없이 exit 1). **(2) 비교 결과를 `grep -cE -e ''`로 세지 않는다** — `printf '%s\n' "$CMP"`는 `CMP`가 비어도 빈 줄 하나를 내보내 계수가 1이 되고, 「비어 있음이 PASS」인 판정이 늘 FAIL한다(실측: 빈 `CMP`에 `grep -cE -e ''`는 1, `grep -cE -e '^[<>]'`는 0). `grep -cE -e ''`가 정확한 것은 위 범위 길이 상한처럼 **생산자가 비어 있지 않음을 liveness가 먼저 보장한 계수**뿐이다. 여기서는 차이 표시 행(`diff`의 `^[<>]`, `diff -u`의 `^[-+]`)을 세는 패턴을 쓴다(실측: 같은 형태가 두 줄 중 한 줄이 다를 때 `N=2`로 FAIL, 같을 때 `N=0`으로 PASS).

  **다른 판정 형태를 쓰지 않는다.** idiom을 여럿 두면 각각이 `set -euo pipefail` 아래에서 서로 다른 엣지 케이스를 갖고, 계획 작성자가 그 단서를 전부 지키지 못한다. 판정 줄은 예외 없이 `test <비교> || { echo 'FAIL: …'; exit 1; }` 꼴이며, 생산자가 무엇을 세든 판정 줄의 모양은 바뀌지 않는다. 아래 넷은 **이 한 형태가 동시에 닫는 함정**이고, 쓰라는 지시가 아니라 **왜 이 형태인지의 근거**다.
  - **`!` 반전은 `set -e`가 집행하지 않는다.** bash 매뉴얼이 명시한 예외(「the command's return value is being inverted with `!`」)라 `! cmd …` 형태는 금지 토큰이 **실제로 있어도** 스크립트를 중단시키지 못하고 다음 줄로 진행해 exit 0으로 끝난다(실측: `set -euo pipefail` 아래 `! echo FORBIDDEN | grep -q FORBIDDEN`이 후속 명령을 실행하고 종료 상태 0). 정본 형태는 `!`를 쓰지 않고 `|| { echo …; exit 1; }`로 **명시 종료**한다.
  - **계수 grep은 0건일 때 rc=1이라 그대로 대입하면 대입 줄에서 스크립트가 죽는다.** 대입의 종료 상태가 곧 `grep`의 rc이기 때문이다(실측: `set -euo pipefail` 아래 `N=$(printf 'a\nb\n' | grep -cF 'ZZZ')`는 다음 줄을 출력하지 못하고 exit 1). **`|| true`가 이것을 중화**해 0건을 판정 실패가 아니라 `N=0`이라는 측정값으로 넘긴다.
  - **`grep -q`는 `pipefail`과 결합하면 입력 크기에 따라 판정이 뒤집힌다.** `grep -q`는 첫 매치에서 즉시 종료하고, 파이프 앞 생산자(`awk`·`git show`·`git diff`·`seq`)는 쓸 게 남아 있으면 SIGPIPE로 죽으며 `pipefail`이 그 **141**을 파이프라인 종료 상태로 전파한다. 실측: 금지 토큰을 담은 2,000,000줄 입력에 `if seq 1 2000000 | grep -q '^1$'; then echo FAIL; exit 1; fi`는 **`PASS`를 찍고 exit 0**(vacuous PASS)인데, 같은 명령을 `seq 1 5`로 줄이면 정상 FAIL한다 — **대상이 커진 뒤 같은 락이 조용히 반대로 뒤집힌다.** 정본 형태의 계수 grep은 **입력을 끝까지 읽으므로** SIGPIPE가 나지 않는다(실측: 같은 2,000,000줄 입력을 `S=$(seq 1 2000000)`로 담아 `printf '%s\n' "$S" | grep -cE`에 넣어도 긍정형은 `N=1`로 통과, 부정형은 141이 아니라 exit 1로 집행).
  - **bare 판정 명령은 부정 의도를 통째로 역전시킨다.** `grep -q '금지패턴' "$F"`를 한 줄 그대로 두면 금지 패턴이 **있을 때 rc=0으로 통과**하고 없을 때 `set -e`로 죽는다 — 의도와 정반대다. 정본 형태는 긍정·부정이 `-ge 1`/`-eq 0`만 다르고 나머지가 같아 뒤집힐 자리가 없다.
  - **`grep -qv`는 부재 판정에 쓰지 않는다.** 「매치하지 않는 행이 하나라도 있으면 참」이라 「전 행 부재」를 판정하지 못한다. 부재는 위 부정형(`-eq 0`)으로만 판정한다. 반대로 매치하지 않는 행을 **세는** `grep -vcF`·`grep -vcE`는 정본 형태의 생산자 안에서 쓴다 — 그것은 판정이 아니라 계수이고, 매처 선택과 `-e` 전달 규칙은 계수와 같다(실측: `aaa`·`bbb`·`ccc` 3줄에 `grep -vcF -e 'aaa'`·`grep -vcE -e '^a'`가 모두 2).
- **패턴은 항상 홑따옴표로 감싼다.** 큰따옴표 안의 백틱과 `$`는 셸이 먼저 해석해 패턴을 바꿔 버린다.
- **락 스크립트는 고유 파일명으로 저장하고, 첫머리에서 `cd "$(git rev-parse --show-toplevel)"`로 cwd를 워크트리 루트에 고정한 뒤 `pwd`와 `git rev-parse --short HEAD`를 출력한다.** 어느 워크트리·어느 커밋에서 돌았는지가 결과와 함께 남아야 한다. 아래 로그·임시 파일 경로도 생산자의 상대 경로도 워크트리 루트를 전제하므로, 하니스가 다른 cwd에서 호출하면 로그가 gitignore되지 않은 위치에 생기고 생산자가 빈 산출을 내 liveness FAIL이 락 실패로 오독된다(실측: 워크트리 하위 디렉터리에서 호출해도 이 치환이 그 워크트리 루트를 잡는다 — 링크된 워크트리에서는 공유 체크아웃이 아니라 워크트리 자신의 루트가 나온다). 워크트리 **밖에서** 호출하면 이 치환이 다른 저장소 루트를 잡으므로, 그 오호출은 출력한 `pwd`가 의도한 워크트리인지 대조해 잡는다.
- **락 스크립트 자신과 락이 만드는 로그·임시 파일은 모두 워크트리 안의 gitignore된 경로(예: 워크트리 루트 기준 `docs/temp/`·`logs/`)에 둔다.** 공유 `/tmp`는 동시에 도는 다른 작업과 충돌해 결과를 오염시킨다. **gitignore되지 않은 경로**에 두면 락이 자기가 측정하는 상태를 오염시킨다 — 로그도 스크립트도 untracked 파일로 남아 clean 워크트리 요구를 깨고, `git add -A`에 쓸려 들어가면 정확 파일 수 락이 하니스 파일을 열거해 FAIL하며, 그러면 검증 규칙의 「락이 아니라 구현을 되돌린다」가 올바른 구현에 헛발동한다. **디렉터리를 쓰면 갓 만든 `git worktree`에는 그 디렉터리가 없을 수 있으므로 첫 사용 전에 `mkdir -p`로 만든다** — 없는 디렉터리로 리다이렉트하면 `set -euo pipefail` 아래에서 `FAIL:` 줄 없이 rc=1로 중단해 진짜 락 실패와 구분되지 않는다(실측: `logs/`가 없는 격리 워크트리에서 `echo … > logs/lock.log`가 `No such file or directory`로 rc=1, `mkdir -p logs` 뒤에는 rc=0). **락 산출을 파일로 남길 때는 `2>&1`로 stderr를 함께 병합한다** — `> logs/lock.log`만 쓰면 위 「락 실패가 아니라 하니스 실패」를 가르는 `grep: invalid option`·`unrecognized option` 줄이 로그 밖으로 흩어져 로그에는 맨 `FAIL:` 판정 줄만 남고, 그 구분이 로그만으로는 서지 않아 검증 규칙의 「락이 아니라 구현을 되돌린다」가 하니스 실패에 적용된다(실측: 자리표시자를 치환하지 않은 스크립트를 `> logs/lock.log`로만 남기면 로그에 `FAIL:` 줄만, `2>&1`을 붙이면 `grep: invalid option` 줄이 그 앞에 함께 남는다).
- **base 대입 전에 `git fetch origin main`을 먼저 실행한다.** `origin/main`은 로컬 remote-tracking ref라 갱신하지 않으면 작성 규칙의 diff base 불릿이 경고한 거짓 FAIL이 그대로 난다. **이 fetch는 위 생산자 규칙의 대상이 아니다** — `git fetch origin main`은 진행 상황을 stderr에 쓰고 stdout에는 아무것도 내놓지 않아, 산출을 변수에 담아 `test -n`으로 받으면 성공했을 때조차 FAIL 분기로 간다(실측: `S=$(git fetch origin main 2>/dev/null || true)` 뒤 `${#S}`가 0). 그렇다고 `|| true`만 붙여 두면 오프라인·ref prune 실패가 조용히 삼켜진다. **fetch가 ref를 세웠는지는 `origin/main` 도달성으로 받는다** — `S=$(git rev-parse --verify --quiet origin/main || true)`가 산출을 내므로 정본 형태의 liveness 줄이 곧 판정이다(실측: ref가 있으면 rc=0에 SHA, 없으면 rc=1에 빈 산출). 닫는 것은 **ref 부재까지**이고, ref가 있는데 뒤처진 경우는 닫지 못한다. 생산자 규칙이 걸리는 것은 그다음 줄의 `B=$(git merge-base origin/main HEAD)`뿐이다 — 이 대입을 맨몸으로 두면 `origin/main` ref가 prune된 스크래치 워크트리나 오프라인 실행에서 `set -euo pipefail` 아래 `FAIL:` 줄 없이 중단해 진짜 락 실패와 구분되지 않는다(실측: `B=$(git merge-base origin/nonexistent-main HEAD)`가 rc=128로 다음 줄에 도달하지 못함). `|| true`로 대입을 중화하고 `test -n "$B" || { echo 'FAIL: base 미확보'; exit 1; }` liveness로 받는다 — `set -u`는 미설정 참조만 덮지 **실패한 대입은 덮지 못한다.**
- **무필터 열거 락을 돌리기 전에 `git add -A`를 먼저 실행한다.** `git diff --name-only "$B"`는 추적되는 파일만 보므로, 스테이징하지 않으면 계획에 없는 신규 파일이 untracked로 남아 집합이 닫히지 않는다(실측: `git status --porcelain`이 `?? sneaky.md`를 내놓는데 `git diff --name-only "$B"`는 열거하지 않아 정확 파일 수 락이 그대로 통과, `git add -A` 뒤에는 같은 생산자가 그 파일을 함께 열거).
- **계획 작성자는 이 집행 주의 블록을 이슈 본문에 실어 보낸다.** 개발 에이전트는 실행 시점에 이 커맨드 문서를 읽지 않고 이슈 본문의 verification을 읽는다. 본문에 없으면 집행 규칙은 소비되지 않는다.

##### 검증 규칙

- **계획 확정 전에 baseline에서 전 락을 실제로 실행하고 before/after 대조표를 계획에 싣는다.** 「지금은 실패, 고치면 통과」가 실측으로 확인되지 않은 락은 판별력이 없다. 계획 확정 시점에는 구현이 없으므로 「after」는 **`git worktree add`로 만든 스크래치 워크트리에 임시 패치를 적용해 측정한 뒤 그 워크트리를 폐기**해서 만든다. `cp -r` 사본은 저장소가 아니라 `git show "$B:$F"`·`git diff --name-only "$B"` 같은 생산자가 전부 오류를 낸다(실측: `.git` 없는 사본에서 `not a git repository`). 작업 브랜치에 구현을 미리 넣어 두는 방식은 쓰지 않는다.
- **락을 양방향으로 확인한다.** 잡아야 할 것을 잡는가, 그리고 계획이 지시한 구현을 거부하지 않는가. 둘 중 하나라도 어긋나면 구현자가 지시받은 일을 했을 때 자기 게이트에 걸리는 자기모순이 된다.
- **대조군 락을 명시하고 baseline에서 PASS임을 밝힌다.** 대조군은 기존 구조가 그대로임을 지키는 락이고, 구현 후 깨지면 과잉수정 신호다. 판별력 락과 대조군, 그리고 판별력이 없는 전제 검사를 대조표에서 구분해 적는다.
- **정확 파일 수 락이 FAIL하면 락이 아니라 구현을 되돌린다.** 락을 구현에 맞춰 느슨하게 고치는 것은 게이트 무력화다. 미커밋 변경이 남은 워크트리도 이 락을 직접 깨므로 격리 워크트리를 clean 상태로 두고 시작한다.
- **락이 덮을 표면 집합은 census로 닫는다.** 토큰 전수 census 표를 계획에 싣고 `히트 = 수정 + 명시 제외` 전건이 되게 한다. census 명령은 그대로 다시 돌려 같은 결과가 나오는 형태로 싣는다 — `grep -E`를 빼서 basic regex의 `|`가 리터럴이 되면 0건이 나오고, 재현되지 않는 census는 근거가 아니다. **`grep -c`는 매치된 줄 수이지 출현 수가 아니다** — 한 줄에 토큰이 두 번 나오면 1로 세어져 `히트 = 수정 + 명시 제외`를 닫았다고 믿는 census에서 표면이 조용히 빠진다(실측: 이 커맨드 문서 자신에 대고 `grep -q` 리터럴을 세면 줄 수보다 출현 수가 크다; 최소 재현은 같은 줄에 리터럴이 두 번 있는 입력에서 `grep -cF`가 1, `grep -oF`로 뽑아 센 출현이 2). 출현 전수가 필요한 계수는 `grep -o`로 출현을 한 줄씩 뽑은 뒤 그 산출을 정본 형태의 생산자로 넣는다. `-o` 산출은 한 줄이 곧 출현 1건이라 계수 쪽에 새 규칙이 필요 없고, 매처는 집행 규칙의 선택 기준(리터럴이면 `-cF`, 정규식이면 `-cE`)을 그대로 받는다.
- **census는 서로 다른 탐색 양식 2종 이상으로 수행한다.** 개념 토큰 grep과 명령 형태 grep은 서로 다른 표면을 찾아낸다. 한 양식만 쓰면 다른 양식에만 보이는 표면이 통째로 빠지고, 그 사실조차 드러나지 않는다.
- **pathspec 제외는 사각지대를 만든다.** `':!docs/temp'`처럼 경로를 통째로 빼면 그 경로에만 있는 표면은 census에 나타나지 않는다. 제외한 경로는 제외 사실과 사유를 census 표에 함께 적어 남은 사각지대를 계획에서 유계로 선언한다.

#### 계획 정비 완료 코멘트

쓰기 모드에서는 이슈 본문 정비 직후 계획 정비 완료 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 계획 정비 완료**
- status: plan-ready-for-review
- spec-path: {1A Spec-First | 1B Issue-First Bundled}
- ssot: {docs/specs/...}
- risk flags: {none | lifecycle | contract-drift | generated-artifact-sync | mutable-config | health-path | multi-consumer}
- next: Plan Review 요청"
```

### 5단계: Plan Review 요청 (Gate 0)

정비된 구현계획을 별도 컨텍스트의 계획 리뷰 서브에이전트 `@plan-reviewer`로 넘긴다.
구현 세션과 격리된 read-only 리뷰이며, 이 단계는 코드 수정, 브랜치 생성, PR 생성을 하지 않는다.
`@plan-reviewer` 정의는 `.agent/agents/plan-reviewer.md`다.

```text
Agent(
  subagent_type="plan-reviewer",
  prompt="""
이슈 #{번호}의 본문 Implementation Plan을 검토하라.
가정, 범위 적합성, 누락된 소비자, 생성 산출물, 롤백/테스트 공백을 공격적으로 확인하라.

## 이슈 본문 Implementation Plan
{Spec Path / File Map / Tasks / Verification / Risk Flags / Stop Conditions / Non-Goals}

verdict(approve-implement | narrow-scope | revise-plan | split-issue | invoke-human)와 근거를 반환하라.
"""
)
```

`@plan-reviewer`는 동기 호출로 verdict와 근거를 반환한다(read-only, GitHub 쓰기 없음).
반환된 verdict를 오케스트레이터가 이슈 코멘트에 `Plan Review`로 남기고, `reviewer:` 필드에 리뷰 수행 주체를 기록한다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Review**
- verdict: {approve-implement | narrow-scope | revise-plan | split-issue | invoke-human}
- reviewer: @plan-reviewer
- reviewed-plan: 이슈 본문 Implementation Plan
- feedback summary: {요약}
- required changes: {없음 | 이슈 본문에 반영할 항목}
- next: {Plan Preflight 완료 | 이슈 본문 보강 후 재요청 | 분리/사람 판단 대기}"
```

Verdict:

- `approve-implement`: 계획대로 구현 가능
- `narrow-scope`: 축소 범위로 구현 가능
- `revise-plan`: 이슈 본문 보강 후 재검토 필요
- `split-issue`: 이슈 분리 필요
- `invoke-human`: 사람 판단 필요

### 6단계: 피드백 반영 루프

- `approve-implement`: 현재 구현계획을 확정한다.
- `narrow-scope`: 축소 범위, 제외 범위, 후속 이슈 후보를 이슈 본문에 반영한 뒤 확정한다.
- `revise-plan`: `plan-preflight:started` 상태를 유지하고 이슈 본문을 보강한 뒤 `Plan Review` 코멘트에 재요청 사유를 남기고 다시 요청한다.
- `split-issue`: 구현계획 확정을 중단하고 `Plan Preflight 보류` 코멘트에 아래 형식의 분리안을 남긴다. 하위 이슈 생성, 라벨 조작, 큐 편입, 부모 이슈 close 자동화는 하지 않는다.
- `invoke-human`: 구현계획 확정을 중단하고 `Plan Preflight 보류` 코멘트에 사람 판단이 필요한 질문을 남긴다.

`split-issue` 보류 코멘트에는 다음 구조를 사용한다.

```markdown
🤖 **Plan Preflight 보류**
- status: split-issue
- reason: {범위 과대 | 다중 invariant | 다중 consumer | 계약 축 혼재 | 선행/후속 관계 필요}
- autonomous action: none
- labels: plan-preflight:done 제거, plan-preflight:started 제거
- next: 사람 또는 별도 오케스트레이션이 아래 split plan을 기준으로 후속 이슈 등록

## Split Plan

### 후보 A
- 목표:
- 포함:
- 제외:
- 선행:
- 후속:
- 예상 수정 파일:
- 읽어야 할 소비자:
- 검증:
- risk class:
- stop conditions:

### 후보 B
- 목표:
- 포함:
- 제외:
- 선행:
- 후속:
- 예상 수정 파일:
- 읽어야 할 소비자:
- 검증:
- risk class:
- stop conditions:
```

split plan은 파일 묶음이 아니라 flow/invariant 기준으로 나눈다. 각 후보는 독립적으로 검증 가능해야 하며, 후속 이슈가 merge되기 전의 중간 상태가 안전한지 명시한다.

### 7단계: 완료 라벨

`approve-implement` 또는 `narrow-scope`가 반영된 경우에만 Plan Preflight를 완료한다.

```bash
gh issue edit #{번호} --remove-label "plan-preflight:started" || true
gh issue edit #{번호} --add-label "plan-preflight:done"
```

완료 직후 이슈 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 완료**
- status: done
- verdict: {approve-implement | narrow-scope}
- implementation plan: 이슈 본문 Implementation Plan 기준
- labels: plan-preflight:done
- next: `/implement-issue #{번호}` 실행 가능"
```

중단 시 라벨 처리:

- `needs-rewrite`, `needs-spec-first`, `blocked`, stale 계획: `plan-preflight:done` 제거
- `split-issue`, 사람 판단 또는 선행 이슈 대기: `plan-preflight:started` 제거 후 보류 사유 코멘트

중단 시에는 아래 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 보류**
- status: {needs-rewrite | needs-spec-first | blocked | split-issue | invoke-human}
- reason: {스펙 충돌 | 선행 이슈 미완 | 범위 분리 필요 | 사람 판단 필요 | stale plan}
- labels: plan-preflight:done 제거, 필요 시 plan-preflight:started 제거
- next: {스펙 정리 | 선행 이슈 완료 대기 | 후속 이슈 분리 | 사람 답변 대기}"
```

`split-issue` 상태의 `next`는 자동 실행이 아니라 "후속 이슈 분리"다. 자동 하위 이슈 생성, 자동 실행 상태값, 부모 이슈 자동 close 같은 실행 계약은 이 커맨드 범위 밖이다.

## 결과 보고

사용자에게 아래를 요약한다.

```markdown
## Plan Preflight 완료

- issue: #123
- status: `done | needs-rewrite | needs-spec-first | blocked | split-issue | invoke-human`
- labels: `plan-preflight:started | plan-preflight:done | n-a`
- Plan Review: `approve-implement | narrow-scope | revise-plan | split-issue | invoke-human`
- 구현 인계 가능 여부:
- 주요 risk flags:
```
