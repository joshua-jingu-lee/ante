# Ante 시스템 구성도와 런타임 흐름

> 인덱스: [README.md](README.md) | 모듈 책임: [module-map.md](module-map.md)

## 시스템 구성도

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Single asyncio Process                         │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 EventBus (asyncio.Queue)                       │  │
│  │       publish(event) / subscribe(event_type, handler)          │  │
│  └─────┬──────────┬──────────┬─────────────────────────────────┘   │
│        │          │          │                                      │
│  ┌─────▼──────┐ ┌─▼────────┐ ┌▼───────┐                            │
│  │ BotManager │ │ Treasury │ │ Rule   │                            │
│  │            │ │          │ │ Engine │                            │
│  │ ┌────────┐ │ │ central  │ │ global │                            │
│  │ │ Bot A  │ │ │ balance  │ │ +      │                            │
│  │ │ (StgA) │ │ │ bot      │ │ per-   │                            │
│  │ ├────────┤ │ │ budget   │ │ stg    │                            │
│  │ │ Bot B  │ │ │ alloc    │ │        │                            │
│  │ │ (StgB) │ │ └─────────┘ └────────┘                            │
│  │ ├────────┤ │                                                     │
│  │ │ Bot C  │ │ ┌──────────────────────────────────────────┐        │
│  │ │ (paper)│ │ │ APIGateway (Rate Limiter)                │        │
│  │ └────────┘ │ │  - request queueing, caching, throttle   │        │
│  └────────────┘ │  - bot request merging                   │        │
│                  └──────────────────┬───────────────────────┘        │
│                                     │                                │
│  ┌──────────────────────────────────▼──────────────────────────┐    │
│  │ BrokerAdapter (interface)                                    │    │
│  │  └── KISAdapter (impl)                                       │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│  │ WebAPI       │ │ Notification │ │ Strategy     │ │ Approval   │ │
│  │ (FastAPI)    │ │ Adapter      │ │ Registry +   │ │ (결재)     │ │
│  │              │ │  └─ Telegram │ │ ReportStore  │ │            │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────┘ │
│                                                                     │
│  ┌──────────────┐ ┌──────────────────────────────────────────────┐ │
│  │ IPC Server   │ │ ServiceRegistry                              │ │
│  │ (Unix socket)│ │  서버 서비스 인스턴스 컨테이너                │ │
│  │  └─ CLI 런타 │ │  WebAPI·IPC 공용                             │ │
│  │    임 커맨드  │ │                                              │ │
│  └──────────────┘ └──────────────────────────────────────────────┘ │
│                                                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                 │
│  │ Instrument   │ │ Member       │ │ Audit        │                 │
│  │ (종목 마스터)│ │ (인증/권한)  │ │ (감사 로그)  │                 │
│  └──────────────┘ └──────────────┘ └──────────────┘                 │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ [7] DataStore (데이터 저장 인프라) ─ 유일한 Parquet 접근 계층 │   │
│  │  ParquetStore · Normalizer · Catalog · Retention             │   │
│  │  Collector (실시간) · Injector (수동 주입)                    │   │
│  ├╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶┤   │
│  │ [8] DataFeed (배치 수집) ─ DataStore를 통해 저장              │   │
│  │  data.go.kr / DART / pykrx → ETL → ParquetStore에 쓰기      │   │
│  │  내장 스케줄러 (backfill + daily)                             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶╶  │
│  ┌──────────────────┐ ┌──────────────────┐                          │
│  │ Config           │ │ Database         │  ← 공통 인프라           │
│  │ (TOML/env/SQLite)│ │ (SQLite WAL)     │                          │
│  └──────────────────┘ └──────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │ Web                │ CLI (IPC)          │ REST API (향후)
         │                    │ Unix socket        │
   ┌─────┴──────┐     ┌──────┴───────┐    ┌───────┴───────┐
   │ 사용자      │     │ AI Agent     │    │ AI Agent      │
   │ (대시보드)  │     │ (전략 개발)   │    │ (자동화)      │
   └────────────┘     └──────────────┘    └───────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                Backtest Engine (subprocess)                          │
