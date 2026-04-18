# 계약 표류 리뷰 스킬

> 스펙, 구현, 소비자, 생성 산출물 사이의 이름/경로/필드 drift를 점검할 때 사용한다.

## 언제 읽나

- API endpoint rename
- response field 추가 / 삭제 / rename
- CLI 명령 / 옵션 변경
- schema, Pydantic model, generated type 변경
- docs/specs 와 구현이 같이 흔들릴 가능성이 있는 변경

## 체크리스트

- SSOT 문서와 실제 구현이 같은 이름과 경로를 쓰는가
- 경로 rename 시 모든 소비자가 함께 바뀌었는가
- field rename 시 frontend / tests / docs / generated outputs가 같이 갱신되었는가
- 스펙을 바꾸지 않고 구현만 바꾸는 drift가 없는가
- 구현을 유지한 채 스펙만 앞서가거나 뒤처지지 않는가

## red flags

- 문서엔 `kill-switch`인데 구현은 `halt` / `activate`
- OpenAPI는 갱신됐는데 generated type은 예전 필드를 유지
- response_model은 바뀌었는데 tests가 예전 shape만 본다
