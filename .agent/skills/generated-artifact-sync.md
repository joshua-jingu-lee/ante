# 생성 산출물 동기화 스킬

> 코드에서 파생되는 문서나 타입, 스키마 산출물이 함께 갱신되어야 하는 변경을 점검할 때 사용한다.

## 언제 읽나

- DB DDL / schema 문서
- CLI command / guide
- 프로젝트 구조 문서

## 체크리스트

- 변경된 계약에 대응하는 생성 산출물이 모두 갱신되었는가
- 산출물 생성 명령과 결과 파일이 함께 PR에 포함되었는가
- 전용 check 명령이 있는 산출물은 리뷰/CI 전에 실제 check 명령을 실행했는가
- 전용 check 명령이 없는 산출물은 생성 명령 실행 후 `git diff -- <산출물>`로 최신 여부를 확인했는가
- 수동 편집 금지 산출물을 수동으로만 맞추지 않았는가
- 생성 산출물이 새 구현을 반영하지만 소비자는 여전히 예전 계약을 쓰지 않는가

## 주요 산출물

| 산출물 | 입력/SSOT | Generate | Check | 기대 동작 |
|---|---|---|---|---|
| `docs/architecture/generated/project-structure.md` | 현재 Git 추적/비무시 파일 트리 | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py` | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py --check` | generate는 파일 구조 문서를 재생성한다. check는 산출물이 최신이면 0으로 종료하고, 불일치하면 실패하며 재생성 명령을 안내한다. |
| `docs/architecture/generated/db-schema.md` | 모듈 소스 코드의 DDL 상수 | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py` | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py --check` | generate는 DB schema 문서를 재생성한다. check는 산출물이 최신이면 0으로 종료하고, 불일치하면 실패하며 재생성 명령을 안내한다. |
| `guide/cli.md` | Click CLI command tree | `.venv/bin/python scripts/generate_cli_reference.py` | `.venv/bin/python scripts/generate_cli_reference.py && git diff --exit-code -- guide/cli.md` | generate는 CLI 레퍼런스를 재생성한다. 전용 `--check`가 없으므로 생성 후 diff가 비어 있어야 최신이다. |

## 적용 흐름

1. 구현 중 생성 산출물의 입력이 바뀌면 먼저 대응하는 generate 명령을 실행한다.
2. 생성된 산출물과 소비자 코드/문서가 같은 계약을 쓰는지 확인한다.
3. 리뷰 또는 CI 전에는 전용 check 명령을 실행한다.
4. 전용 check가 없는 산출물은 generate 명령을 다시 실행한 뒤 `git diff --exit-code -- <산출물>`로 변경 없음 상태를 확인한다.
   - 이 형태는 **regenerate-first**이므로 유효하다 — regenerate를 먼저 돌렸을 때만 stale 산출물이 rc=1로 잡힌다. regenerate를 건너뛰고 커밋 뒤 그냥 실행하면 워크트리 = 인덱스라 항상 rc=0이 되어 가드가 죽는다. 다만 생성기가 날짜 스탬프를 찍는 산출물은 **diff가 그 스탬프 줄만일 때 PASS로 본다** — `scripts/generate_project_structure.py`가 `--check` 모드에서 기존 스탬프를 재사용하는 것과 같은 취급이다. 스탬프 줄 밖에 hunk가 있으면 stale이다. 「스탬프 줄만인지」는 육안이 아니라 아래 정본 형태로 판정한다. `scripts/generate_cli_reference.py`처럼 생성 시각을 무조건 기록하는 생성기는 regenerate만으로 산출물을 변경 상태로 만들어 `git diff --exit-code`가 **항상 rc=1**이 되므로, 「변경 없음」은 원리적으로 성립하지 않고 그 rc만으로는 stale을 가릴 수 없다. regenerate 직후 스탬프 줄을 제외한 나머지 변경 줄 수를 세어 0인지 판정한다.

     ```bash
     N=$(git diff -U0 -- <산출물> | grep -E '^[+-]' | grep -v '^[+-][+-]' | grep -vc '마지막 갱신' || true)
     test "$N" -eq 0 || { echo "FAIL: 스탬프 외 변경"; exit 1; }
     ```

     판정을 마치면 **후속 검증·회귀 락을 돌리기 전에 `git checkout -- <산출물>`로 스탬프 변경을 되돌려 워크트리를 clean으로 만든다** — 미커밋 변경이 남으면 clean 워크트리를 요구하는 회귀 락(정확 파일 수 락)이 같은 워크트리에서 오탐한다.

## red flags

- DDL이 바뀌었는데 schema 문서가 그대로다
- 구조 문서가 새 디렉토리를 모른다
