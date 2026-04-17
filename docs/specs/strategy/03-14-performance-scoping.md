# Strategy 모듈 세부 설계 - 설계 결정 - 성과 추적의 scoping

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 성과 추적의 scoping

전략 정의는 글로벌이지만, 성과·거래 기록은 계좌별로 분리 추적된다.

```bash
# 계좌별 성과 조회
ante strategy performance momentum_breakout --account domestic
# → domestic 계좌에서의 성과만

ante strategy performance momentum_breakout
# → 전 계좌 합산 (각 계좌별 통화로 개별 표시)
```

성과 집계 시 `account_id`로 그룹핑하여 계좌별 수익률, MDD 등을 독립 산출한다. 통화가 다른 계좌 간 성과를 단순 합산하지 않는다.
