"""``rule update``가 ``enabled``를 생략하면 저장된 같은 type의 값을 유지한다 (#2729).

판정은 ``dynamic_config.set``에 넘어간 목록, 응답의 ``rule.enabled``, 감사 detail이다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.rule.config_update import update_account_rule_config

KEY = "accounts.domestic.rules"
RULE_TYPE = "daily_loss_limit"
PARAMS = {"max_daily_loss_percent": 0.03}
OTHER = {"type": "total_exposure_limit", "enabled": False, "max_exposure_percent": 0.8}


def _stored(enabled: bool) -> dict[str, Any]:
    return {"type": RULE_TYPE, "enabled": enabled, "max_daily_loss_percent": 0.02}


async def _update(
    stored: list[dict[str, Any]],
    *,
    config: Any | None = None,
    **enabled: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    dynamic_config = MagicMock()
    dynamic_config.get = AsyncMock(return_value=[dict(item) for item in stored])
    dynamic_config.set = AsyncMock(return_value=None)
    audit_logger = MagicMock()
    audit_logger.log = AsyncMock(return_value=None)
    result = await update_account_rule_config(
        account_service=AsyncMock(),
        dynamic_config=dynamic_config,
        account_id="domestic",
        rule_type=RULE_TYPE,
        params=dict(PARAMS),
        changed_by="tester",
        config=config,
        audit_logger=audit_logger,
        **enabled,
    )
    dynamic_config.set.assert_awaited_once()
    assert dynamic_config.set.await_args.args[0] == KEY
    saved = dynamic_config.set.await_args.args[1]
    return saved, result, audit_logger.log.await_args.kwargs["detail"]


def _expected(enabled: bool) -> dict[str, Any]:
    return {"type": RULE_TYPE, "enabled": enabled, **PARAMS}


@pytest.mark.asyncio
@pytest.mark.parametrize("omitted", [{}, {"enabled": None}], ids=["missing", "none"])
@pytest.mark.parametrize("stored_enabled", [False, True])
async def test_omitted_enabled_keeps_the_stored_value(
    omitted: dict[str, Any], stored_enabled: bool
) -> None:
    saved, result, detail = await _update(
        [dict(OTHER), _stored(stored_enabled)], **omitted
    )
    assert saved == [OTHER, _expected(stored_enabled)]
    assert result["rule"] == {
        "type": RULE_TYPE,
        "enabled": stored_enabled,
        "params": PARAMS,
    }
    assert detail == f"rule update: {RULE_TYPE} enabled={stored_enabled}"


@pytest.mark.asyncio
@pytest.mark.parametrize("omitted", [{}, {"enabled": None}], ids=["missing", "none"])
async def test_omitted_enabled_without_a_stored_item_is_true(
    omitted: dict[str, Any],
) -> None:
    saved, result, detail = await _update([dict(OTHER)], **omitted)
    assert saved == [OTHER, _expected(True)]
    assert result["rule"]["enabled"] is True
    assert detail == f"rule update: {RULE_TYPE} enabled=True"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_enabled", [False, True])
@pytest.mark.parametrize("given", [False, True])
async def test_given_enabled_wins_over_the_stored_value(
    stored_enabled: bool, given: bool
) -> None:
    saved, result, detail = await _update([_stored(stored_enabled)], enabled=given)
    assert saved == [_expected(given)]
    assert result["rule"]["enabled"] is given
    assert detail == f"rule update: {RULE_TYPE} enabled={given}"


@pytest.mark.asyncio
async def test_direct_path_keeps_the_seed_value_when_dynamic_config_is_empty() -> None:
    config = MagicMock()
    config.get = MagicMock(return_value=[_stored(False)])
    saved, result, detail = await _update([], config=config)
    config.get.assert_called_once_with(KEY)
    assert saved == [_expected(False)]
    assert result["rule"]["enabled"] is False
    assert detail == f"rule update: {RULE_TYPE} enabled=False"
