# D-015: default-deny 인증 게이트 (2026-05-11)

> Ante 설계 결정 기록.
> 인덱스: [README.md](README.md)
> 상태: **D-018 이후 CLI/IPC 중심 인증 계약으로 축소됨**.

**결정**: CLI 명령은 기본적으로 인증을 요구한다. 공개 명령은 명시 allowlist에만 둔다. 인증은 CLI group factory가 1차 차단하고, scope 검증은 command decorator가 담당한다.

**근거**:
- 새 명령 추가 시 인증 누락이 안전한 실패(exit 1)로 드러나야 한다.
- 공개 명령은 누락이 아니라 의도된 결정이어야 한다.
- `require_scope` predicate(human bypass + agent scope 검증)는 Member scope SSOT를 따른다.

**책임 분리**:

| 단계 | 책임 | 위치 |
|------|------|------|
| 1차 차단(authentication) | 인증된 principal이 있는지 확인. 없으면 exit 1. | CLI group factory |
| 2차 차단(authorization) | required scope를 만족하는지 확인. agent가 부족하면 거부. human은 bypass. | CLI decorator |

**Consequences**:
- CLI 공개 명령은 `_AUTH_EXEMPT_COMMAND_PATHS` allowlist로 관리한다.
- Runtime mutation은 CLI가 IPC로 서버에 전달하며, IPC command handler는 actor를 받아 audit log를 남긴다.
- D-018 이후 HTTP transport와 session cookie 기반 인증은 활성 런타임 계약이 아니다.
