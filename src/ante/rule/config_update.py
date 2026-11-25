"""Rule configuration update helpers shared by CLI and IPC."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ante.eventbus.events import NotificationEvent

logger = logging.getLogger(__name__)

_ACCOUNT_RULES_KEY_PREFIX = "accounts."
_ACCOUNT_RULES_KEY_SUFFIX = ".rules"
RULE_ITEM_KEYS: frozenset[str] = frozenset({"type", "id", "enabled"})


def account_rules_config_key(account_id: str) -> str:
    """Return the dynamic config key for account-scoped stored rules."""
    return f"{_ACCOUNT_RULES_KEY_PREFIX}{account_id}{_ACCOUNT_RULES_KEY_SUFFIX}"


def is_account_rules_config_key(key: str) -> bool:
    """Return whether ``key`` has the ``accounts.<account_id>.rules`` shape."""
    return (
        key.startswith(_ACCOUNT_RULES_KEY_PREFIX)
        and key.endswith(_ACCOUNT_RULES_KEY_SUFFIX)
        and len(key) >= len(_ACCOUNT_RULES_KEY_PREFIX) + len(_ACCOUNT_RULES_KEY_SUFFIX)
    )


def rule_config_to_item(cfg: dict[str, Any]) -> dict[str, Any]:
    """Convert a stored rule config dict to the public rule item shape."""
    params = {k: v for k, v in cfg.items() if k not in RULE_ITEM_KEYS}
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


def _reject_rule_item_keys(params: dict[str, Any]) -> None:
    """Reject params that would overwrite the rule item's own keys."""
    reserved = sorted(params.keys() & RULE_ITEM_KEYS)
    if reserved:
        raise ValueError(
            "params에 규칙 항목 key를 줄 수 없습니다: "
            f"{', '.join(repr(k) for k in reserved)}. "
            "규칙 종류는 명령의 인자(rule_type)로, 켜고 끄기는 "
            "--enabled/--disabled(IPC enabled)로 지정합니다. id는 바꿀 수 없습니다."
        )


def _priority_errors(params: dict[str, Any]) -> list[str]:
    """Return the error for a non-integer ``priority`` param."""
    if "priority" not in params:
        return []
    value = params["priority"]
    if isinstance(value, int) and not isinstance(value, bool):
        return []
    return ["priority must be an integer"]


def _is_unwritable(
    index: int, item: Any, is_first: bool, create_rule: Callable[..., Any]
) -> bool:
    """Return whether a stored dict item blocks and ``rule update`` cannot fix it."""
    if is_first:
        return False
    try:
        rule = create_rule(item)
    except Exception:
        rule_type = item.get("type")
        logger.debug(
            "저장된 규칙 항목을 규칙으로 만들 수 없다고 판정: index=%d, rule_type=%s",
            index,
            rule_type if isinstance(rule_type, str) else None,
            exc_info=True,
        )
        return True
    if rule is None or "priority" not in item:
        return False
    return not isinstance(item["priority"], (int, float))


def _drop_unwritable_items(
    raw_rules: list[Any], create_rule: Callable[..., Any]
) -> tuple[list[Any], list[tuple[int, Any]]]:
    """Split stored items into kept items and dropped ``(index, item)`` pairs."""
    kept: list[Any] = []
    dropped: list[tuple[int, Any]] = []
    seen_types: set[Any] = set()
    for index, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            dropped.append((index, item))
            continue
        rule_type = item.get("type")
        try:
            is_first = rule_type not in seen_types
        except TypeError:
            dropped.append((index, item))
            continue
        seen_types.add(rule_type)
        if _is_unwritable(index, item, is_first, create_rule):
            dropped.append((index, item))
            continue
        kept.append(item)
    return kept, dropped


def _describe_dropped(dropped: list[tuple[int, Any]]) -> str:
    """Describe dropped items by position and type names only, never values."""
    parts = []
    for index, item in dropped:
        field = item.get("type") if isinstance(item, dict) else None
        type_name = type(field).__name__ if isinstance(item, dict) else "-"
        rule_type = field if isinstance(field, str) else None
        parts.append(
            f"index={index} item={type(item).__name__} type={type_name} "
            f"rule_type={rule_type}"
        )
    return "; ".join(parts)


async def _report_dropped(
    account_id: str, key: str, dropped: list[tuple[int, Any]], eventbus: Any | None
) -> None:
    """Log and notify that unwritable stored items were dropped on write."""
    logger.warning(
        "계좌 규칙 저장값에서 쓸 수 없는 항목을 버림: account=%s, dropped=[%s]",
        account_id,
        _describe_dropped(dropped),
    )
    if eventbus is None:
        return
    await eventbus.publish(
        NotificationEvent(
            level="warning",
            title="계좌 규칙 저장값에서 쓸 수 없는 항목을 버림",
            message=(
                f"계좌 {account_id} 의 거래 규칙을 저장하면서 규칙으로 만들 수 없고 "
                f"rule update로도 고칠 수 없는 항목 {len(dropped)}건을 버렸습니다. "
                "오류 로그에서 위치를 확인하고, 원문은 "
                f"ante config history {key} 의 이전 값에서 확인하세요."
            ),
            category="system",
        )
    )


def _put_rule_config(
    raw_rules: list[dict[str, Any]],
    rule_type: str,
    enabled: bool | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Replace or append the rule of ``rule_type``; ``None`` keeps stored enabled."""
    for index, cfg in enumerate(raw_rules):
        if cfg.get("type") == rule_type:
            kept = cfg.get("enabled", True) if enabled is None else enabled
            raw_rules[index] = item_to_rule_config(rule_type, kept, params)
            return raw_rules[index]
    new_enabled = True if enabled is None else enabled
    new_config = item_to_rule_config(rule_type, new_enabled, params)
    raw_rules.append(new_config)
    return new_config


async def update_account_rule_config(
    *,
    account_service: Any,
    dynamic_config: Any,
    account_id: str,
    rule_type: str,
    params: dict[str, Any],
    changed_by: str,
    enabled: bool | None = None,
    config: Any | None = None,
    audit_logger: Any | None = None,
    eventbus: Any | None = None,
) -> dict[str, Any]:
    """Validate and persist one account-scoped stored rule override.

    It stores the full ``accounts.{account_id}.rules`` list through
    ``DynamicConfigService`` so
    ``ConfigChangedEvent`` and dynamic config history remain the single mutation
    path.
    """
    from ante.rule.engine import RULE_REGISTRY, RuleEngine

    await account_service.get(account_id)

    if rule_type not in RULE_REGISTRY:
        raise ValueError(
            f"알 수 없는 룰 타입: {rule_type!r}. "
            f"가능한 값: {list(RULE_REGISTRY.keys())}"
        )

    _reject_rule_item_keys(params)
    rule_class = RULE_REGISTRY[rule_type]
    validation_errors = _priority_errors(params) + rule_class.config_errors(
        item_to_rule_config(rule_type, True, params)
    )
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

    raw_rules, dropped = _drop_unwritable_items(raw_rules, RuleEngine._create_rule)
    new_config = _put_rule_config(raw_rules, rule_type, enabled, params)
    enabled = new_config["enabled"]

    await dynamic_config.set(key, raw_rules, category="rule", changed_by=changed_by)
    if dropped:
        await _report_dropped(account_id, key, dropped, eventbus)

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
