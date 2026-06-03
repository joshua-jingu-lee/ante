"""CLI --format json 서브커맨드 뒤 배치 테스트.

이슈 #632: `ante account list --format json` 형태로 호출할 때
서브커맨드 뒤의 --format 옵션이 올바르게 동작하는지 검증한다.

이슈 #1701: ``report schema``, ``data list``, ``bot list``, ``member info`` 4개
trailing 명령에도 ``@format_option`` 누락이 잔존해 ``Error: No such option:
--format`` 으로 거부되던 ingress drift를 닫는다. 4 case (+ default text
회귀 1건)는 본 파일의 #632 패턴을 그대로 미러한다 (additive backward-compat).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.commands.bot import bot_list
from ante.cli.commands.data import data_list
from ante.cli.commands.member import member_info
from ante.cli.commands.report import schema as report_schema
from ante.cli.formatter import OutputFormatter
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from tests.unit._async_test_utils import asyncio_run_returning


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


def _patch_account_factory(svc, db):  # noqa: ANN001, ANN202
    """#1856: ``_create_account_service`` 가 async context manager 로 전환된 후
    fake factory 가 ``ctx`` 인자를 받아 ``svc`` 만 yield 하도록 한다.

    ``db`` 인자는 backward-compat 시그니처로 유지되지만, 새 context manager 의
    내부에서는 ``open_cli_db`` 헬퍼가 DB lifecycle 을 캡슐화하므로 fake 도 svc
    만 yield 한다.
    """
    _ = db  # backward-compat — unused inside fake factory

    @asynccontextmanager
    async def _fake_factory(ctx=None):  # noqa: ANN001, ANN202
        yield svc

    return patch(
        "ante.cli.commands.account._create_account_service",
        new=_fake_factory,
    )


def _patch_member_factory(svc, db):  # noqa: ANN001, ANN202
    """#1856: ``member._create_service`` async context manager fake factory."""
    _ = db

    @asynccontextmanager
    async def _fake_factory(ctx=None):  # noqa: ANN001, ANN202
        yield svc

    return patch(
        "ante.cli.commands.member._create_service",
        new=_fake_factory,
    )


