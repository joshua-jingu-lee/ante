"""Broker CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 5).

본 모듈은 #1816 의 6차 migration domain (broker) 의 대표 fault 5 건이
CLI path 와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출함을
lock 한다. #1842 (account) / #1843 sub-PR 1 (member) / sub-PR 2 (approval) /
sub-PR 3 (bot) / sub-PR 4 (treasury) 의 1:1 동형 패턴.

검증 대상 fault:

- ``APIError`` → ``BROKER_API_ERROR`` (external; KIS API business/HTTP error)
- ``AuthenticationError`` → ``BROKER_AUTH_FAILED`` (auth; KIS OAuth 토큰
  발급/갱신 실패)
- ``OrderNotFoundError`` → ``BROKER_ORDER_NOT_FOUND`` (not_found; broker side
  주문 부재)
- ``RateLimitError`` → ``BROKER_RATE_LIMITED`` (external; KIS per-minute
  rate limit 초과)
- ``CircuitOpenError`` → ``BROKER_CIRCUIT_OPEN`` (service_unavailable;
  연속 실패 임계 도달로 circuit breaker OPEN)

broker CLI 표면 (``balance``/``positions``/``reconcile``) 은 IPC 우선 →
``except click.ClickException`` 으로 fallback path 에 진입한다. fallback
의 ``_get_broker``/``_run_balance``/``_run_positions``/``_run_reconcile``
이 broker typed exception 을 raise 하면 ``except Exception`` 분기의
``emit_cli_error(fmt, e)`` 가 registry MRO lookup 으로 ``BROKER_*`` 안정
코드를 surface 한다 — 본 test 는 그 경로를 mock 으로 단언한다.

IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322 의
``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 — 실측 ``.code``
가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로 직접 직렬화한다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.broker.exceptions import (
    APIError,
    AuthenticationError,
    CircuitOpenError,
    OrderNotFoundError,
    RateLimitError,
)
from ante.cli.main import cli
from ante.contracts import ipc_error_payload
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=["broker:read", "broker:write", "broker:admin"],
)


@pytest.fixture
def runner() -> CliRunner:
    """``ante --format json broker ...`` 호출용 ``CliRunner`` fixture.

    auth middleware 를 master member 로 우회한다 (#1843 sub-PR 1/2/3/4
    fixture 1:1 동형). ``require_scope`` decorator 는 그대로 동작하므로
    모든 broker scope 를 부여한다.
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


