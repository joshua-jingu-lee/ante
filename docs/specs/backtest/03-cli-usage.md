# Backtest Engine 모듈 세부 설계 - CLI 사용법

> 인덱스: [README.md](README.md) | 호환 문서: [backtest.md](backtest.md)

# CLI 사용법

```bash
# 백테스트 실행
ante backtest run strategies/my_strategy.py \
  --start 2025-01-01 --end 2025-12-31 \
  --balance 10000000 \
  --symbols 005930,000660 \
  --timeframe 1d \
  --format json
```

`--data-path`를 생략하면 Config의 `data.path`를 사용한다. 다른 데이터셋을 검증할 때만
`--data-path <경로>`로 작업 대상 data root를 명시한다.
