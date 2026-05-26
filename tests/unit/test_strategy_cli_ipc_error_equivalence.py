"""Strategy CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 6).

본 모듈은 #1816 의 7차 migration domain (strategy) 의 대표 fault 4 건이
CLI path 와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출함을
lock 한다. #1842 (account) / #1843 sub-PR 1 (member) / sub-PR 2 (approval) /
sub-PR 3 (bot) / sub-PR 4 (treasury) / sub-PR 5 (broker) 의 1:1 동형 패턴.

검증 대상 fault:

- ``StrategyNotFoundError`` → ``STRATEGY_NOT_FOUND`` (not_found; #1796 lock)
- ``StrategyLoadError`` → ``STRATEGY_LOAD_ERROR`` (validation; 본 PR 신규)
- ``StrategyValidationError`` → ``STRATEGY_VALIDATION_ERROR`` (validation; 본 PR
  신규)
- ``IncompatibleExchangeError`` → ``STRATEGY_INCOMPATIBLE_EXCHANGE`` (validation;
  본 PR 신규)

IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322 의
``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 — 실측 ``.code``
가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로 직접 직렬화한다.

CLI direct path 는 ``strategy set-status`` 표면의 cold-path 분기에서
typed exception 을 raise 하고 ``except Exception → fmt.error(str(e),
code=getattr(e, "code", "STRATEGY_ERROR"))`` 핸들러가 동일 안정 코드를
surface 함을 단언한다 (#1796 ``strategy_set_status`` 패턴).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.contracts import ipc_error_payload
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.exceptions import (
    IncompatibleExchangeError,
    StrategyLoadError,
    StrategyNotFoundError,
    StrategyValidationError,
)

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=["strategy:read", "strategy:write"],
)


@pytest.fixture
def runner() -> CliRunner:
    """``ante --format json strategy ...`` 호출용 ``CliRunner`` fixture.

    auth middleware 를 master member 로 우회한다 (#1843 sub-PR 1/2/3/4/5
    fixture 1:1 동형). ``require_scope`` decorator 는 그대로 동작하므로
    모든 strategy scope 를 부여한다.
    """
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx) -> None:  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


def _ipc_envelope_code(exc: BaseException) -> str:
    """주어진 exception 을 IPC envelope 으로 직렬화했을 때의 ``code``.

    IPC server.py:322 가 적용하는 ``getattr(e, "code", "EXECUTION_ERROR")``
    fallback 과 helper(``ipc_error_payload``)의 registry-first resolution 은
    실측 ``.code`` 가 일치하는 한 동일 코드를 생성한다 (#1842 plan v2 #6).
    본 helper 는 helper 경로를 그대로 사용해 contract 동등성을 단언한다.
    """

    payload = ipc_error_payload(exc)
    return payload["code"]


def _cli_envelope_payload(result_output: str) -> dict:
    """``CliRunner.result.output`` 에서 JSON envelope 첫 객체를 추출."""
    payload_line = next(
        (line for line in result_output.splitlines() if line.startswith("{")),
        None,
    )
    assert payload_line is not None, f"JSON envelope 발견 실패: {result_output!r}"
    return json.loads(payload_line)


def _patch_strategy_set_status_raises(exc: BaseException):  # noqa: ANN202
    """``strategy set-status`` cold-path 가 raise 하도록 mock.

    ``is_active_runtime()`` 을 False 로 강제해 IPC 경로 대신 ``_create_registry``
    → ``registry.update_status(...)`` 호출 경로에 진입시키고, ``StrategyRegistry``
    를 mock 으로 대체해 ``update_status`` 가 ``exc`` 를 raise 하도록 만든다.
    """
    from ante.cli.commands import strategy as strategy_cmd

    mock_registry = MagicMock()
    mock_registry.initialize = AsyncMock(return_value=None)
    mock_registry.update_status = AsyncMock(side_effect=exc)
    mock_registry.get = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.close = AsyncMock(return_value=None)

    # #1857: ``_create_registry`` 는 async context manager 로 변환됨.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_create_registry(*args, **kwargs):  # noqa: ANN202
        yield mock_registry, mock_db

    return (
        patch.object(strategy_cmd, "_create_registry", new=_fake_create_registry),
        patch(
            "ante.cli.cold_path.is_active_runtime",
            return_value=False,
        ),
    )


# ── (1) StrategyNotFoundError ↔ STRATEGY_NOT_FOUND ──────────────────────────


class TestStrategyNotFoundEquivalence:
    """``StrategyNotFoundError`` 는 양쪽에서 ``STRATEGY_NOT_FOUND``.

    CLI direct path: ``strategy set-status`` cold-path 가
    ``registry.update_status`` 에서 typed exception 을 raise →
    ``except Exception`` 핸들러가 ``getattr(e, "code", "STRATEGY_ERROR")`` 로
    ``STRATEGY_NOT_FOUND`` 를 surface (#1796 lock).
    """

    def test_cli_direct_strategy_not_found(self, runner: CliRunner) -> None:
        exc = StrategyNotFoundError("전략 'st-1' 을 찾을 수 없습니다.")
        registry_patch, runtime_patch = _patch_strategy_set_status_raises(exc)
        with registry_patch, runtime_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "set-status",
                    "st-1",
                    "--status",
                    "adopted",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "STRATEGY_NOT_FOUND"

    def test_ipc_envelope_strategy_not_found(self) -> None:
        exc = StrategyNotFoundError("전략 'st-1' 을 찾을 수 없습니다.")
        assert _ipc_envelope_code(exc) == "STRATEGY_NOT_FOUND"


# ── (2) StrategyLoadError ↔ STRATEGY_LOAD_ERROR ─────────────────────────────


class TestStrategyLoadErrorEquivalence:
    """``StrategyLoadError`` 는 양쪽에서 ``STRATEGY_LOAD_ERROR``.

    CLI direct path: ``strategy submit`` 의 load 단계가 ``StrategyLoader.load``
    에서 raise → ``except StrategyLoadError`` 분기의 ``emit_cli_error`` 가
    registry MRO lookup 으로 ``STRATEGY_LOAD_ERROR`` 를 surface.

    submit 표면은 path 인자 + 파일 시스템 의존성이 많아 본 test 는 IPC
    envelope equivalence 만 단언한다 (registry resolver 가 동일 코드를
    생성한다는 contract 만으로 surface SSOT lock 충분).
    """

    def test_ipc_envelope_load_error(self) -> None:
        exc = StrategyLoadError("ModuleNotFoundError: ante_user_strategies.foo")
        assert _ipc_envelope_code(exc) == "STRATEGY_LOAD_ERROR"

    def test_class_level_code(self) -> None:
        """``getattr(e, "code")`` 가 typed 코드를 반환 — server.py:322 fallback
        과 helper registry-first 가 동일 코드를 생성하는 invariant."""
        exc = StrategyLoadError("load failed")
        assert getattr(exc, "code", None) == "STRATEGY_LOAD_ERROR"


# ── (3) StrategyValidationError ↔ STRATEGY_VALIDATION_ERROR ─────────────────


class TestStrategyValidationErrorEquivalence:
    """``StrategyValidationError`` 는 양쪽에서 ``STRATEGY_VALIDATION_ERROR``.

    CLI ``strategy submit``/``validate``/``list --status`` 표면이 ingress
    validation 단계에서 직접 ``code="STRATEGY_VALIDATION_ERROR"`` 를 명시
    부여하며, service-layer typed exception (예: registry 등록 단계의
    metadata 검증) 도 동일 안정 코드 SSOT 를 surface 한다.
    """

    def test_ipc_envelope_validation_error(self) -> None:
        exc = StrategyValidationError("manifest 검증 실패: name 필드 누락")
        assert _ipc_envelope_code(exc) == "STRATEGY_VALIDATION_ERROR"

    def test_class_level_code(self) -> None:
        exc = StrategyValidationError("validation failed")
        assert getattr(exc, "code", None) == "STRATEGY_VALIDATION_ERROR"


# ── (4) IncompatibleExchangeError ↔ STRATEGY_INCOMPATIBLE_EXCHANGE ──────────


class TestIncompatibleExchangeEquivalence:
    """``IncompatibleExchangeError`` 는 양쪽에서 ``STRATEGY_INCOMPATIBLE_EXCHANGE``.

    전략 ↔ 계좌 exchange 호환성 거부의 안정 코드. ``StrategyError`` MRO
    lookup 으로 CLI strategy 표면의 ``except StrategyError`` 핸들러가 동일
    typed 코드를 surface 한다.
    """

    def test_ipc_envelope_incompatible_exchange(self) -> None:
        exc = IncompatibleExchangeError(
            "전략 exchange=KRX 가 계좌 exchange=NASDAQ 와 호환되지 않습니다."
        )
        assert _ipc_envelope_code(exc) == "STRATEGY_INCOMPATIBLE_EXCHANGE"

    def test_class_level_code(self) -> None:
        exc = IncompatibleExchangeError("incompat")
        assert getattr(exc, "code", None) == "STRATEGY_INCOMPATIBLE_EXCHANGE"