_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner."""
    r = CliRunner()
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


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


# ── member list --format json ────────────────────────────


class TestMemberListFormatOption:
    """ante member list --format json (서브커맨드 뒤 배치)."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        """member list --format json 이 올바르게 JSON 출력."""
        svc = MagicMock()
        db = _mock_db()
        svc.list_members = AsyncMock(return_value=[])

        with _patch_member_factory(svc, db):
            result = runner.invoke(cli, ["member", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "members" in data or "message" in data

    def test_format_before_subcommand_still_works(self, runner: CliRunner) -> None:
        """--format json member list (루트 옵션) 도 여전히 동작."""
        svc = MagicMock()
        db = _mock_db()
        svc.list_members = AsyncMock(return_value=[])

        with _patch_member_factory(svc, db):
            result = runner.invoke(cli, ["--format", "json", "member", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "members" in data or "message" in data


# ── member register --format json ────────────────────────


class TestMemberRegisterFormatOption:
    """ante member register ... --format json."""

    def test_register_format_after(self, runner: CliRunner) -> None:
        """register --format json 이 JSON 출력."""
        svc = MagicMock()
        db = _mock_db()
        mock_member = MagicMock()
        mock_member.member_id = "new-agent"
        mock_member.type = "agent"
        mock_member.role = "member"
        mock_member.org = "default"
        mock_member.name = "Agent"
        svc.register = AsyncMock(return_value=(mock_member, "token-123"))

        with _patch_member_factory(svc, db):
            result = runner.invoke(
                cli,
                [
                    "member",
                    "register",
                    "--id",
                    "new-agent",
                    "--type",
                    "agent",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["member_id"] == "new-agent"
            assert data["token"] == "token-123"


# ── account list --format json ────────────────────────────


class TestAccountListFormatOption:
    """ante account list --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        svc = AsyncMock()
        db = _mock_db()
        svc.list.return_value = []

        with _patch_account_factory(svc, db):
            result = runner.invoke(cli, ["account", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "accounts" in data or "message" in data


# ── account info --format json ────────────────────────────


class TestAccountInfoFormatOption:
    """ante account info {id} --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        from decimal import Decimal

        from ante.account.models import Account, AccountStatus, TradingMode

        svc = AsyncMock()
        db = _mock_db()
        svc.get.return_value = Account(
            account_id="test-acct",
            name="테스트",
            exchange="KRX",
            currency="KRW",
            broker_type="mock",
            status=AccountStatus.ACTIVE,
            trading_mode=TradingMode.VIRTUAL,
            credentials={},
            buy_commission_rate=Decimal("0.00015"),
            sell_commission_rate=Decimal("0.00195"),
        )

        with _patch_account_factory(svc, db):
            result = runner.invoke(
                cli, ["account", "info", "test-acct", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["account_id"] == "test-acct"


# ── account delete --yes ──────────────────────────────


class TestAccountDeleteYes:
    """ante account delete {id} --yes (#1139: IPC → cold-path direct service)."""

    def test_delete_with_yes_skips_confirm(self, runner: CliRunner) -> None:
        svc = AsyncMock()
        db = _mock_db()
        svc.delete.return_value = None

        with (
            _patch_account_factory(svc, db),
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_offline_fmt_del__.sock",
            ),
        ):
            result = runner.invoke(cli, ["account", "delete", "test-acct", "--yes"])

        assert result.exit_code == 0
        assert "삭제 완료" in result.output
        svc.delete.assert_called_once()

    def test_delete_without_yes_requires_confirmation(self, runner: CliRunner) -> None:
        """``--yes`` 없이 호출하면 prompt 없이 ``CLI_CONFIRMATION_REQUIRED``로 실패한다.

        SSOT: docs/specs/cli/02-design-decisions.md — 위험 명령 확인 방식 표.
        """
        svc = AsyncMock()
        db = _mock_db()
        svc.delete.return_value = None

        with (
            _patch_account_factory(svc, db),
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_offline_fmt_del2__.sock",
            ),
        ):
            result = runner.invoke(cli, ["account", "delete", "test-acct"])

        assert result.exit_code == 1
        assert "CLI_CONFIRMATION_REQUIRED" in result.output
        svc.delete.assert_not_called()


# ── treasury status --format json ─────────────────────────


class TestTreasuryStatusFormatOption:
    """ante treasury status --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_treasury = MagicMock()
        db = _mock_db()
        mock_treasury.get_summary.return_value = {
            "account_balance": 1000000,
            "purchasable_amount": 800000,
            "total_evaluation": 1200000,
            "total_profit_loss": 200000,
            "total_allocated": 500000,
            "total_reserved": 100000,
            "unallocated": 300000,
            "bot_count": 2,
        }

        with patch(
            "ante.cli.commands.treasury._create_treasury",
            new=_acm_factory((mock_treasury, db)),
        ):
            result = runner.invoke(
                cli,
                [
                    "treasury",
                    "status",
                    "--account",
                    "domestic",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["account_balance"] == 1000000
            assert data["bot_count"] == 2


# ── strategy list --format json ───────────────────────────


class TestStrategyListFormatOption:
    """ante strategy list --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        db = _mock_db()
        registry = MagicMock()
        registry.list_strategies = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new=_acm_factory((registry, db)),
        ):
            result = runner.invoke(cli, ["strategy", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "strategies" in data or "message" in data


# ── strategy info --format json ───────────────────────────


class TestStrategyInfoFormatOption:
    """ante strategy info {name} --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        from datetime import UTC, datetime

        from ante.strategy.registry import StrategyRecord, StrategyStatus

        db = _mock_db()
        record = StrategyRecord(
            strategy_id="test_v1.0",
            name="test",
            version="1.0",
            filepath="/strats/test.py",
            status=StrategyStatus.ADOPTED,
            registered_at=datetime(2026, 1, 1, tzinfo=UTC),
            description="테스트 전략",
            author_name="agent",
            author_id="agent",
            validation_warnings=[],
        )
        registry = MagicMock()
        registry.get_by_name = AsyncMock(return_value=[record])

        with (
            patch(
                "ante.cli.commands.strategy._create_registry",
                new=_acm_factory((registry, db)),
            ),
            patch(
                "ante.cli.commands.strategy._load_strategy_params",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli, ["strategy", "info", "test", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "test"


# ── config get --format json ──────────────────────────────


class TestConfigGetFormatOption:
    """ante config get --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda k, d=None: d
        mock_dynamic = AsyncMock()
        mock_db = AsyncMock()
        mock_db.fetch_all = AsyncMock(return_value=[])
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new=_acm_factory((mock_config, mock_dynamic, mock_db)),
        ):
            result = runner.invoke(cli, ["config", "get", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "configs" in data


# ── config set --format json ──────────────────────────────


class TestConfigSetFormatOption:
    """ante config set KEY VALUE --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"success": True, "key": "custom.key", "value": "hello"},
        }

        with (
            patch(
                "ante.cli.commands.ipc_helpers.IPCClient",
                return_value=mock_client,
            ),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
        ):
            result = runner.invoke(
                cli, ["config", "set", "custom.key", "hello", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True


# ── config history --format json ──────────────────────────


class TestConfigHistoryFormatOption:
    """ante config history KEY --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_dynamic = AsyncMock()
        mock_dynamic.get_history = AsyncMock(return_value=[])
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new=_acm_factory((mock_config, mock_dynamic, mock_db)),
        ):
            result = runner.invoke(
                cli,
                ["config", "history", "risk.test_qa_key", "--format", "json"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["key"] == "risk.test_qa_key"
            assert data["history"] == []


# ── trade list --format json ──────────────────────────────


class TestTradeListFormatOption:
    """ante trade list --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        svc = MagicMock()
        db = _mock_db()
        svc.get_trades = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.trade._create_trade_service",
            new=_acm_factory((svc, db)),
        ):
            result = runner.invoke(cli, ["trade", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "trades" in data or "message" in data


# ── trade info --format json ──────────────────────────────


class TestTradeInfoFormatOption:
    """ante trade info {id} --format json.

    #1515: missing-resource는 JSON error envelope과 함께 exit code 1을 반환한다.
    이 테스트는 --format json 옵션의 서브커맨드 뒤 배치 동작을 검증하면서,
    동시에 missing case가 nonzero exit를 내는지도 확인한다.
    """

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.cli.commands.trade.asyncio.run",
            side_effect=asyncio_run_returning(None),
        ):
            result = runner.invoke(
                cli, ["trade", "info", "trade-123", "--format", "json"]
            )
            # #1515: missing trade는 exit 1 + JSON error envelope.
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert "message" in data
            assert data["status"] == "error"


# ── account set-credentials 비대화형 테스트 ────────────────


class TestAccountSetCredentialsNonInteractive:
    """ante account set-credentials --credential KEY=VALUE (모든 required key)."""

    def test_set_credentials_non_interactive(self, runner: CliRunner) -> None:
        from decimal import Decimal

        from ante.account.models import Account, AccountStatus, TradingMode

        svc = AsyncMock()
        db = _mock_db()
        svc.get.return_value = Account(
            account_id="test-acct",
            name="테스트",
            exchange="KRX",
            currency="KRW",
            broker_type="kis-domestic",
            status=AccountStatus.ACTIVE,
            trading_mode=TradingMode.VIRTUAL,
            credentials={},
            buy_commission_rate=Decimal("0.00015"),
            sell_commission_rate=Decimal("0.00195"),
        )

        with (
            _patch_account_factory(svc, db),
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_offline_fmt_setc__.sock",
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "account",
                    "set-credentials",
                    "test-acct",
                    "--credential",
                    "app_key=my-key",
                    "--credential",
                    "app_secret=my-secret",
                    "--credential",
                    "account_no=50123456-01",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0, result.output
            assert "재설정 완료" in result.output
            svc.update.assert_called_once()
            # 전달된 credentials 확인 (kis-domestic preset의 모든 required key 포함)
            call_kwargs = svc.update.call_args
            creds = call_kwargs.kwargs.get("credentials") or call_kwargs[1].get(
                "credentials"
            )
            assert creds["app_key"] == "my-key"
            assert creds["app_secret"] == "my-secret"
            assert creds["account_no"] == "50123456-01"


# ── #1701: trailing 4 commands 정적 + runtime 회귀 ─────────────


_TRAILING_SUBCOMMANDS_1701 = [
    ("report schema", report_schema),
    ("data list", data_list),
    ("bot list", bot_list),
    ("member info", member_info),
]


class TestTrailingFormatOptionRegistered1701:
    """#1701: 4개 trailing 명령에 ``--format`` 옵션이 등록되어 있는지 정적 검증.

    ``test_cli_approval_format_option`` 의 1:1 미러 패턴 (#1078 sibling).
    decorator 누락 회귀를 click 메타데이터 레벨에서 감지한다.
    """

    @pytest.mark.parametrize(
        "name,cmd",
        _TRAILING_SUBCOMMANDS_1701,
        ids=[s[0] for s in _TRAILING_SUBCOMMANDS_1701],
    )
    def test_format_option_exists(self, name: str, cmd: click.Command) -> None:
        """``{name}`` 커맨드에 ``--format`` 옵션이 존재해야 한다."""
        param_names = [p.name for p in cmd.params]
        assert "output_format" in param_names, (
            f"{name} 커맨드에 --format 옵션이 없습니다 (issue #1701)"
        )

    @pytest.mark.parametrize(
        "name,cmd",
        _TRAILING_SUBCOMMANDS_1701,
        ids=[s[0] for s in _TRAILING_SUBCOMMANDS_1701],
    )
    def test_format_option_choices(self, name: str, cmd: click.Command) -> None:
        """``--format`` 옵션은 text/json 중 선택 가능해야 한다."""
        fmt_param = next(p for p in cmd.params if p.name == "output_format")
        assert isinstance(fmt_param.type, click.Choice)
        assert "json" in fmt_param.type.choices
        assert "text" in fmt_param.type.choices


class TestReportSchemaFormatOption1701:
    """#1701: ``ante report schema --format json`` 은 exit 0 + valid JSON."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["report", "schema", "--format", "json"])

        assert result.exit_code == 0, result.output
        # ReportStore.get_schema()는 dict를 반환하므로 JSON parse 가능해야 한다.
        payload = json.loads(result.output)
        assert isinstance(payload, dict)

    def test_default_text_output_preserved(self, runner: CliRunner) -> None:
        """``--format`` 미지정 시 기본 text 출력은 그대로 유지된다 (additive)."""
        result = runner.invoke(cli, ["report", "schema"])

        assert result.exit_code == 0, result.output
        # text 모드는 ``OutputFormatter.output``이 ``str(data)`` 로 echo —
        # JSON 모드의 indented dump (``{\n  "...":`` 패턴)와 구분된다.
        assert not result.output.startswith("{\n  ")


class TestDataListFormatOption1701:
    """#1701: ``ante data list --format json`` 은 exit 0 + valid JSON."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        """ParquetStore가 빈 디렉토리를 반환하면 ``{datasets:[],count:0}`` 출력."""
        mock_store = MagicMock()
        mock_store.list_symbols.return_value = []

        with patch("ante.data.store.ParquetStore", return_value=mock_store):
            result = runner.invoke(cli, ["data", "list", "--format", "json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload == {"datasets": [], "count": 0}


class TestBotListFormatOption1701:
    """#1701: ``ante bot list --format json`` 은 exit 0 + valid JSON."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        """봇이 없을 때 ``{message:..., bots:[]}`` 출력."""
        mock_db = _mock_db()
        mock_db.fetch_all = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.bot._create_services",
            new=_acm_factory((mock_db, None, None, None)),
        ):
            result = runner.invoke(cli, ["bot", "list", "--format", "json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "bots" in payload
        assert payload["bots"] == []


class TestMemberInfoFormatOption1701:
    """#1701: ``ante member info <id> --format json`` 은 exit 0 + valid JSON.

    기존 ``TestMemberInfoMissingExit.test_valid_exits_zero`` (#1515)는 루트 그룹
    ``--format`` 을 사용했으나, #1701은 서브커맨드 위치 ``--format`` (member info
    <id> --format json) 의 등록을 검증한다.
    """

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        existing = Member(
            member_id="m-1701",
            type=MemberType.HUMAN,
            role=MemberRole.DEFAULT,
            org="default",
            name="Existing",
            status="active",
            scopes=[],
        )
        svc = MagicMock()
        svc.get = AsyncMock(return_value=existing)
        db = _mock_db()

        with _patch_member_factory(svc, db):
            result = runner.invoke(
                cli, ["member", "info", "m-1701", "--format", "json"]
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["member_id"] == "m-1701"


# ── #2024: non-finite float → strict JSON null 정규화 ──────────


def _capture_formatter_output(fn) -> str:  # noqa: ANN001
    """``OutputFormatter`` 가 ``click.echo`` 한 stdout 을 캡처한다.

    ``CliRunner.isolation()`` 은 click 의 출력 스트림을 가로채므로 click 명령
    호출 없이 포맷터 단독 출력도 안전하게 수집할 수 있다.
    """
    runner = CliRunner()
    with runner.isolation() as (stdout, _stderr):
        fn()
    return stdout.getvalue().decode("utf-8")


class TestNonFiniteFloatStrictJson2024:
    """#2024: ``--format json`` 출력이 inf/nan 을 ``null`` 로 정규화해 strict JSON.

    SSOT: 손실 0 건 백테스트의 ``profit_factor=inf`` 같은 non-finite float 가
    비표준 ``Infinity``/``NaN`` 토큰으로 직렬화되면 strict JSON parser(Agent
    파싱 표면)가 실패한다. ``allow_nan=False`` + sanitize 로 ``null`` 정규화한다.
    """

    def test_output_inf_becomes_null_and_strict_parseable(self) -> None:
        """(a) profit_factor=inf 출력이 strict json.loads 성공 + None."""
        fmt = OutputFormatter("json")
        out = _capture_formatter_output(
            lambda: fmt.output({"metrics": {"profit_factor": float("inf")}})
        )
        # strict parse (allow_nan 기본 False) — Infinity 토큰이면 raise.
        payload = json.loads(out)
        assert payload["metrics"]["profit_factor"] is None

    def test_output_negative_inf_and_nan_become_null(self) -> None:
        """(b) -inf, nan 모두 None."""
        fmt = OutputFormatter("json")
        out = _capture_formatter_output(
            lambda: fmt.output(
                {
                    "neg_inf": float("-inf"),
                    "nan": float("nan"),
                }
            )
        )
        payload = json.loads(out)
        assert payload["neg_inf"] is None
        assert payload["nan"] is None

    def test_output_nested_dict_list_non_finite_become_null(self) -> None:
        """(c) 중첩 dict/list 내부 non-finite → None."""
        fmt = OutputFormatter("json")
        out = _capture_formatter_output(
            lambda: fmt.output(
                {
                    "outer": {
                        "inner": [
                            {"pf": float("inf")},
                            float("nan"),
                            1.5,
                        ],
                    },
                }
            )
        )
        payload = json.loads(out)
        assert payload["outer"]["inner"][0]["pf"] is None
        assert payload["outer"]["inner"][1] is None
        assert payload["outer"]["inner"][2] == 1.5

    def test_output_finite_values_preserved(self) -> None:
        """(d) 회귀: finite float/int/str/bool 값 보존 (bool 은 None 아님)."""
        fmt = OutputFormatter("json")
        out = _capture_formatter_output(
            lambda: fmt.output(
                {
                    "ratio": 1.5,
                    "count": 7,
                    "name": "alpha",
                    "flag_true": True,
                    "flag_false": False,
                }
            )
        )
        payload = json.loads(out)
        assert payload["ratio"] == 1.5
        assert payload["count"] == 7
        assert payload["name"] == "alpha"
        # bool 은 float 로 강등돼 None 되면 안 됨.
        assert payload["flag_true"] is True
        assert payload["flag_false"] is False

    def test_table_path_inf_strict_parseable(self) -> None:
        """(e) table() 경로도 inf 포함 시 strict JSON."""
        fmt = OutputFormatter("json")
        out = _capture_formatter_output(
            lambda: fmt.table(
                [{"symbol": "AAA", "pf": float("inf")}],
                ["symbol", "pf"],
            )
        )
        payload = json.loads(out)
        assert isinstance(payload, list)
        assert payload[0]["pf"] is None
        assert payload[0]["symbol"] == "AAA"

    def test_success_path_inf_strict_parseable(self) -> None:
        """(e) success() 경로도 inf 포함 시 strict JSON."""
        fmt = OutputFormatter("json")
        out = _capture_formatter_output(
            lambda: fmt.success("done", data={"pf": float("inf")})
        )
        payload = json.loads(out)
        assert payload["status"] == "ok"
        assert payload["data"]["pf"] is None

    def test_datetime_value_serialized_via_default_str(self) -> None:
        """(f) 회귀: datetime 값은 default=str 로 문자열 직렬화 유지."""
        from datetime import UTC, datetime

        fmt = OutputFormatter("json")
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        out = _capture_formatter_output(lambda: fmt.output({"ts": dt}))
        payload = json.loads(out)
        assert payload["ts"] == str(dt)
