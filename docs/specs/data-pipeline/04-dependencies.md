# DataStore 모듈 세부 설계 - 의존 관계

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# 의존 관계

```
ante.feed ────import───→ ante.data  (store, normalizer, schemas)
Collector ─────────────→ ante.data  (store, schemas)
Backtest Engine ───────→ ante.data  (store, schemas)
LiveDataProvider ──────→ ante.data  (store) + APIGateway (캐시)

ante.feed ✕───→ Collector          (서로 의존 없음)
ante.data ✕───→ ante.feed          (역방향 의존 없음)
```
