# DataFeed 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 타 모듈 설계 시 참고

- **DataStore 스펙**: ParquetStore, Normalizer, schemas를 import하여 사용. DataFeed가 쓴 파일을 모든 소비자가 읽을 수 있다.
- **CLI 스펙**: `ante feed` 서브커맨드 등록
- **Instrument 스펙**: `instruments.parquet`에서 종목 메타데이터를 InstrumentService가 읽을 수 있다
- **Config 스펙**: API 키는 `{data}/.feed/.env`에 저장 (`ante feed config set`으로 관리, 환경변수 우선), 설정은 `{data}/.feed/config.toml`
