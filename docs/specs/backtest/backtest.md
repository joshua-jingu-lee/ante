# Backtest Engine 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/backtest/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 백테스트, D-004, [strategy.md](../strategy/strategy.md) 전략 인터페이스

이 문서는 분할된 `backtest` 스펙의 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
최신 계약 SSOT는 [README.md](README.md)의 문서 목록과 주제별 하위 문서다.
새 계약, 결정, 미결 사항은 이 파일에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-cli-usage.md](03-cli-usage.md) | CLI 사용법 |
| [05-cross-module-notes.md](05-cross-module-notes.md) | 타 모듈 설계 시 참고 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 설계 결정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### Subprocess 격리 (D-004)

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### BacktestDataProvider — Parquet 기반 과거 데이터

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### BacktestExecutor — 시뮬레이션 실행

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### BacktestResult — 결과 데이터

상세 내용: [02-design-decisions.md](02-design-decisions.md)

#### BacktestConfig — 실행 설정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

#### DatasetInfo — 로드된 데이터셋 정보

상세 내용: [02-design-decisions.md](02-design-decisions.md)

#### to_dict() 직렬화

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 성과 지표 계산 (metrics.py)

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### BacktestService — 메인 프로세스 측 관리

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### BacktestStrategyContext

상세 내용: [02-design-decisions.md](02-design-decisions.md)

## CLI 사용법

상세 내용: [03-cli-usage.md](03-cli-usage.md)


## 타 모듈 설계 시 참고

상세 내용: [05-cross-module-notes.md](05-cross-module-notes.md)
