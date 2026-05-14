"""CLI date 옵션 strict ISO(``YYYY-MM-DD``) 검증 매트릭스 (#1513).

이슈 #1513: 5개 CLI date 옵션 — `audit list --from-date`, `audit list --to-date`,
`treasury snapshot --date`, `treasury snapshot --from`, `treasury snapshot --to`
— 가 `not-a-date`나 `2026-5-1` 같은 invalid 입력을 exit 0으로 처리하던 ingress
drift를 닫는다. Web API helper(`src/ante/web/utils/date_params.py:29-50`)와
동일한 패턴(regex ``^\\d{4}-\\d{2}-\\d{2}$`` fullmatch 선검사 +
``datetime.strptime`` calendar parse)을 CLI Click callback으로 적용한 결과를
검증한다.

스펙 / 분류:
- `audit list`와 `treasury snapshot`은 `docs/specs/cli/03-commands.md`의 `offline`
  분류이며 IPC route가 없다 (`src/ante/ipc/registry.py`
  `register_all_handlers()` 19개 handler 중 audit/snapshot route 부재).
  따라서 IPC integration 검증은 N/A이며 본 테스트는 CLI Click ingress 경로만
  검증한다.

Non-Goals (follow-up 후보):
- CLI 전반 `--format json` invalid input의 JSON error envelope 표준화.
  본 테스트는 `--format json` 모드에서도 invalid date가 exit != 0이 되는지만
  단정하고, click 표준 stderr text 경로가 JSON envelope가 아니어도 OK로 본다.
- service-runtime gap(`AuditLogger.query`, `Treasury.get_daily_snapshot`은
  invalid str을 그대로 SQL로 전달) — CLI ingress에서 차단되는 이상 위험이
  실현되지 않으므로 본 PR scope 밖.
- 다른 CLI date 옵션(`trade list --from/--to`, `backtest run --start/--end`,
  `report performance --start/--end`, `feed run --since/--until/--date`).

Codex Plan Review v2 권고:
- `CliRunner(mix_stderr=False)`로 stderr 분리 단정 fragility를 방지한다.
- click의 정확한 에러 메시지 텍스트 의존 대신 exit != 0 + (``Invalid value`` 또는
  ``YYYY-MM-DD`` / ``달력 날짜`` / 입력 값 자체) 키워드 강건 매칭.
- valid case 회귀 보존은 mock 복잡도 최소화 — service mock이 까다로우면
  "click parse error 부재"만 단정해도 충분 (#1512와 같은 패턴).
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


def _make_runner() -> CliRunner:
    """`mix_stderr=False` runner. click 버전에 따라 fallback (#1512와 동일 패턴)."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner.

    `authenticate_member`와 `_run_authenticate`를 모두 patch하여 실제 DB 접근을
    방지한다 (#1404 / `test_cli_treasury_snapshot.py` 패턴 참조).
    """
    r = _make_runner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        def _set_member(ctx):  # noqa: ANN001
            ctx.ensure_object(dict)
            ctx.obj["member"] = _MOCK_MASTER

        with (
            patch("ante.cli.main.authenticate_member", side_effect=_set_member),
            patch("ante.cli.middleware._run_authenticate"),
        ):
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _assert_date_rejected(result, *, hint_keywords: tuple[str, ...] = ()) -> None:
    """invalid date 거부에 대한 강건한 단정 (#1512 `_assert_range_rejected` 패턴).

    click 정확한 에러 메시지 텍스트 의존 대신 exit != 0 + (stderr 또는 output에
    'Invalid value' / 'YYYY-MM-DD' / '달력 날짜' / hint 키워드 중 하나 포함)로
    검증한다. `mix_stderr=False`에서 stderr가 분리됐을 수 있으므로 둘 다 본다.
    """
    assert result.exit_code != 0, (
        f"exit_code expected != 0, got {result.exit_code}; output={result.output!r}, "
        f"stderr={getattr(result, 'stderr', '')!r}"
    )
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    haystack = combined.lower()
    has_invalid_value = "invalid value" in haystack
    has_format_hint = "yyyy-mm-dd" in haystack or "달력 날짜" in combined
    has_hint = any(k.lower() in haystack for k in hint_keywords)
    assert has_invalid_value or has_format_hint or has_hint, (
        f"expected 'Invalid value', 'YYYY-MM-DD', '달력 날짜' or one of "
        f"{hint_keywords} in output/stderr; "
        f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
    )


# ── 옵션 매트릭스 ────────────────────────────────────────────────
# audit `--from-date`, `--to-date` + treasury `--date`, `--from`, `--to`
# 5개 옵션을 (명령, 옵션-args 빌더, hint) 튜플로 표현.

# `treasury snapshot`은 `--account` required, `audit list`는 추가 args 불필요.
_AUDIT_FROM_DATE = (
    "audit-from-date",
    lambda v: ["audit", "list", "--from-date", v],
)
_AUDIT_TO_DATE = (
    "audit-to-date",
    lambda v: ["audit", "list", "--to-date", v],
)
_TREASURY_DATE = (
    "treasury-date",
    lambda v: ["treasury", "snapshot", "--date", v, "--account", "test"],
)
_TREASURY_FROM = (
    "treasury-from",
    lambda v: ["treasury", "snapshot", "--from", v, "--account", "test"],
)
_TREASURY_TO = (
    "treasury-to",
    lambda v: ["treasury", "snapshot", "--to", v, "--account", "test"],
)

ALL_OPTIONS = [
    _AUDIT_FROM_DATE,
    _AUDIT_TO_DATE,
    _TREASURY_DATE,
    _TREASURY_FROM,
    _TREASURY_TO,
]


INVALID_FORMAT_VALUES = [
    "not-a-date",
    "2026/05/13",
    "13-05-2026",
]

NON_ZERO_PADDED_VALUES = [
    "2026-5-1",
    "2026-05-1",
    "2026-5-13",
]

INVALID_CALENDAR_VALUES = [
    # regex는 통과하지만 strptime이 거부.
    "2026-13-01",  # month > 12
    "2026-02-30",  # 30 of Feb
    "2026-02-29",  # 2026 is non-leap
]

VALID_VALUES = [
    "2026-05-13",
    "2024-02-29",  # leap year valid edge
]


# ── invalid format 거부 ──────────────────────────────────────────


@pytest.mark.parametrize(
    "option_id,args_builder",
    ALL_OPTIONS,
    ids=[opt[0] for opt in ALL_OPTIONS],
)
@pytest.mark.parametrize("value", INVALID_FORMAT_VALUES)
def test_invalid_format_rejected(
    option_id: str,
    args_builder,
    value: str,
    runner: CliRunner,
) -> None:
    """잘못된 형식(`not-a-date`, `2026/05/13`, `13-05-2026`)은 exit != 0."""
    result = runner.invoke(cli, args_builder(value))
    _assert_date_rejected(result, hint_keywords=(value, option_id))


# ── non-zero-padded 거부 (regex fullmatch) ────────────────────────


@pytest.mark.parametrize(
    "option_id,args_builder",
    ALL_OPTIONS,
    ids=[opt[0] for opt in ALL_OPTIONS],
)
@pytest.mark.parametrize("value", NON_ZERO_PADDED_VALUES)
def test_non_zero_padded_rejected(
    option_id: str,
    args_builder,
    value: str,
    runner: CliRunner,
) -> None:
    """zero-padded 아님(`2026-5-1`, `2026-05-1`, `2026-5-13`)은 regex가 거부."""
    result = runner.invoke(cli, args_builder(value))
    _assert_date_rejected(result, hint_keywords=(value, option_id))


# ── invalid calendar 거부 (strptime) ──────────────────────────────


@pytest.mark.parametrize(
    "option_id,args_builder",
    ALL_OPTIONS,
    ids=[opt[0] for opt in ALL_OPTIONS],
)
@pytest.mark.parametrize("value", INVALID_CALENDAR_VALUES)
def test_invalid_calendar_rejected(
    option_id: str,
    args_builder,
    value: str,
    runner: CliRunner,
) -> None:
    """캘린더 invalid 입력(`2026-13-01`, `2026-02-30`, `2026-02-29`)은 strptime 거부."""
    result = runner.invoke(cli, args_builder(value))
    _assert_date_rejected(result, hint_keywords=(value, option_id))


# ── valid 값 회귀 보존 (click parse error 부재만 단정) ──────────────


@pytest.mark.parametrize(
    "option_id,args_builder",
    ALL_OPTIONS,
    ids=[opt[0] for opt in ALL_OPTIONS],
)
@pytest.mark.parametrize("value", VALID_VALUES)
def test_valid_passes_click_ingress(
    option_id: str,
    args_builder,
    value: str,
    runner: CliRunner,
) -> None:
    """valid date(`2026-05-13`, `2024-02-29` 윤년)는 click parse error를 내지 않는다.

    backend mock 정확도가 fragile하므로(audit는 `Database`/`AuditLogger` lazy
    import, treasury는 `_create_treasury` async flow) #1512 패턴대로
    "click.BadParameter / 'Invalid value' 부재"만 강건하게 단정한다.
    핸들러가 이후 backend 단계에서 실패해도 OK — 본 invariant는 'callback이
    valid date를 거부하지 않는다'이므로 ingress 통과만 보장한다.
    """
    result = runner.invoke(cli, args_builder(value))
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "Invalid value" not in combined, (
        f"valid {value!r} on {option_id} should not trigger click parse error; "
        f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
    )
    # click.BadParameter가 raise되지 않아야 한다.
    if result.exception is not None:
        assert not isinstance(result.exception, click.BadParameter), (
            f"valid {value!r} on {option_id} should not raise click.BadParameter; "
            f"got {result.exception!r}"
        )


# ── 옵션 미지정 (None) 회귀 보존 ───────────────────────────────────


class TestAuditListOmitDates:
    """`audit list` (date 옵션 미지정) ingress 통과 회귀 보존.

    callback은 ``None``일 때 그대로 ``None``을 반환해 기존 동작(옵션 생략)을
    깨지 않아야 한다. backend mock fragility 때문에 'click parse error 부재'만
    단정한다 (#1512 패턴).
    """

    def test_omit_dates_passes_ingress(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["audit", "list"])
        combined = (result.output or "") + (getattr(result, "stderr", "") or "")
        assert "Invalid value" not in combined, (
            f"omitting --from-date/--to-date should not trigger click parse error; "
            f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
        )
        if result.exception is not None:
            assert not isinstance(result.exception, click.BadParameter), (
                f"omitting dates should not raise click.BadParameter; "
                f"got {result.exception!r}"
            )


class TestTreasurySnapshotOmitDates:
    """`treasury snapshot` (date 옵션 미지정) ingress 통과 회귀 보존."""

    def test_omit_dates_passes_ingress(self, runner: CliRunner) -> None:
        # `_create_treasury` async flow를 mock하여 실제 DB 접근을 방지.
        mock_treasury = AsyncMock()
        mock_treasury.get_daily_snapshot = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.treasury._create_treasury",
            new_callable=AsyncMock,
            return_value=(mock_treasury, mock_db),
        ):
            result = runner.invoke(cli, ["treasury", "snapshot", "--account", "test"])
        combined = (result.output or "") + (getattr(result, "stderr", "") or "")
        assert "Invalid value" not in combined, (
            f"omitting --date/--from/--to should not trigger click parse error; "
            f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
        )
        if result.exception is not None:
            assert not isinstance(result.exception, click.BadParameter), (
                f"omitting dates should not raise click.BadParameter; "
                f"got {result.exception!r}"
            )


# ── --format json 모드 invalid date 거부 ─────────────────────────


class TestFormatJsonInvalidDate:
    """`--format json` 모드에서도 invalid date는 exit != 0.

    `--format json` JSON error envelope 표준화는 본 PR Non-Goals이지만,
    oracle probe `expected_exit=nonzero` 요구는 JSON 모드에서도 충족되어야
    한다. click.BadParameter는 표준 text stderr 경로(JSON envelope 아님)로
    가더라도 exit 2가 보장되므로 그것만 단정한다.
    """

    def test_audit_list_format_json_invalid_from_date(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["--format", "json", "audit", "list", "--from-date", "not-a-date"],
        )
        _assert_date_rejected(result, hint_keywords=("not-a-date", "from-date"))

    def test_treasury_snapshot_format_json_invalid_date(
        self, runner: CliRunner
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "treasury",
                "snapshot",
                "--date",
                "not-a-date",
                "--account",
                "test",
            ],
        )
        _assert_date_rejected(result, hint_keywords=("not-a-date", "date"))
