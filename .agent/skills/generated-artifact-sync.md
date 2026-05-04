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
- 수동 편집 금지 산출물을 수동으로만 맞추지 않았는가
- 생성 산출물이 새 구현을 반영하지만 소비자는 여전히 예전 계약을 쓰지 않는가
- `frontend/src/types/api.generated.ts` 변경 시 `frontend/src/api/*.ts` adapter와 UI/domain model이 같은 PR에서 맞춰졌는가
- generated type import가 adapter 계층(`frontend/src/api/*.ts`) 밖으로 새지 않았는가

## 주요 산출물

- `frontend/openapi.json`
- `frontend/src/types/api.generated.ts`
- `docs/architecture/generated/db-schema.md`
- `guide/cli.md`
- `docs/architecture/generated/project-structure.md`

## red flags

- API 구현만 바뀌고 generated type이 없다
- DDL이 바뀌었는데 schema 문서가 그대로다
- 구조 문서가 새 디렉토리를 모른다
- generated type만 갱신되고 adapter/UI model은 이전 raw shape를 계속 가정한다
- `api.generated.ts`를 수동 편집해 OpenAPI와 타입 산출물의 출처가 갈라진다
