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

`backtest run`에서 `--symbols`를 생략하면(내부적으로 빈 목록) `StrategyMeta.symbols`로 fallback하고, `--timeframe`를 생략하면 `StrategyMeta.timeframe`로 fallback한다. 명시한 `--symbols`/`--timeframe`는 meta보다 우선한다. CLI와 meta 모두 종목이 없으면 에러가 아니라 경고와 함께 0-step으로 끝난다.

> canonical exchange 계약 SSOT: [core.md `## Canonical Exchange Vocabulary`](../core/core.md#canonical-exchange-vocabulary).
> backtest `--exchange` override의 목표 계약은 canonical-only·`*` 거부이나, 현재 CLI/`src/ante/backtest/`에
> 미구현된 spec-vs-implementation gap이다. 옵션 신설 포함 정렬은 #1578에서 다룬다.
