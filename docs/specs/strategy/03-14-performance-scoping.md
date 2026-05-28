# Strategy 모듈 세부 설계 - 설계 결정 - 성과 추적의 scoping

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 성과 추적의 scoping

전략 정의는 글로벌이지만, 성과·거래 기록은 계좌별로 분리 추적된다. `ante strategy performance` 는 `--account-id` 를 semantic-required 로 받으며 (미지정 시 `STRATEGY_MISSING_REQUIRED_ACCOUNT` 에러, SSOT: `src/ante/cli/commands/strategy.py`), 지정 계좌에서의 모든 봇 성과를 집계한다.

```bash
# 계좌별 성과 조회 (semantic-required)
ante strategy performance momentum_breakout --account-id domestic
# → domestic 계좌에서의 성과만 (해당 계좌에서 이 전략을 사용한 모든 봇 집계)
```

성과 집계는 항상 단일 계좌 scope 에서 수행하여 통화 차이로 인한 합산 오류를 차단한다. 통화가 다른 계좌 간 성과를 단순 합산하지 않으며, 여러 계좌의 성과를 비교하려면 호출자가 각 계좌별로 명령을 반복 호출한다.
