# DataFeed 모듈 세부 설계 - 모듈 구조

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 모듈 구조

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

### 의존성 흐름

```
ante.feed.cli ──→ config.py (FeedConfig)
  │                  │
  ├──────────────→ injector.py (FeedInjector)
  │
  ▼
pipeline/orchestrator ──────────────────────────────
  │          │           │           │            │
  ▼          ▼           ▼           ▼            ▼
sources/   transform/   ante.data   pipeline/    report/
                         · store    checkpoint   generator
                         · normalizer
                         · schemas  scheduler
```

**핵심 규칙:**
- `sources/`, `transform/`는 **서로 의존하지 않음** (orchestrator가 연결)
- **저장은 `ante.data.store.ParquetStore`를 통해서만** — 자체 Parquet 구현 없음
- **정규화는 `ante.data.normalizer`를 통해서만** — 자체 normalize 모듈 없음
- 외부 API 의존성은 `sources/` 안에만 존재
- `transform/`은 **순수 함수** — DataFrame in → DataFrame out

### 모듈별 역할

| 모듈 | 역할 |
|------|------|
| `config.py` | `FeedConfig` — 피드 디렉토리 초기화, API 키 관리(set/list/check), config.toml 생성 |
| `cli.py` | click 서브커맨드 정의 (Ante CLI에 `ante feed`로 등록). feed_init, feed_status, feed_inject, feed_config(set/list/check), feed_run(backfill/daily), feed_start |
| `cli_output.py` | CLI 출력 포맷팅 — backfill/daily 수집 결과를 text/json으로 정형화 |
| `cli_scheduler.py` | `ante feed start` 상주 스케줄러 — daily_at/backfill_at 시각에 수집 자동 실행, SIGTERM 안전 종료 |
| `injector.py` | `FeedInjector` — CSV 파일/DataFrame → Normalizer → validate → ParquetStore.write() |
| `models/result.py` | `CollectionResult` dataclass (성공/실패/경고 집계), `ValidationResult` dataclass (검증 결과, merge 지원) |
| `sources/base.py` | `DataSource` Protocol (runtime_checkable), `RateLimiter` (Token Bucket + 일일 한도) |
| `sources/data_go_kr.py` | `DataGoKrSource` — data.go.kr API 호출, 페이지네이션, HTTP 200 에러 처리, Exponential Backoff |
| `sources/dart.py` | `DARTSource` — DART API 호출, corp_code ZIP 다운로드/파싱, fnlttMultiAcnt 다중회사 배치 |
| `transform/validate.py` | `validate_transport`, `validate_syntax`, `validate_schema`, `validate_business`, `validate_all` — 4계층 검증 |
| `pipeline/orchestrator.py` | `FeedOrchestrator` — ETL 진입점, lock 파일 관리, 가드 평가, 리포트 저장. BackfillRunner/DailyRunner에 위임 |
| `pipeline/backfill_runner.py` | `BackfillRunner` — backfill 모드 ETL 실행. 날짜별 루프, 체크포인트 관리, 소스별 수집 오케스트레이션 |
| `pipeline/daily_runner.py` | `DailyRunner` — daily 모드 ETL 실행. 전일 1일치 수집 |
| `pipeline/data_go_kr_collector.py` | `DataGoKrCollector` — data.go.kr 수집 + DataGoKrNormalizer로 정규화 + 검증 + ParquetStore 저장 |
| `pipeline/dart_collector.py` | `DARTCollector` — DART 수집 + corp_code 매핑 관리 + 분기별 재무제표 저장 |
| `pipeline/indicator_calculator.py` | `IndicatorCalculator` — fundamental 데이터에서 PER/PBR/EPS/BPS/ROE/부채비율 파생 지표 계산 |
| `pipeline/checkpoint.py` | `Checkpoint` — JSON 체크포인트 load/save/get_last_date (write-then-rename 원자적 기록) |
| `pipeline/scheduler.py` | `generate_backfill_dates`, `generate_daily_date`, `is_business_day` — 모드별 날짜 범위 생성 |
| `report/generator.py` | `ReportGenerator` — generate(CollectionResult → dict), save(JSON 파일), list_reports(최근 리포트 목록) |
