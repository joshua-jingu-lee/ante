# Report Store 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/report/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 리포트, [backtest.md](../backtest/backtest.md) 백테스트 결과, D-010

## 개요

Report Store는 **전략 검증 리포트를 저장·관리·조회하는 모듈**이다.
AI Agent가 전략 백테스트 후 리포트를 제출하면 시스템에 축적되며,
사용자가 리포트를 검토하여 전략 채택 여부를 결정한다.

**주요 기능**:
- **리포트 스키마**: Agent가 제출할 리포트의 표준 포맷 정의
- **리포트 저장**: SQLite에 리포트 메타데이터 + JSON 상세 내용 저장
- **리포트 조회**: 전략별, 기간별, 상태별 필터링 조회
- **Agent 피드백**: 운영 중인 전략의 실전 성과 데이터 제공 (Agent 개선 루프용)

## 설계 결정

### ReportStatus Enum

| 값 | 설명 |
|----|------|
| DRAFT | 백테스트 완료 시 자동 생성된 초안 |
| SUBMITTED | Agent가 제출 |
| REVIEWED | 사용자가 검토 완료 |
| ADOPTED | 전략 채택 |
| REJECTED | 전략 미채택 |
| ARCHIVED | 보관 |

### StrategyReport 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| report_id | str | 고유 ID |
| strategy_name | str | 전략명 |
| strategy_version | str | 전략 버전 |
| strategy_path | str | 전략 파일 경로 |
| status | ReportStatus | 리포트 상태 |
| submitted_at | datetime | 제출 시각 |
| submitted_by | str | 제출자 (기본: "agent") |
| backtest_period | str | 백테스트 기간 (예: "2024-01 ~ 2026-03") |
| total_return_pct | float | 총 수익률 (%) |
| total_trades | int | 총 거래 수 |
| sharpe_ratio | float \| None | 샤프 비율 |
| max_drawdown_pct | float \| None | 최대 낙폭 (%) |
| win_rate | float \| None | 승률 |
| summary | str | 전략 요약 |
| rationale | str | 전략 근거 |
| risks | str | 리스크 분석 |
| recommendations | str | 권장 사항 |
| detail_json | str | 전체 백테스트 결과 (JSON, 아래 내부 구조 참조) |
| user_notes | str | 사용자 피드백 메모 |
| reviewed_at | datetime \| None | 검토 시각 |

구현: `src/ante/report/models.py` 참조

### detail_json 내부 구조

`detail_json` 필드는 `BacktestResult.to_dict()` 결과를 JSON 직렬화한 것이다. 내부 키 구조는 다음과 같다:

> 참조: [backtest.md](../backtest/backtest.md) BacktestResult 섹션

| 키 | 타입 | 설명 |
|----|------|------|
| `strategy` | `str` | `"{name}_v{version}"` |
| `period` | `str` | `"{start_date} ~ {end_date}"` |
| `initial_balance` | `float` | 초기 자금 |
| `final_balance` | `float` | 최종 자산 |
| `total_return_pct` | `float` | 총 수익률 (%) |
| `total_trades` | `int` | 총 거래 수 |
| `metrics` | `dict` | 성과 지표 13개 ([backtest.md](../backtest/backtest.md) metrics.py 참조) |
| `equity_curve` | `list[dict]` | 자산 곡선 (`timestamp`, `equity`, `balance`) |
| `trades` | `list[dict]` | 거래 내역 (`timestamp`, `symbol`, `side`, `quantity`, `price`, `commission`, `slippage`, `reason`) |
| `config` | `dict` | 실행 설정 — BacktestConfig 직렬화 (`strategy_path`, `symbols`, `timeframe`, `start_date`, `end_date`, `initial_balance`, `buy_commission_rate`, `sell_commission_rate`, `slippage_rate`, `data_paths`) |
| `datasets` | `list[dict]` | 로드된 데이터셋 — DatasetInfo 직렬화 (`symbol`, `timeframe`, `row_count`, `start_date`, `end_date`, `data_dir`, `file_count`) |

> `config`와 `datasets`는 BacktestResult 실행 설정 포함 스펙 반영 후 추가된다. 기존 리포트에는 해당 키가 없을 수 있으며, 소비자는 `.get()` 또는 optional 처리가 필요하다.

### ReportDraftGenerator — 백테스트 초안 자동 생성

> 소스: [`src/ante/report/draft.py`](../../../src/ante/report/draft.py)