│  - on-demand start, exit on complete                                │
│  - reads Parquet via DataStore (ParquetStore)                       │
│  - writes results to file/DB                                        │
│  - notifies main process on completion                              │
└─────────────────────────────────────────────────────────────────────┘
```

## 데이터 계층 구조

DataStore와 DataFeed는 "저장 인프라"와 "수집 파이프라인"으로 역할이 분리된다.

```
┌─────────────────────────────────────────────────────────────────┐
│                  DataStore (ante.data) — 저장 인프라              │
│                                                                   │
│  schemas.py ─── 스키마 정의 (유일한 원본)                         │
│  store.py ───── ParquetStore (유일한 Parquet 읽기/쓰기 계층)      │
│  normalizer.py─ 모든 소스의 Normalizer 통합                      │
│                  (KIS, Yahoo, DataGoKr, DART, Default)            │
│  catalog.py ─── 데이터 탐색 API                                  │
│  retention.py ─ 보존 정책                                        │
│  injector.py ── 외부 데이터 수동 주입 (CSV 등)                    │
│  collector.py ─ 실시간 데이터 수집 (APIGateway 경유)              │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              Parquet 저장소 (data/)                           │ │
│  │   ohlcv/ · fundamental/ · tick/ · flow/ · event/             │ │
│  └─────────────────────────────────────────────────────────────┘ │
└───────▲───────────────▲───────────────▲───────────────▲─────────┘
        │ write          │ write          │ read          │ read
        │                │                │               │
   DataFeed         Collector      Backtest Engine   DataProvider
   (배치 수집)      (실시간 수집)   (subprocess)     (전략 데이터)
```

### 의존 방향

```
ante.feed ────import───→ ante.data  (store, normalizer, schemas)
Collector ─────────────→ ante.data  (store, schemas)
Backtest Engine ───────→ ante.data  (store, schemas)
LiveDataProvider ──────→ ante.data  (store) + APIGateway (캐시)

ante.feed ✕───→ Collector          (서로 의존 없음)
ante.data ✕───→ ante.feed          (역방향 의존 없음)
```

### 쓰기 소유권

같은 Parquet 파티션에 복수 모듈이 동시에 쓰면 데이터 유실 위험이 있다.
타임프레임·데이터 유형별로 **쓰기 소유권을 단일 모듈에 고정**하여 충돌을 원천 차단한다.

| 데이터 | 쓰기 소유자 | 쓰기 방식 | 근거 |
|--------|-----------|----------|------|
| OHLCV 일봉 (`1d`) | DataFeed | 파티션 덮어쓰기 | data.go.kr에서 완전한 일봉을 수집, 더 높은 신뢰도 |
| OHLCV 분봉 (`1m`, `5m` 등) | Collector | append/merge | 실시간으로만 수집 가능, KIS API 경유 |
| `fundamental`, `flow`, `event` | DataFeed | 파티션 덮어쓰기 | 외부 API 배치 수집 전용 |
| `tick` | Collector | append | 실시간 전용 |

**읽기는 제한 없음** — 모든 소비자(Backtest, DataProvider, Strategy, CLI)가 ParquetStore.read()로 통합 조회한다.

## 통신 방식

- **EventBus (1:N broadcast)**: 주문 흐름, 시스템 이벤트, 알림 등 1:N 성격의 통신. 이벤트 타입 목록은 [specs/eventbus/eventbus.md](../specs/eventbus/eventbus.md) 참조.
- **직접 호출 (1:1 request-response)**: 데이터 조회, 자금 확인, 설정 읽기 등 요청-응답 성격의 호출. 각 모듈 스펙 참조.

## 주문 처리 흐름

```
Bot -> OrderRequestEvent -> [EventBus]
  -> [RuleEngine] global + per-stg validation
    -> OrderValidatedEvent -> [EventBus]
      -> [Treasury] check & reserve funds
        -> OrderApprovedEvent -> [EventBus]
          -> [APIGateway] rate limit queue
            -> [BrokerAdapter] execute order
              -> OrderFilledEvent -> [EventBus]
                -> [Bot] update position
                -> [Treasury] update balance
                -> [Notification] send alert
```
