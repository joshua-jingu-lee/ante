"""Config 기본값 상수."""

DEFAULTS: dict[str, object] = {
    "system.log_level": "INFO",
    "system.timezone": "Asia/Seoul",
    "db.path": "db/ante.db",
    "db.event_log_retention_days": 30,
    "parquet.base_path": "data/",
    "parquet.compression": "snappy",
    "web.host": "0.0.0.0",
    "web.port": 8000,
    "eventbus.history_size": 1000,
    "instrument.default_exchange": "KRX",
    "broker.commission_rate": 0.00015,
    "broker.sell_tax_rate": 0.0023,
    "treasury.sync_interval_seconds": 300,
}
