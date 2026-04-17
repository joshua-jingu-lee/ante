# Strategy 모듈 세부 설계 - 설계 결정 - StrategySnapshot — 전략 파일 스냅샷 관리

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# StrategySnapshot — 전략 파일 스냅샷 관리

구현: `src/ante/strategy/snapshot.py` 참조

봇 시작 시 원본 전략 파일을 `strategies/.running/{bot_id}/`에 복사하여, 원본 수정으로부터 실행 중 코드를 보호한다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `create` | `bot_id: str, source_path: Path` | `Path` | 스냅샷 생성, 복사된 경로 반환 |
| `cleanup` | `bot_id: str` | `None` | 봇의 스냅샷 삭제 |
| `cleanup_all` | — | `int` | 잔존 스냅샷 전체 정리 (시스템 시작 시), 정리된 수 반환 |
| `get_snapshot_path` | `bot_id: str` | `Path \| None` | 스냅샷 경로 조회, 없으면 None |

**설계 근거**:
- Agent가 전략을 수정 중일 때 실행 중인 봇이 영향 받지 않도록 방어
- 봇 종료 시 자동 정리, 시스템 시작 시 잔존 스냅샷 일괄 정리
