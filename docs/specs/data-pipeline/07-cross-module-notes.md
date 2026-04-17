# DataStore 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# 타 모듈 설계 시 참고

- **DataFeed 스펙**: DataStore를 통해 저장. §DataFeed와의 관계 참조
- **API Gateway 스펙**: LiveDataProvider가 캐시(최신) + ParquetStore(과거) 조합으로 데이터 제공
- **Backtest 스펙**: BacktestDataProvider가 ParquetStore에서 직접 읽기
- **CLI 스펙**: `ante data list/schema/storage/validate` 커맨드 구현. 데이터 주입은 `ante feed inject`로 이관. `ante data retention` CLI는 미구현
