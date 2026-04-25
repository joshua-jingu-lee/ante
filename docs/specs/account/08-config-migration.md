# Account 모듈 세부 설계 - config/defaults.py 마이그레이션

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# config/defaults.py 마이그레이션

Account 도입 시 기존 시스템 레벨 설정 중 계좌로 이동해야 할 항목을 정리한다.
이 문서는 broker-to-account migration mapping의 SSOT다. Config 모듈 문서는
legacy `[broker]` 설정의 출처만 설명하고, 이관 후 필드명은 본 문서를 따른다.

### 표준 Account 필드

이관 후 Account API/DB/모델은 다음 필드명만 표준으로 사용한다.

| 영역 | Canonical Account field | 비고 |
|------|-------------------------|------|
| 인증 정보 | `credentials` | 암호화 저장되는 JSON |
| 브로커 동작 설정 | `broker_config` | 예: KIS `is_paper` |
| 매수 비용 | `buy_commission_rate` | 매수 수수료율 |
| 매도 비용 | `sell_commission_rate` | 세금 포함 매도 총 비용률 |

`credentials_ref`, `commission_rate`, `sell_tax_rate`는 Account API/DB 필드가 아니다.
필요한 경우 legacy 설정을 읽는 migration tool의 입력/source 용어로만 사용한다.

### Account로 이동하는 설정

| Legacy source | 현재 값 | Canonical Account field | 이관 규칙 |
|---------------|--------|-------------------------|-----------|
| `system.timezone` | `"Asia/Seoul"` | `timezone` | 거래소별 시간대 기본값 |
| `instrument.default_exchange` | `"KRX"` | `exchange` | 계좌별 거래소 기본값 |
| `broker.type` | - | `broker_type` | 계좌별 브로커 어댑터 유형 |
| `broker.commission_rate` | `0.00015` | `buy_commission_rate` | 매수 수수료율로 이관 |
| `broker.commission_rate` + `broker.sell_tax_rate` | `0.00015` + `0.0023` | `sell_commission_rate` | 매도 수수료율은 세금 포함 총 비용률로 산정 |
| `secrets.env`의 `KIS_*` | - | `credentials` | migration tool이 읽어 Account credentials JSON으로 암호화 저장 |

`broker.sell_tax_rate`는 이관 후 독립 Account 필드로 남지 않는다. 국내 주식처럼 매도
세금이 있는 시장에서는 migration tool이 legacy 매도 세금 값을 `sell_commission_rate`
산정에 반영한다.

### 시스템 레벨에 유지하는 설정

| 키 | 이유 |
|----|------|
| `system.log_level` | 시스템 전역 로깅 |
| `db.path` | 단일 DB |
| `db.event_log_retention_days` | 시스템 전역 정책 |
| `data.path`, `parquet.compression` | 독립 모듈 (Data Store). `parquet.base_path`는 legacy alias |
| `web.host`, `web.port` | 단일 웹 서버 |
| `eventbus.history_size` | 시스템 인프라 |
| `member.token_ttl_days` | Member는 Account 밖 |
| `treasury.sync_interval_seconds` | 브로커 어댑터 내부에서 관리 |
| `instrument.cache_ttl_seconds` | 캐시 정책 |
| `audit.retention_days` | 시스템 전역 규정 |
| `telegram.command.*` | 알림은 글로벌 |

### 삭제 또는 Account 파생으로 전환하는 설정

| 키 | 처리 |
|----|------|
| `broker.retry.*` | BrokerAdapter 내부 상수로 유지 (broker_type별 고정값) |
| `broker.circuit_breaker.*` | 동일 |
| `broker.timeout.*` | 동일 |
