# Strategy 모듈 세부 설계 - 설계 결정 - 백테스트와의 관계

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 백테스트와의 관계

백테스트는 계좌 없이 독립 실행 가능하다. Data Store에서 `exchange/symbol/timeframe`으로 데이터를 직접 조회한다.

```bash
# 계좌 없이 백테스트 (exchange는 전략 메타에서 추론)
ante backtest run strategies/momentum.py \
  --start 2025-01-01 --end 2025-12-31

# exchange를 명시적으로 지정 (전략 메타와 다른 시장으로 테스트)
ante backtest run strategies/universal_ma.py \
  --start 2025-01-01 --end 2025-12-31 \
  --exchange NYSE --symbols AAPL,MSFT
```

`exchange="*"` 전략은 `--exchange` 옵션으로 백테스트할 시장을 자유롭게 지정할 수 있다.

> canonical exchange 계약 SSOT: [core.md `## Canonical Exchange Vocabulary`](../core/core.md#canonical-exchange-vocabulary).
> backtest `--exchange` override의 목표 계약은 canonical-only·`*` 거부이나, 현재 CLI/`src/ante/backtest/`에
> 미구현된 spec-vs-implementation gap이다. 옵션 신설 포함 정렬은 #1578에서 다룬다.
