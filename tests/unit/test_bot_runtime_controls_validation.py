"""봇 runtime control 범위 검증 테스트 (#1456).

SSOT:
    - ``docs/dashboard/user-stories/bots.md`` B-5 line 197-200 — runtime
      control 4개 필드의 spec 범위 정의.
    - ``docs/specs/web-api/05-resource-endpoints.md`` PUT ``/api/bots/{bot_id}``
      body — runtime control 필드 contract.

Spec 범위:
    - ``max_restart_attempts``: 1~10
    - ``restart_cooldown_seconds``: 10~600
    - ``step_timeout_seconds``: 5~120
    - ``max_signals_per_step``: 1~200

본 모듈은 3개 layer 를 invariant 로 잠근다:
    1. ``BotConfig.__post_init__`` — 직접 생성 시 ``ValueError``.
    2. ``BotUpdateRequest`` Pydantic 모델 — PUT body validation 시 422.
    3. ``BOT_UPDATE_REQUEST_SCHEMA`` JSON Schema + live ``/openapi.json``
       ``components.schemas.BotUpdateRequest`` — frontend codegen 노출 범위.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ante.bot.config import (
    MAX_MAX_RESTART_ATTEMPTS,
    MAX_MAX_SIGNALS_PER_STEP,
    MAX_RESTART_COOLDOWN_SECONDS,
    MAX_STEP_TIMEOUT_SECONDS,
    MIN_MAX_RESTART_ATTEMPTS,
    MIN_MAX_SIGNALS_PER_STEP,
    MIN_RESTART_COOLDOWN_SECONDS,
    MIN_STEP_TIMEOUT_SECONDS,
    BotConfig,
)
from ante.web.routes.bots import BOT_UPDATE_REQUEST_SCHEMA
from ante.web.schemas import BotUpdateRequest


def _base_payload() -> dict:
    """spec 범위 안에 있는 baseline payload — single field만 override 해서 테스트."""
    return {}


# ── Layer 1: BotConfig.__post_init__ ──────────────────────


class TestBotConfigRuntimeControlsValidation:
    """``BotConfig`` 직접 생성 시 spec 범위 밖 값은 ``ValueError``."""

    def test_max_restart_attempts_below_min_raises(self) -> None:
        with pytest.raises(ValueError, match="max_restart_attempts"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                max_restart_attempts=MIN_MAX_RESTART_ATTEMPTS - 1,
            )

    def test_max_restart_attempts_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="max_restart_attempts"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                max_restart_attempts=MAX_MAX_RESTART_ATTEMPTS + 1,
            )

    def test_restart_cooldown_seconds_below_min_raises(self) -> None:
        with pytest.raises(ValueError, match="restart_cooldown_seconds"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                restart_cooldown_seconds=MIN_RESTART_COOLDOWN_SECONDS - 1,
            )

    def test_restart_cooldown_seconds_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="restart_cooldown_seconds"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                restart_cooldown_seconds=MAX_RESTART_COOLDOWN_SECONDS + 1,
            )

    def test_step_timeout_seconds_below_min_raises(self) -> None:
        with pytest.raises(ValueError, match="step_timeout_seconds"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                step_timeout_seconds=MIN_STEP_TIMEOUT_SECONDS - 1,
            )

    def test_step_timeout_seconds_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="step_timeout_seconds"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                step_timeout_seconds=MAX_STEP_TIMEOUT_SECONDS + 1,
            )

    def test_max_signals_per_step_below_min_raises(self) -> None:
        with pytest.raises(ValueError, match="max_signals_per_step"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                max_signals_per_step=MIN_MAX_SIGNALS_PER_STEP - 1,
            )

    def test_max_signals_per_step_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="max_signals_per_step"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                account_id="acc-test",
                max_signals_per_step=MAX_MAX_SIGNALS_PER_STEP + 1,
            )

    def test_defaults_pass_validation(self) -> None:
        """spec default (3, 60, 30, 50)는 모두 통과 범위 안."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            account_id="acc-test",
        )
        assert config.max_restart_attempts == 3
        assert config.restart_cooldown_seconds == 60
        assert config.step_timeout_seconds == 30
        assert config.max_signals_per_step == 50

    def test_min_boundary_passes(self) -> None:
        """spec min 값은 통과한다."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            account_id="acc-test",
            max_restart_attempts=MIN_MAX_RESTART_ATTEMPTS,
            restart_cooldown_seconds=MIN_RESTART_COOLDOWN_SECONDS,
            step_timeout_seconds=MIN_STEP_TIMEOUT_SECONDS,
            max_signals_per_step=MIN_MAX_SIGNALS_PER_STEP,
        )
        assert config.max_restart_attempts == MIN_MAX_RESTART_ATTEMPTS

    def test_max_boundary_passes(self) -> None:
        """spec max 값은 통과한다."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            account_id="acc-test",
            max_restart_attempts=MAX_MAX_RESTART_ATTEMPTS,
            restart_cooldown_seconds=MAX_RESTART_COOLDOWN_SECONDS,
            step_timeout_seconds=MAX_STEP_TIMEOUT_SECONDS,
            max_signals_per_step=MAX_MAX_SIGNALS_PER_STEP,
        )
        assert config.max_restart_attempts == MAX_MAX_RESTART_ATTEMPTS


