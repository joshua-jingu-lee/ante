# CLI 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/cli/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) CLI 인터페이스, D-007, D-010

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
계약 SSOT는 이 README의 문서 목록과 주제별 하위 문서다.
[cli.md](cli.md)는 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
새 계약, 결정, 미결 사항은 [cli.md](cli.md)에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [cli.md](cli.md) | 호환용 인덱스 및 기존 섹션 앵커 (계약 본문 아님) |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-commands.md](03-commands.md) | 커맨드 상세. CLI 명령 시그니처와 실행 분류의 SSOT |
| [04-agent-workflows.md](04-agent-workflows.md) | Agent 워크플로우 예시 |
| [06-cross-module-notes.md](06-cross-module-notes.md) | 타 모듈 설계 시 참고 |
