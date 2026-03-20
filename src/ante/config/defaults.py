"""Config 기본값 상수."""

DEFAULTS: dict[str, object] = {
    "system.log_level": "INFO",
    "system.timezone": "Asia/Seoul",
    "db.path": "db/ante.db",
    "db.event_log_retention_days": 30,
    "parquet.base_path": "data/",
    "parquet.compression": "snappy",
    "web.host": "0.0.0.0",
    "web.port": 3982,
    "eventbus.history_size": 1000,
    "member.token_ttl_days": 90,
    "instrument.cache_ttl_seconds": 3600,
    "treasury.sync_interval_seconds": 300,
    "audit.retention_days": 90,
    "telegram.command.polling_interval": 3.0,
    "telegram.command.confirm_timeout": 30.0,
}
