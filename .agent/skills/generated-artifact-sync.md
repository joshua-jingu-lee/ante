# 생성 산출물 동기화 스킬

> 코드에서 파생되는 문서나 타입, 스키마 산출물이 함께 갱신되어야 하는 변경을 점검할 때 사용한다.

## 언제 읽나

- OpenAPI / generated frontend types
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
- `frontend/src/types/api.generated.ts` 변경 시 `frontend/src/api/*.ts` adapter와 UI/domain model이 같은 PR에서 맞춰졌는가
- generated type import가 adapter 계층(`frontend/src/api/*.ts`) 밖으로 새지 않았는가

## 주요 산출물

| 산출물 | 입력/SSOT | Generate | Check | 기대 동작 |
|---|---|---|---|---|
| `docs/architecture/generated/project-structure.md` | 현재 Git 추적/비무시 파일 트리 | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py` | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py --check` | generate는 파일 구조 문서를 재생성한다. check는 산출물이 최신이면 0으로 종료하고, 불일치하면 실패하며 재생성 명령을 안내한다. |
| `docs/architecture/generated/db-schema.md` | 모듈 소스 코드의 DDL 상수 | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py` | `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py --check` | generate는 DB schema 문서를 재생성한다. check는 산출물이 최신이면 0으로 종료하고, 불일치하면 실패하며 재생성 명령을 안내한다. |
| `guide/cli.md` | Click CLI command tree | `.venv/bin/python scripts/generate_cli_reference.py` | `.venv/bin/python scripts/generate_cli_reference.py && git diff --exit-code -- guide/cli.md` | generate는 CLI 레퍼런스를 재생성한다. 전용 `--check`가 없으므로 생성 후 diff가 비어 있어야 최신이다. |
| `frontend/openapi.json` | 실행 중인 백엔드 `/openapi.json` | `curl http://localhost:3982/openapi.json -o frontend/openapi.json` | `git diff --exit-code -- frontend/openapi.json` | 백엔드 API 계약 변경 시 OpenAPI JSON을 갱신한다. 전용 check가 없으므로 재수집 후 diff가 비어 있어야 최신이다. |
| `frontend/src/types/api.generated.ts` | `frontend/openapi.json` 또는 백엔드 `/openapi.json` | `cd frontend && npm run generate-types` | `cd frontend && npm run generate-types && git diff --exit-code -- src/types/api.generated.ts` | OpenAPI에서 TypeScript wire contract를 재생성한다. 전용 check가 없으므로 생성 후 diff가 비어 있어야 최신이다. |

## 적용 흐름

1. 구현 중 생성 산출물의 입력이 바뀌면 먼저 대응하는 generate 명령을 실행한다.
2. 생성된 산출물과 소비자 코드/문서가 같은 계약을 쓰는지 확인한다.
3. 리뷰 또는 CI 전에는 전용 check 명령을 실행한다.
4. 전용 check가 없는 산출물은 generate 명령을 다시 실행한 뒤 `git diff --exit-code -- <산출물>`로 변경 없음 상태를 확인한다.

## red flags

- API 구현만 바뀌고 generated type이 없다
- DDL이 바뀌었는데 schema 문서가 그대로다
- 구조 문서가 새 디렉토리를 모른다
- generated type만 갱신되고 adapter/UI model은 이전 raw shape를 계속 가정한다
- `api.generated.ts`를 수동 편집해 OpenAPI와 타입 산출물의 출처가 갈라진다
