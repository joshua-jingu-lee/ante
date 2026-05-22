"""Rule configuration update helpers shared by CLI and IPC."""

from __future__ import annotations

from typing import Any


def account_rules_config_key(account_id: str) -> str:
    """Return the dynamic config key for account-scoped stored rules."""
    return f"accounts.{account_id}.rules"


def rule_config_to_item(cfg: dict[str, Any]) -> dict[str, Any]:
    """Convert a stored rule config dict to the public rule item shape."""
    params = {k: v for k, v in cfg.items() if k not in ("type", "id", "enabled")}
    return {
        "type": cfg.get("type", ""),
        "enabled": cfg.get("enabled", True),
        "params": params,
    }


def item_to_rule_config(
    rule_type: str, enabled: bool, params: dict[str, Any]
) -> dict[str, Any]:
    """Convert a public rule item shape to the stored rule config dict."""
    cfg: dict[str, Any] = {"type": rule_type, "enabled": enabled}
    cfg.update(params)
    return cfg


async def update_account_rule_config(
    *,
    account_service: Any,
    dynamic_config: Any,
    account_id: str,
    rule_type: str,
    enabled: bool,
    params: dict[str, Any],
    changed_by: str,
    config: Any | None = None,
    audit_logger: Any | None = None,
) -> dict[str, Any]:
    """Validate and persist one account-scoped stored rule override.

    It stores the full ``accounts.{account_id}.rules`` list through
    ``DynamicConfigService`` so
    ``ConfigChangedEvent`` and dynamic config history remain the single mutation
    path.
    """
    from ante.rule.engine import RULE_REGISTRY

    await account_service.get(account_id)

    if rule_type not in RULE_REGISTRY:
        raise ValueError(
            f"알 수 없는 룰 타입: {rule_type!r}. "
            f"가능한 값: {list(RULE_REGISTRY.keys())}"
        )

    rule_class = RULE_REGISTRY[rule_type]
    validation_errors = rule_class.validate_config(params)
    if validation_errors:
        raise ValueError(f"룰 config 검증 실패: {'; '.join(validation_errors)}")

    key = account_rules_config_key(account_id)
    raw_rules: list[dict[str, Any]] = []

    try:
        value = await dynamic_config.get(key)
        if isinstance(value, list):
            raw_rules = value
    except Exception:
        raw_rules = []

    if not raw_rules and config is not None and hasattr(config, "get"):
        value = config.get(key)
        if isinstance(value, list):
            raw_rules = list(value)

    new_config = item_to_rule_config(rule_type, enabled, params)
    for index, cfg in enumerate(raw_rules):
        if cfg.get("type") == rule_type:
            raw_rules[index] = new_config
            break
    else:
        raw_rules.append(new_config)

    await dynamic_config.set(key, raw_rules, category="rule", changed_by=changed_by)

    if audit_logger is not None:
        await audit_logger.log(
            member_id=changed_by,
            action="account.rule.update",
            resource=f"account:{account_id}:rule:{rule_type}",
            detail=f"rule update: {rule_type} enabled={enabled}",
            ip="",
        )

    return {
        "account_id": account_id,
        "rule_type": rule_type,
        "rule": rule_config_to_item(new_config),
    }
