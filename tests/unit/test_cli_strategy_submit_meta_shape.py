"""CLI ``strategy submit`` meta shape ingress validation 회귀 (#1756).

이슈 #1756 (oracle A7 cli_strategy_submit_meta_shape_contract):
사용자가 작성한 strategy manifest의 ``meta`` 속성이 ``StrategyMeta`` 인스턴스가
아닌 ``dict`` (또는 임의의 다른 객체)일 때, 기존 ``strategy submit`` 경로는
``meta = strategy_cls.meta`` 직후 ``registry.register(...)`` 호출로 진입해
``registry.py`` 내부 ``meta.name`` attribute access에서 ``AttributeError``가
raise되었다. 호출 표면에는 ``StrategyError`` 만 catch되어 있어 raw exception이
Click default 핸들러까지 전파되며 stderr traceback이 노출된다.

본 회귀는 다음 invariant를 단정한다.

- **R1 JSON 모드, dict meta** — exit 1, stdout JSON envelope에
  ``submitted=False``, ``stage="meta_validation"``,
  ``code="STRATEGY_VALIDATION_ERROR"`` 세 필드가 모두 존재, stderr empty
  (traceback 누출 없음).
- **R2 JSON 모드, 정상 StrategyMeta 인스턴스 sanity** — 기존 정상 등록 경로가
  meta shape 분기 추가에 의해 회귀하지 않음 (exit 0, ``submitted=True``).
- **R3 text 모드, dict meta** — exit 1, stderr에 ``Invalid meta shape`` 와
  실제 받은 타입(``dict``)이 동시에 포함. (formatter spec상 text 모드 fmt.error는
  ``Error: <message>`` 한 줄만 인쇄하며 ``code`` 는 JSON 전용 — text는 사람이
  읽는 메시지 본문으로만 invariant를 단정한다.)

테스트 전략:
- ``StrategyLoader.load`` 를 mock하여 임의 strategy class 객체를 반환시킨다.
  ``Strategy`` ABC 서브클래스화는 ``meta=<dict>`` 시 정의 시점에 fail하지
  않으므로, ABC 우회를 위해 ``MagicMock`` 기반 가짜 클래스로 ``.meta`` 만
  주입한다 (이슈 보고서의 실제 manifest와 동등한 정적 형상).
- ``_create_registry`` 도 mock하여 R2 sanity에서 정상 ``register`` 응답을
  되돌린다.
- ``StrategyValidator`` 의 정적 검증은 통과로 mock (본 회귀의 책임은 meta
  shape ingress 분기로 한정; static validator의 dict-meta 거부는 별도 sweep).
"""

from __future__ import annotations

import inspect
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.base import Signal, Strategy, StrategyMeta


def _acm_factory(value):  # noqa: ANN001, ANN202
    """#1857: helper async context manager 전환에 맞춰 fake factory 를
    생성한다. 기존 ``new_callable=AsyncMock, return_value=(...)`` 패턴을
    ``new=_acm_factory((...))`` 로 대체해 ``async with helper(ctx) as
    (...):`` 호출이 yield 한 값을 그대로 받도록 한다.
    """
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def _fake_factory(*args, **kwargs):
        yield value

    return _fake_factory


_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


# ── 테스트용 strategy 클래스 ──────────────────────────────