def _patch_balance_fallback_raises(exc: BaseException):  # noqa: ANN202
    """broker.balance CLI 의 fallback path 에서 broker exception 을 강제로
    raise 시키기 위한 context manager 묶음.

    IPC 우선 시도는 ``ipc_send`` 가 ``ClickException`` 을 raise 하도록
    mock — CLI ``balance`` 의 ``except click.ClickException`` 분기가 fallback
    path 에 진입한다. fallback 의 ``_get_broker`` 가 mock adapter (raise 하는
    ``get_account_balance``) 를 반환하면, ``_run_balance`` 가 broker exception
    을 전파하고 ``except Exception → emit_cli_error`` 가 안정 코드를 surface
    한다.
    """
    import click

    from ante.broker.base import BrokerAdapter
    from ante.cli.commands import broker as broker_cmd

    async def _raise_click(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise click.ClickException("server unavailable")

    mock_adapter = MagicMock(spec=BrokerAdapter)
    mock_adapter.is_connected = True
    mock_adapter.exchange = "KRX"
    mock_adapter.get_account_balance = AsyncMock(side_effect=exc)
    mock_adapter.get_positions = AsyncMock(side_effect=exc)
    mock_adapter.get_account_positions = AsyncMock(side_effect=exc)
    mock_adapter.disconnect = AsyncMock(return_value=None)

    async def _fake_get_broker(account_id=None):  # noqa: ANN001, ANN202
        return mock_adapter, None

    return patch.object(
        broker_cmd, "_ipc_broker_command", new=_raise_click
    ), patch.object(broker_cmd, "_get_broker", new=_fake_get_broker)


# ── (1) APIError ↔ BROKER_API_ERROR ─────────────────────────────────────────


class TestBrokerApiErrorEquivalence:
    """``APIError`` 는 양쪽에서 ``BROKER_API_ERROR``.

    CLI direct path: ``broker balance`` fallback path 에서 broker adapter
    가 raise → ``emit_cli_error`` 가 registry MRO lookup 으로
    ``BROKER_API_ERROR`` 를 surface.

    원천 KIS ``msg_cd`` (``APIError.error_code``) 는 envelope public surface
    에 노출되지 않는다 — round-trip 분리 회귀는
    ``test_broker_external_code_separation`` 가 책임진다.
    """

    def test_cli_direct_api_error_via_balance(self, runner: CliRunner) -> None:
        exc = APIError(
            "KIS API Error [APBK0501]: 주문 가능 금액 부족",
            status_code=400,
            error_code="APBK0501",
        )
        ipc_patch, broker_patch = _patch_balance_fallback_raises(exc)
        with ipc_patch, broker_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "balance",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BROKER_API_ERROR"

    def test_ipc_envelope_api_error(self) -> None:
        exc = APIError(
            "KIS API Error [APBK0501]: 주문 가능 금액 부족",
            status_code=400,
            error_code="APBK0501",
        )
        assert _ipc_envelope_code(exc) == "BROKER_API_ERROR"


# ── (2) AuthenticationError ↔ BROKER_AUTH_FAILED ────────────────────────────


class TestBrokerAuthFailedEquivalence:
    """``AuthenticationError`` 는 양쪽에서 ``BROKER_AUTH_FAILED``.

    CLI direct path: ``broker balance`` fallback path 에서 broker adapter
    가 raise → ``emit_cli_error`` 가 ``BROKER_AUTH_FAILED`` 를 surface.
    """

    def test_cli_direct_auth_failed_via_balance(self, runner: CliRunner) -> None:
        exc = AuthenticationError("인증 실패 (HTTP 401): invalid app_key")
        ipc_patch, broker_patch = _patch_balance_fallback_raises(exc)
        with ipc_patch, broker_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "balance",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BROKER_AUTH_FAILED"

    def test_ipc_envelope_auth_failed(self) -> None:
        exc = AuthenticationError("인증 실패 (HTTP 401): invalid app_key")
        assert _ipc_envelope_code(exc) == "BROKER_AUTH_FAILED"


# ── (3) OrderNotFoundError ↔ BROKER_ORDER_NOT_FOUND ─────────────────────────


class TestBrokerOrderNotFoundEquivalence:
    """``OrderNotFoundError`` 는 양쪽에서 ``BROKER_ORDER_NOT_FOUND``.

    CLI direct path: ``broker balance`` fallback path 에서 broker adapter
    가 raise (예: 보유 조회 시 cross-fault 시나리오) → ``emit_cli_error`` 가
    ``BROKER_ORDER_NOT_FOUND`` 를 surface. ``broker`` CLI 자체에는 단일
    order 조회 표면이 없지만 contract-level equivalence 는 fallback path
    에서 typed exception 이 ``emit_cli_error`` 를 통해 동일 코드를 raise
    함을 lock 한다.
    """

    def test_cli_direct_order_not_found_via_balance(self, runner: CliRunner) -> None:
        exc = OrderNotFoundError("주문을 찾을 수 없음: ord-1")
        ipc_patch, broker_patch = _patch_balance_fallback_raises(exc)
        with ipc_patch, broker_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "balance",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BROKER_ORDER_NOT_FOUND"

    def test_ipc_envelope_order_not_found(self) -> None:
        exc = OrderNotFoundError("주문을 찾을 수 없음: ord-1")
        assert _ipc_envelope_code(exc) == "BROKER_ORDER_NOT_FOUND"


# ── (4) RateLimitError ↔ BROKER_RATE_LIMITED ────────────────────────────────


class TestBrokerRateLimitedEquivalence:
    """``RateLimitError`` 는 양쪽에서 ``BROKER_RATE_LIMITED``.

    CLI direct path: ``broker balance`` fallback path 에서 broker adapter
    가 raise → ``emit_cli_error`` 가 ``BROKER_RATE_LIMITED`` 를 surface.
    """

    def test_cli_direct_rate_limited_via_balance(self, runner: CliRunner) -> None:
        exc = RateLimitError("Rate limit 초과: 분당 20회 초과")
        ipc_patch, broker_patch = _patch_balance_fallback_raises(exc)
        with ipc_patch, broker_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "balance",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BROKER_RATE_LIMITED"

    def test_ipc_envelope_rate_limited(self) -> None:
        exc = RateLimitError("Rate limit 초과: 분당 20회 초과")
        assert _ipc_envelope_code(exc) == "BROKER_RATE_LIMITED"


# ── (5) CircuitOpenError ↔ BROKER_CIRCUIT_OPEN ──────────────────────────────


class TestBrokerCircuitOpenEquivalence:
    """``CircuitOpenError`` 는 양쪽에서 ``BROKER_CIRCUIT_OPEN``.

    CLI direct path: ``broker balance`` fallback path 에서 broker adapter
    가 raise (circuit breaker OPEN) → ``emit_cli_error`` 가
    ``BROKER_CIRCUIT_OPEN`` 을 surface.
    """

    def test_cli_direct_circuit_open_via_balance(self, runner: CliRunner) -> None:
        exc = CircuitOpenError("Circuit breaker OPEN: KIS API 차단 중")
        ipc_patch, broker_patch = _patch_balance_fallback_raises(exc)
        with ipc_patch, broker_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "balance",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BROKER_CIRCUIT_OPEN"

    def test_ipc_envelope_circuit_open(self) -> None:
        exc = CircuitOpenError("Circuit breaker OPEN: KIS API 차단 중")
        assert _ipc_envelope_code(exc) == "BROKER_CIRCUIT_OPEN"
