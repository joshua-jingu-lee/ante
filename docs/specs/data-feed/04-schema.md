# DataFeed 모듈 세부 설계 - 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 스키마

DataFeed는 `ante.data.schemas`를 직접 import하여 사용한다. 스키마를 내부에 별도 정의하지 않는다.

**OHLCV**: [data-pipeline.md](../data-pipeline/data-pipeline.md) §OHLCV_SCHEMA 참조.

**FUNDAMENTAL**: [data-pipeline.md](../data-pipeline/data-pipeline.md) §FUNDAMENTAL_SCHEMA 참조.

**INSTRUMENTS** (`{data}/.feed/instruments.parquet`):

수집 과정에서 확보한 종목 메타데이터. Ante의 `InstrumentService`가 읽어서 `instruments` 테이블에 반영할 수 있다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `symbol` | Utf8 | 종목코드 (6자리) |
| `exchange` | Utf8 | 거래소 (KRX 등) |
| `name` | Utf8 | 종목명 (한글) |
| `market` | Utf8 | 시장구분 (KOSPI/KOSDAQ/KONEX) |

> data.go.kr 수집 시 `srtnCd`(symbol), `itmsNm`(name), `mrktCtg`(market)를 함께 받아오므로 추가 호출 없이 갱신.
> 수집할 때마다 덮어쓰기하여 최신 상태 유지.

### 파일 규격

| 항목 | 규칙 |
|------|------|
| 형식 | Parquet (snappy 압축) |
| 디렉토리 | `data/{data_type}/{exchange}/{timeframe}/{symbol}/{YYYY-MM}.parquet` |
| 파티셔닝 | 1m 이상: 월별, 10s/30s: 일별 (YYYY-MM-DD) |
| 쓰기 방식 | `ParquetStore.write()` 호출 (파티션 단위 overwrite — 멱등성 보장) |
| 정렬 | timestamp/date 오름차순 |
| 중복 | 동일 timestamp 행 없을 것 |
| 타임존 | UTC |