class _ValidStrategy(Strategy):
    """R2 sanity: 정상 StrategyMeta 인스턴스를 가진 전략."""

    meta = StrategyMeta(
        name="valid-meta",
        version="0.1.0",
        description="meta shape sanity",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []


def _make_dict_meta_strategy_cls() -> Any:
    """``.meta`` 가 dict인 가짜 strategy class.

    Strategy ABC 서브클래스로 ``meta=<dict>`` 선언 시 정의 시점에 typing
    이슈는 없지만 ``isinstance(meta, StrategyMeta)`` 가 False가 되는 형상을
    가장 작게 재현한다. ``StrategyLoader.load`` 의 반환값을 mock으로 대체할
    것이므로 ABC 구현 의무는 무관하다 — 단순한 dummy 객체로 충분하다.
    """
    fake_cls = MagicMock()
    fake_cls.meta = {
        "name": "broken-dict",
        "version": "0.1.0",
        "description": "dict-shape meta (invalid)",
    }
    # rationale/risks 추출 try 블록이 인스턴스화하므로 호출 가능하지만
    # `isinstance` 분기에서 이미 SystemExit(1) 되므로 도달하지 않는다.
    fake_cls.return_value = MagicMock(
        get_rationale=MagicMock(return_value=""),
        get_risks=MagicMock(return_value=[]),
    )
    return fake_cls


# ── CliRunner / 인증 fixture ──────────────────────────────


def _make_runner() -> CliRunner:
    """``mix_stderr=False`` runner. click 버전 fallback (#1517 패턴)."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


@pytest.fixture()
def runner() -> CliRunner:
    """인증을 mock으로 우회한 ``mix_stderr=False`` CliRunner."""
    r = _make_runner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _mock_registry_for_valid() -> MagicMock:
    """R2 sanity용 register 성공 응답."""
    registry = MagicMock()
    registry.initialize = AsyncMock()
    record = MagicMock()
    record.strategy_id = "valid-meta_v0.1.0"
    record.name = "valid-meta"
    record.version = "0.1.0"
    record.description = "meta shape sanity"
    record.author_name = "agent"
    record.author_id = "agent"
    record.filepath = "/tmp/valid_meta.py"
    record.registered_at = MagicMock()
    record.registered_at.isoformat.return_value = "2026-05-24T00:00:00"
    record.validation_warnings = []
    registry.register = AsyncMock(return_value=record)
    return registry


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


def _passing_validation() -> MagicMock:
    v = MagicMock()
    v.valid = True
    v.errors = []
    v.warnings = []
    return v


# ── R1: JSON 모드, dict meta → meta_validation error envelope ────


class TestSubmitDictMetaJson:
    """dict meta가 JSON envelope의 meta_validation 분기로 거부됨을 단정."""

    def test_dict_meta_json_envelope(self, runner: CliRunner) -> None:
        validation = _passing_validation()
        broken_cls = _make_dict_meta_strategy_cls()

        with (
            patch("ante.strategy.validator.StrategyValidator") as mock_validator_cls,
            patch("ante.strategy.loader.StrategyLoader") as mock_loader,
        ):
            mock_validator_cls.return_value.validate.return_value = validation
            mock_loader.load.return_value = broken_cls

            result = runner.invoke(
                cli,
                ["--format", "json", "strategy", "submit", __file__],
            )

        # exit 1: 명시적 SystemExit(1) — traceback 누출 차단.
        assert result.exit_code == 1, (
            f"dict meta가 exit {result.exit_code}로 통과/실패함: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        # stderr 비어있음 — traceback / AttributeError 흔적 없음.
        stderr = result.stderr or ""
        assert "Traceback" not in stderr, f"stderr에 traceback 누출: {stderr!r}"
        assert "AttributeError" not in stderr, (
            f"stderr에 AttributeError 누출: {stderr!r}"
        )

        # JSON envelope 3-필드 단정.
        payload = json.loads(result.stdout)
        assert payload.get("submitted") is False, payload
        assert payload.get("stage") == "meta_validation", payload
        assert payload.get("code") == "STRATEGY_VALIDATION_ERROR", payload
        # error 메시지는 받은 타입(dict)을 사용자에게 노출해야 한다.
        assert "dict" in payload.get("error", ""), payload


# ── R2 sanity: 정상 StrategyMeta 인스턴스는 회귀하지 않음 ─────


class TestSubmitValidMetaSanity:
    """meta shape 분기 추가로 기존 정상 등록 경로가 회귀하지 않음을 단정."""

    def test_valid_meta_instance_registers(self, runner: CliRunner) -> None:
        validation = _passing_validation()
        db = _mock_db()
        registry = _mock_registry_for_valid()

        with (
            patch("ante.strategy.validator.StrategyValidator") as mock_validator_cls,
            patch("ante.strategy.loader.StrategyLoader") as mock_loader,
            patch(
                "ante.cli.commands.strategy._create_registry",
                new=_acm_factory((registry, db)),
            ),
        ):
            mock_validator_cls.return_value.validate.return_value = validation
            mock_loader.load.return_value = _ValidStrategy

            result = runner.invoke(
                cli,
                ["--format", "json", "strategy", "submit", __file__],
            )

        assert result.exit_code == 0, (
            f"valid StrategyMeta 인스턴스가 exit {result.exit_code}로 실패함: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        registry.register.assert_called_once()
        # JSON envelope: submitted=True + meta_validation 누출 없음.
        payload = json.loads(result.stdout)
        assert payload.get("submitted") is True, payload
        assert "stage" not in payload or payload.get("stage") != "meta_validation"


# ── R3: text 모드, dict meta → stderr 키워드 검증 ──────────────


class TestSubmitDictMetaText:
    """text 모드에서도 동일 invariant — stderr에 사용자 메시지 + 코드."""

    def test_dict_meta_text_mode(self, runner: CliRunner) -> None:
        validation = _passing_validation()
        broken_cls = _make_dict_meta_strategy_cls()

        with (
            patch("ante.strategy.validator.StrategyValidator") as mock_validator_cls,
            patch("ante.strategy.loader.StrategyLoader") as mock_loader,
        ):
            mock_validator_cls.return_value.validate.return_value = validation
            mock_loader.load.return_value = broken_cls

            result = runner.invoke(
                cli,
                ["strategy", "submit", __file__],
            )

        assert result.exit_code == 1, (
            f"text 모드 dict meta가 exit {result.exit_code}로 통과/실패함: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        stderr = result.stderr or ""
        # traceback 누출 없음.
        assert "Traceback" not in stderr, stderr
        assert "AttributeError" not in stderr, stderr
        # fmt.error text 경로는 ``Error: <message>`` 한 줄만 인쇄한다
        # (formatter SSOT). 사람이 읽는 메시지 본문에 도메인 키워드 + 실제 받은
        # 타입이 함께 포함됨을 단정한다.
        assert "Invalid meta shape" in stderr, (
            f"stderr에 'Invalid meta shape' 누락: {stderr!r}"
        )
        assert "dict" in stderr, f"stderr에 받은 타입 'dict' 누락: {stderr!r}"
        assert "StrategyMeta" in stderr, (
            f"stderr에 기대 타입 'StrategyMeta' 누락: {stderr!r}"
        )