# ── Layer 2: BotUpdateRequest Pydantic ──────────────────────


class TestBotUpdateRequestRuntimeControlsValidation:
    """``BotUpdateRequest`` 가 spec 범위 밖 값을 ``ValidationError`` 로 거부.

    PUT 핸들러는 ``ValidationError`` 를 422 ``HTTPException`` 으로 변환한다
    (``routes/bots.py:1090``).
    """

    def test_max_restart_attempts_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"max_restart_attempts": MIN_MAX_RESTART_ATTEMPTS - 1}
            )

    def test_max_restart_attempts_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"max_restart_attempts": MAX_MAX_RESTART_ATTEMPTS + 1}
            )

    def test_restart_cooldown_seconds_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"restart_cooldown_seconds": MIN_RESTART_COOLDOWN_SECONDS - 1}
            )

    def test_restart_cooldown_seconds_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"restart_cooldown_seconds": MAX_RESTART_COOLDOWN_SECONDS + 1}
            )

    def test_step_timeout_seconds_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"step_timeout_seconds": MIN_STEP_TIMEOUT_SECONDS - 1}
            )

    def test_step_timeout_seconds_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"step_timeout_seconds": MAX_STEP_TIMEOUT_SECONDS + 1}
            )

    def test_max_signals_per_step_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"max_signals_per_step": MIN_MAX_SIGNALS_PER_STEP - 1}
            )

    def test_max_signals_per_step_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BotUpdateRequest.model_validate(
                {"max_signals_per_step": MAX_MAX_SIGNALS_PER_STEP + 1}
            )

    def test_min_boundary_accepted(self) -> None:
        """spec min 값은 ``BotUpdateRequest`` 도 통과한다."""
        body = BotUpdateRequest.model_validate(
            {
                "max_restart_attempts": MIN_MAX_RESTART_ATTEMPTS,
                "restart_cooldown_seconds": MIN_RESTART_COOLDOWN_SECONDS,
                "step_timeout_seconds": MIN_STEP_TIMEOUT_SECONDS,
                "max_signals_per_step": MIN_MAX_SIGNALS_PER_STEP,
            }
        )
        assert body.max_restart_attempts == MIN_MAX_RESTART_ATTEMPTS
        assert body.restart_cooldown_seconds == MIN_RESTART_COOLDOWN_SECONDS
        assert body.step_timeout_seconds == MIN_STEP_TIMEOUT_SECONDS
        assert body.max_signals_per_step == MIN_MAX_SIGNALS_PER_STEP

    def test_max_boundary_accepted(self) -> None:
        """spec max 값은 ``BotUpdateRequest`` 도 통과한다."""
        body = BotUpdateRequest.model_validate(
            {
                "max_restart_attempts": MAX_MAX_RESTART_ATTEMPTS,
                "restart_cooldown_seconds": MAX_RESTART_COOLDOWN_SECONDS,
                "step_timeout_seconds": MAX_STEP_TIMEOUT_SECONDS,
                "max_signals_per_step": MAX_MAX_SIGNALS_PER_STEP,
            }
        )
        assert body.max_restart_attempts == MAX_MAX_RESTART_ATTEMPTS

    def test_none_remains_acceptable(self) -> None:
        """``None`` 은 그대로 통과한다 (변경하지 않음 의미)."""
        body = BotUpdateRequest.model_validate({})
        assert body.max_restart_attempts is None
        assert body.restart_cooldown_seconds is None
        assert body.step_timeout_seconds is None
        assert body.max_signals_per_step is None


