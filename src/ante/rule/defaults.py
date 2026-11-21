"""Account broker_type별 default rule 해석 helper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.account.models import Account


_DEFAULT_RULES_BY_BROKER_TYPE: dict[str, list[dict[str, Any]]] = {
    "kis-domestic": [{"type": "trading_hours", "enabled": True}],
    "test": [],
}


def resolve_effective_rules(
    account: Account,
    stored_rules: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Account broker_type별 default + stored explicit override를 merge.

    정책:

    - ``stored_rules``에 ``type``이 같은 항목이 있으면 그것이 default를
      override한다 (``enabled: false``로 비활성화 포함).
    - ``stored_rules``에 default ``type``이 없으면 default를 effective에
      추가한다.
    - ``stored_rules``의 추가 항목(custom rule)은 그대로 유지한다.
    """
    defaults = _DEFAULT_RULES_BY_BROKER_TYPE.get(account.broker_type, [])
    overrides = stored_rules or []
    override_types = {r.get("type") for r in overrides if isinstance(r, dict)}
    result: list[dict[str, Any]] = []
    for d in defaults:
        if d.get("type") not in override_types:
            result.append(d)
    result.extend(overrides)
    return result
