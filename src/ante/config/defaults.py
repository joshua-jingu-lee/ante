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
    # ── 리스크 관리 ──
    "rule.daily_loss_limit": 0.05,
    "rule.max_exposure_percent": 0.20,
    "rule.max_unrealized_loss": 0.10,
    "rule.max_trades_per_hour": 10,
    "rule.allowed_hours": "09:00-15:30",
    "risk.max_mdd_pct": 0.10,
    "risk.max_position_pct": 0.10,
    # ── 봇 기본 ──
    "bot.default_interval_sec": 60,
    # ── 거래 비용 ──
    "broker.commission_rate": 0.00015,
    "broker.sell_tax_rate": 0.0018,
    # ── 알림 ──
    "notification.telegram_enabled": "true",
    "notification.telegram_level": "important",
    "notification.fill_alert": "true",
    "notification.daily_report": "true",
}