# ── Layer 3: JSON Schema (static + live OpenAPI) ──────────────────────


class TestBotUpdateRequestJsonSchemaBounds:
    """``BOT_UPDATE_REQUEST_SCHEMA`` properties 에 ``minimum``/``maximum`` 노출."""

    def test_schema_includes_max_restart_attempts_bounds(self) -> None:
        prop = BOT_UPDATE_REQUEST_SCHEMA["properties"]["max_restart_attempts"]
        assert prop["minimum"] == MIN_MAX_RESTART_ATTEMPTS
        assert prop["maximum"] == MAX_MAX_RESTART_ATTEMPTS

    def test_schema_includes_restart_cooldown_seconds_bounds(self) -> None:
        prop = BOT_UPDATE_REQUEST_SCHEMA["properties"]["restart_cooldown_seconds"]
        assert prop["minimum"] == MIN_RESTART_COOLDOWN_SECONDS
        assert prop["maximum"] == MAX_RESTART_COOLDOWN_SECONDS

    def test_schema_includes_step_timeout_seconds_bounds(self) -> None:
        prop = BOT_UPDATE_REQUEST_SCHEMA["properties"]["step_timeout_seconds"]
        assert prop["minimum"] == MIN_STEP_TIMEOUT_SECONDS
        assert prop["maximum"] == MAX_STEP_TIMEOUT_SECONDS

    def test_schema_includes_max_signals_per_step_bounds(self) -> None:
        prop = BOT_UPDATE_REQUEST_SCHEMA["properties"]["max_signals_per_step"]
        assert prop["minimum"] == MIN_MAX_SIGNALS_PER_STEP
        assert prop["maximum"] == MAX_MAX_SIGNALS_PER_STEP


class TestBotUpdateRequestLiveOpenApiBounds:
    """live ``/openapi.json`` ``components.schemas.BotUpdateRequest`` 노출 검증.

    ``_install_openapi_customizer`` 가 ``BOT_UPDATE_REQUEST_SCHEMA`` 본체를
    ``components.schemas`` 에 등록한다 (``src/ante/web/app.py:293``). frontend
    ``openapi-typescript`` codegen 이 이 결과를 그대로 사용하므로, 범위 정보가
    components 트리에 전달되는지 invariant 로 확인한다.
    """

    def _schema(self) -> dict:
        from ante.web.app import create_app

        app = create_app()
        return app.openapi()

    def test_components_schema_includes_max_restart_attempts_bounds(self) -> None:
        schema = self._schema()
        prop = schema["components"]["schemas"]["BotUpdateRequest"]["properties"][
            "max_restart_attempts"
        ]
        assert prop["minimum"] == MIN_MAX_RESTART_ATTEMPTS
        assert prop["maximum"] == MAX_MAX_RESTART_ATTEMPTS

    def test_components_schema_includes_restart_cooldown_seconds_bounds(self) -> None:
        schema = self._schema()
        prop = schema["components"]["schemas"]["BotUpdateRequest"]["properties"][
            "restart_cooldown_seconds"
        ]
        assert prop["minimum"] == MIN_RESTART_COOLDOWN_SECONDS
        assert prop["maximum"] == MAX_RESTART_COOLDOWN_SECONDS

    def test_components_schema_includes_step_timeout_seconds_bounds(self) -> None:
        schema = self._schema()
        prop = schema["components"]["schemas"]["BotUpdateRequest"]["properties"][
            "step_timeout_seconds"
        ]
        assert prop["minimum"] == MIN_STEP_TIMEOUT_SECONDS
        assert prop["maximum"] == MAX_STEP_TIMEOUT_SECONDS

    def test_components_schema_includes_max_signals_per_step_bounds(self) -> None:
        schema = self._schema()
        prop = schema["components"]["schemas"]["BotUpdateRequest"]["properties"][
            "max_signals_per_step"
        ]
        assert prop["minimum"] == MIN_MAX_SIGNALS_PER_STEP
        assert prop["maximum"] == MAX_MAX_SIGNALS_PER_STEP
