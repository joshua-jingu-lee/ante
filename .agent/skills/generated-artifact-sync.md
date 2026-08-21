# 생성 산출물 동기화 스킬

> 코드에서 파생되는 문서나 타입, 스키마 산출물이 함께 갱신되어야 하는 변경을 점검할 때 사용한다.

## 언제 읽나

- DB DDL / schema 문서
- CLI command / guide
- 프로젝트 구조 문서

## 체크리스트

- 변경된 계약에 대응하는 생성 산출물이 모두 갱신되었는가
- 산출물 생성 명령과 결과 파일이 함께 PR에 포함되었는가
- 생성 산출물마다 리뷰/CI 전에 전용 check 명령을 실제로 실행했는가
- 수동 편집 금지 산출물을 수동으로만 맞추지 않았는가
- 생성 산출물이 새 구현을 반영하지만 소비자는 여전히 예전 계약을 쓰지 않는가

## 주요 산출물

| 산출물 | 입력/SSOT | Generate | Check | 기대 동작 |
|---|---|---|---|---|
| `docs/architecture/generated/project-structure.md` | 현재 Git 추적/비무시 파일 트리 | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py` | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py --check` | generate는 파일 구조 문서를 재생성한다. check는 산출물이 최신이면 0으로 종료하고, 불일치하면 실패하며 재생성 명령을 안내한다. |
| `docs/architecture/generated/db-schema.md` | 모듈 소스 코드의 DDL 상수 | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py` | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py --check` | generate는 DB schema 문서를 재생성한다. check는 산출물이 최신이면 0으로 종료하고, 불일치하면 실패하며 재생성 명령을 안내한다. |
| `guide/cli.md` | Click CLI command tree | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_cli_reference.py` | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_cli_reference.py --check` | generate는 CLI 레퍼런스를 재생성한다. check는 산출물이 최신이면 0으로 종료하고, 불일치하면 실패하며 재생성 명령을 안내한다. |

## 적용 흐름

1. 구현 중 생성 산출물의 입력이 바뀌면 먼저 대응하는 generate 명령을 실행한다.
2. 생성된 산출물과 소비자 코드/문서가 같은 계약을 쓰는지 확인한다.
3. 리뷰 또는 CI 전에는 전용 check 명령을 실행한다.
4. 모든 생성 산출물은 전용 `--check`를 제공한다. 새 산출물을 추가하면 커밋된 날짜 스탬프를 동결하는 `--check`도 함께 만든다. 이 주장의 정의역은 `scripts/generate_*.py` 규약을 따르는 생성기이며, 다른 메커니즘으로 만들어지는 산출물을 도입하면 같은 규약으로 편입한다. 근거는 #2472다.

## red flags

- DDL이 바뀌었는데 schema 문서가 그대로다
- 구조 문서가 새 디렉토리를 모른다
