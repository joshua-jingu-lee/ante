# Account 모듈 세부 설계 - config/defaults.py 마이그레이션

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# config/defaults.py 마이그레이션

Account 도입 시 기존 시스템 레벨 설정 중 계좌로 이동해야 할 항목을 정리한다.

### Account로 이동하는 설정

| 현재 키 | 현재 값 | Account 필드 | 비고 |
|---------|--------|-------------|------|
| `system.timezone` | `"Asia/Seoul"` | `timezone` | 거래소별 시간대 |
| `instrument.default_exchange` | `"KRX"` | `exchange` | 계좌별 거래소 |
| `broker.commission_rate` | `0.00015` | `buy_commission_rate` | 계좌별 매수 수수료 |
| `broker.sell_tax_rate` | `0.0023` | `sell_commission_rate`에 합산 | 매도 수수료에 세금 포함 |

### 시스템 레벨에 유지하는 설정

| 키 | 이유 |
|----|------|
| `system.log_level` | 시스템 전역 로깅 |
| `db.path` | 단일 DB |
| `db.event_log_retention_days` | 시스템 전역 정책 |
| `parquet.base_path`, `parquet.compression` | 독립 모듈 (Data Store) |
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
