# DataStore 모듈 세부 설계 - DataFeed와의 관계

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# DataFeed와의 관계

DataFeed([data-feed.md](../data-feed/data-feed.md))는 외부 공공 API에서 과거 데이터를 배치 수집하는 ETL 파이프라인이다.
DataStore의 하위 소비자로서, 자체 Parquet 구현 없이 DataStore를 통해 저장한다.

- **스키마**: DataFeed는 `ante.data.schemas`를 직접 import — 스키마 이중 정의 없음
- **정규화**: DataFeed는 `ante.data.normalizer`의 `DataGoKrNormalizer`, `DARTNormalizer`를 사용
- **저장**: DataFeed는 `ante.data.store.ParquetStore.write()`를 호출하여 저장
- **쓰기 소유권**: 일봉(`1d`)과 `fundamental` 등은 DataFeed가 소유, 분봉은 Collector가 소유 (§쓰기 소유권 참조)