백테스트 완료 시 `BacktestCompleteEvent`를 구독하여 리포트 초안(status=DRAFT)을 자동 생성한다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `generate_draft` | result_data: dict, strategy_id: str | StrategyReport | 백테스트 결과로부터 DRAFT 리포트 생성 |

### ReportStore 인터페이스

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | 스키마(reports 테이블) 생성 |
| `submit` | report: StrategyReport | str | 리포트 제출. report_id 반환 |
| `get` | report_id: str | StrategyReport \| None | 리포트 조회 |
| `list_reports` | strategy_name?: str, status?: ReportStatus, limit: int = 20, offset: int = 0 | list[StrategyReport] | 리포트 목록 조회 (필터링) |
| `update_status` | report_id: str, status: ReportStatus, user_notes: str = "" | None | 리포트 상태 변경 (채택/미채택) |
| `delete` | report_id: str | None | 리포트 삭제 |
| `get_schema` | — | dict | 리포트 제출 스키마 반환 (Agent용, 정적 메서드) |

구현: `src/ante/report/store.py` 참조

### 리포트 제출 스키마 (Agent 참조용)

`ante report schema --format json` 으로 조회 가능한 스키마:

```json
{
  "required_fields": [
    "strategy_name", "strategy_version", "strategy_path",
    "backtest_period", "total_return_pct", "total_trades",
    "summary", "rationale"
  ],
  "optional_fields": [
    "sharpe_ratio", "max_drawdown_pct", "win_rate",
    "risks", "recommendations", "detail_json"
  ],
  "format": "JSON",
  "example": {
    "strategy_name": "momentum_breakout",
    "strategy_version": "1.0.0",
    "strategy_path": "strategies/momentum_breakout.py",
    "backtest_period": "2024-01 ~ 2026-03",
    "total_return_pct": 15.3,
    "total_trades": 42,
    "sharpe_ratio": 1.2,
    "max_drawdown_pct": -8.5,
    "win_rate": 0.58,
    "summary": "20일 이동평균 돌파 매매 전략",
    "rationale": "모멘텀 효과를 활용한 추세 추종",
    "risks": "횡보장에서 잦은 손절 발생 가능"
  }
}
```

### PerformanceFeedback — Agent 피드백 API

Agent가 전략 개선을 위해 실전/모의투자 성과를 조회하는 인터페이스.
ATLAS의 autoresearch 루프와 유사한 피드백 경로를 제공한다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `get_bot_performance` | bot_id: str | dict | 봇의 실전 성과 조회 (metrics + current_positions) |
| `get_strategy_performance` | strategy_id: str | dict | 전략의 모든 봇 성과 집계 |
| `get_trade_history` | bot_id: str, limit: int = 100 | list[dict] | 봇의 거래 이력 조회 |

구현: `src/ante/report/feedback.py` 참조

### SQLite 스키마

```sql
CREATE TABLE reports (
    report_id          TEXT PRIMARY KEY,
    strategy_name      TEXT NOT NULL,
    strategy_version   TEXT NOT NULL,
    strategy_path      TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'submitted',
    submitted_at       TEXT NOT NULL,
    submitted_by       TEXT DEFAULT 'agent',
    backtest_period    TEXT DEFAULT '',
    total_return_pct   REAL DEFAULT 0.0,
    total_trades       INTEGER DEFAULT 0,
    sharpe_ratio       REAL,
    max_drawdown_pct   REAL,
    win_rate           REAL,
    summary            TEXT DEFAULT '',
    rationale          TEXT DEFAULT '',
    risks              TEXT DEFAULT '',
    recommendations    TEXT DEFAULT '',
    detail_json        TEXT DEFAULT '{}',
    user_notes         TEXT DEFAULT '',
    reviewed_at        TEXT
);

CREATE INDEX idx_reports_strategy ON reports(strategy_name);
CREATE INDEX idx_reports_status ON reports(status);
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## 미결 사항

없음.

## 타 모듈 설계 시 참고

- **CLI 스펙**: `ante report submit/list/info/schema` 및 `ante bot performance/trades`
- **Web API 스펙**: 리포트 목록/상세 조회 + 상태 변경 (채택/미채택) API
- **Backtest 스펙**: BacktestResult를 리포트로 변환하는 유틸리티. `detail_json` 내부 구조는 `BacktestResult.to_dict()` 스펙 참조 ([backtest.md](../backtest/backtest.md))
