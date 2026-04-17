# Strategy 모듈 세부 설계 - 설계 결정 - Strategy Registry

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# Strategy Registry

구현: `src/ante/strategy/registry.py` 참조

검증 완료된 전략 목록을 SQLite에 영속화하여 관리한다. 전략 상태는 다음과 같이 전이된다:

```
REGISTERED ──결재 승인──▷ ADOPTED ──폐기──▷ ARCHIVED
     └──────────────────폐기──────────────▷ ARCHIVED
```

- `REGISTERED`: 검증 통과, 등록됨 (결재 대기)
- `ADOPTED`: 결재 승인, 봇 배정 가능
- `ARCHIVED`: 보관 (더 이상 사용하지 않음)

> **봇과 전략의 분리**: 봇은 전략을 배정받을 때 전략 파일을 복제(snapshot)하여 독립 관리한다. 따라서 봇의 실행·중지가 전략 상태에 영향을 주지 않으며, 전략이 ARCHIVED되어도 운영 중인 봇에는 영향이 없다.

> **버전 업그레이드 정책**: 동일 name의 새 version 등록 시 이전 version의 상태를 자동 변경하지 않는다. 상태 전환은 사용자가 명시적으로 수행한다.

**SQLite 스키마**:

```sql
CREATE TABLE strategies (
    strategy_id          TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    version              TEXT NOT NULL,
    filepath             TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'registered',
    registered_at        TEXT NOT NULL,
    description          TEXT DEFAULT '',
    author_name          TEXT DEFAULT 'agent',
    author_id            TEXT DEFAULT 'agent',
    validation_warnings  TEXT DEFAULT '[]',  -- JSON array
    rationale            TEXT DEFAULT '',     -- 투자 논거
    risks                TEXT DEFAULT ''      -- 주요 리스크
);
```

#### StrategyStatus (StrEnum)

| 값 | 설명 |
|----|------|
| `REGISTERED` | 검증 통과, 등록됨 (결재 대기) |
| `ADOPTED` | 결재 승인, 봇 배정 가능 |
| `ARCHIVED` | 보관 (폐기) |

#### StrategyRecord 필드

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `strategy_id` | `str` | — | 고유 ID (`{name}_v{version}`) |
| `name` | `str` | — | 전략 이름 |
| `version` | `str` | — | 버전 |
| `filepath` | `str` | — | 전략 파일 경로 |
| `status` | `StrategyStatus` | — | 상태 |
| `registered_at` | `datetime` | — | 등록 시각 |
| `description` | `str` | `""` | 설명 |
| `author_name` | `str` | `"agent"` | 작성자 표시 이름 |
| `author_id` | `str` | `"agent"` | 작성자 ID |
| `validation_warnings` | `list[str]` | `[]` | 검증 경고 목록 |
| `rationale` | `str` | `""` | 투자 논거. Agent가 전략 제출 시 작성. 대시보드 전략 상세에서 표시 |
| `risks` | `str` | `""` | 주요 리스크. Agent가 전략 제출 시 작성. 대시보드 전략 상세에서 표시 |

**근거**:
- `strategy_id`는 `{name}_v{version}` 형식 — 동일 전략의 다른 버전 공존 가능
- SQLite 영속화로 시스템 재시작 후에도 등록 정보 유지
- 상태(status)로 전략 생명주기 관리: 등록 → 채택 → 보관
