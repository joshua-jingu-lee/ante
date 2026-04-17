# Instrument 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/instrument/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md), [notification.md](../notification/notification.md) 종목명 병기, [cli.md](../cli/cli.md) instrument 커맨드

## 개요

Instrument 모듈은 **종목 마스터 데이터를 중앙 관리하는 모듈**이다.
종목코드(symbol)와 거래소(exchange)를 복합 키로 관리하며, 종목명·유형 등 메타데이터를 제공한다.

**주요 기능:**
- **Instrument 모델**: 종목 메타데이터 불변 객체 (frozen dataclass)
- **InstrumentService**: 전체 종목 메모리 캐시 + SQLite 영속화
- **CLI**: `ante instrument list`, `ante instrument search`

## 설계 결정

### 복합 PK (symbol, exchange)

동일 종목코드가 거래소별로 다른 종목을 가리킬 수 있다. 복수 거래소 지원을 위해 `(symbol, exchange)` 복합 PK를 사용한다.

### TTL 기반 메모리 캐시

한국 상장 종목 ~2,500개는 전체를 메모리에 적재해도 합리적인 수준이다.
`initialize()` 시 전체 로드 후 `bulk_upsert()` 시 캐시도 즉시 갱신한다.
`get_name()`은 동기 메서드로 제공하여 알림 핸들러 등에서 `await` 없이 호출 가능하다.

캐시는 `cache_ttl_seconds` (기본 3600초) 경과 후 자동 만료되며, 다음 조회 시 DB에서 재로드된다.
`time.monotonic()` 기반으로 캐시 로드 시각을 추적한다.

### exchange 기본값 "KRX"

모든 symbol 관련 필드/파라미터에 `exchange: str = "KRX"` 기본값을 사용하여 하위 호환성을 보장한다.

## Instrument 모델

```python
@dataclass(frozen=True)
class Instrument:
    symbol: str           # 종목코드 (예: "005930")
    exchange: str         # 거래소 (예: "KRX")
    name: str = ""        # 한글명 (예: "삼성전자")
    name_en: str = ""     # 영문명 (예: "Samsung Electronics")
    instrument_type: str = ""  # 유형 (예: "stock", "etf", "etn")
    logo_url: str = ""    # 로고 이미지 URL
    listed: bool = True   # 상장 여부
    updated_at: str = ""  # 마지막 갱신 시각 (datetime string)
```

## DB 스키마

```sql
CREATE TABLE IF NOT EXISTS instruments (
    symbol           TEXT NOT NULL,
    exchange         TEXT NOT NULL,
    name             TEXT DEFAULT '',
    name_en          TEXT DEFAULT '',
    instrument_type  TEXT DEFAULT '',
    logo_url         TEXT DEFAULT '',
    listed           INTEGER DEFAULT 1,
    updated_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, exchange)
);
CREATE INDEX IF NOT EXISTS idx_instruments_name ON instruments(name);
```

## InstrumentService

**생성자 파라미터:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `db` | Database | (필수) | SQLite 연결 인스턴스 |
| `cache_ttl_seconds` | float | 3600.0 | 캐시 TTL (초). 이 시간 경과 후 다음 조회 시 DB에서 재로드 |

**메서드:**

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | 스키마 생성 + 전체 캐시 워밍 |
| `get` | symbol: str, exchange: str = "KRX" | Instrument \| None | 캐시에서 조회 |
| `get_name` | symbol: str, exchange: str = "KRX" | str | 동기 종목명 조회. 캐시 미스 또는 name이 빈 문자열이면 symbol 반환 |
| `search` | keyword: str, limit: int = 20, listed_only: bool = False | list[Instrument] | name, name_en, symbol LIKE 검색. listed_only=True이면 상장 종목만 반환 |
| `bulk_upsert` | instruments: list[Instrument] | int | 대량 등록/갱신 + 캐시 갱신. 처리 건수 반환 |

구현: `src/ante/instrument/service.py` 참조

## CLI 커맨드

### `ante instrument list`

```
ante instrument list [--exchange KRX] [--type stock|etf|etn...] [--listed-only] [--db-path db/ante.db]
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--exchange` | KRX | 거래소 필터 |
| `--type` | (없음) | 종목 유형 필터 |
| `--listed-only` | False | 상장 종목만 표시 |
| `--db-path` | db/ante.db | DB 경로 |

출력 컬럼: `symbol`, `name`, `name_en`, `type`, `listed`

### `ante instrument search <keyword>`

```
ante instrument search <keyword> [--limit 20] [--listed-only] [--db-path db/ante.db]
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--limit` | 20 | 최대 결과 수 |
| `--listed-only` | False | 상장 종목만 검색 |
| `--db-path` | db/ante.db | DB 경로 |

출력 컬럼: `symbol`, `exchange`, `name`, `name_en`, `type`

### `ante instrument sync`

```
ante instrument sync [--exchange KRX] [--db-path db/ante.db]
```

KIS API에서 종목 마스터 데이터를 조회하여 DB에 동기화한다.

### `ante instrument import <filepath>`

```
ante instrument import <filepath> [--dry-run] [--db-path db/ante.db]
```

CSV/JSON 파일에서 종목 데이터를 일괄 등록/갱신한다. 파일 확장자로 형식을 자동 감지한다. `--dry-run` 옵션으로 실제 반영 없이 미리 확인 가능.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## 미결 사항

없음.

## 타 모듈 설계 시 참고

- **Notification**: `NotificationService`에 `instrument_service` 주입 시 체결 알림에 종목명 병기
- **Data Pipeline**: 시세 데이터 수집 시 종목 메타데이터도 함께 갱신하는 설계 고려
- **Web API**: 종목 검색 API — `/api/instruments/search?q=삼성`
