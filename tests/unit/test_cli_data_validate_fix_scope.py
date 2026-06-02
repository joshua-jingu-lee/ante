"""`ante data validate --fix` 의 data:write scope 조건부 검증 테스트 (#2108).

`data validate` 데코레이터는 `@require_scope("data:read")` 로 순수 검증 권한을
요구하지만, `--fix` 는 손상 파일을 `.corrupted` 로 격리(rename)하는 mutating
경로다. flat scope 모델(`src/ante/member/scopes.py` SSOT — 계층 없음)에서
`data:write` 는 `data:read` 를 함의하지 않으므로, 명령 본문에서
`enforce_scope(ctx, "data:write")` 로 write 권한을 조건부 검증한다.

검증 행렬:
- data:read 만 가진 Agent + `--fix` → permission_denied(exit 1, 필요 권한
  data:write). 실제 파일 mutation(store.validate) 미도달.
- {data:read, data:write} Agent + `--fix` → 통과(store.validate(..., fix=True)
  도달).
- data:read Agent + `--fix` 없는 `validate` → 통과(read 유지, 회귀 없음).
- Human(master) + `--fix` → scope 무관 통과.
- write-only(data:write만, data:read 없음) Agent + `--fix` →
  `@require_scope("data:read")` 데코레이터가 먼저 data:read 부족으로 거부
  (둘 다 필요 모델 검증).
"""

from __future__ import annotations

import json
from unittest.mock import patch

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

_AGENT_READ_ONLY = Member(
    member_id="agent-read",
    type=MemberType.AGENT,
    role=MemberRole.DEFAULT,
    org="default",
    name="Read-only Agent",
    status="active",
    scopes=["data:read"],
)

_AGENT_READ_WRITE = Member(
    member_id="agent-readwrite",
    type=MemberType.AGENT,
    role=MemberRole.DEFAULT,
    org="default",
    name="Read+Write Agent",
    status="active",
    scopes=["data:read", "data:write"],
)

_AGENT_WRITE_ONLY = Member(
    member_id="agent-write",
    type=MemberType.AGENT,
    role=MemberRole.DEFAULT,
    org="default",
    name="Write-only Agent",
    status="active",
    scopes=["data:write"],
)


def _runner_for(member: Member) -> CliRunner:
    """지정 멤버로 인증되는 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_member(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001, ANN202
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = member

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_member
    return r


def _validate_args(*extra: str) -> list[str]:
    return ["data", "validate", *extra]


class TestValidateFixScopeDenied:
    """data:read 만 가진 Agent 의 `--fix` 거부 + 파일 mutation 미도달."""

    def test_read_only_agent_fix_denied_text(self):
        """data:read Agent + --fix → permission_denied(exit 1, data:write)."""
        runner = _runner_for(_AGENT_READ_ONLY)
        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli, _validate_args("--symbol", "005930", "--timeframe", "1d", "--fix")
            )
        assert result.exit_code == 1, result.output
        assert "권한이 부족합니다" in result.output
        assert "data:write" in result.output
        # 권한 거부가 어떤 파일 mutation(ParquetStore 사용)보다 먼저 발화.
        mock_store.assert_not_called()

    def test_read_only_agent_fix_denied_json(self):
        """--format json: permission_denied 구조화 envelope."""
        runner = _runner_for(_AGENT_READ_ONLY)
        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    *_validate_args("--symbol", "005930", "--timeframe", "1d", "--fix"),
                ],
            )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "permission_denied"
        assert "data:write" in payload["message"]
        mock_store.assert_not_called()


class TestValidateFixScopeFailFast:
    """권한 체크가 입력검증·경로 resolution 보다 먼저 발화하는지 (fail-fast).

    #2108 Codex 브랜치 리뷰 후속: `enforce_scope` 를 함수 본문 최상단(입력검증·
    경로 resolution 이전)으로 이동했다. 미인가(read-only) 토큰은 입력 유효성과
    무관하게 즉시 `permission_denied` 여야 하며, invalid timeframe/symbol 을
    함께 줘도 `DATA_VALIDATE_INVALID_*` 가 아니라 `permission_denied` 가 먼저
    나와야 한다(정보 노출 순서 정리 + 어떤 side effect 보다 우선).
    """

    def test_read_only_agent_fix_invalid_timeframe_denied_first(self):
        """read-only Agent + --fix + invalid timeframe → permission_denied 우선."""
        runner = _runner_for(_AGENT_READ_ONLY)
        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    *_validate_args(
                        "--symbol",
                        "005930",
                        "--timeframe",
                        "9z",
                        "--fix",
                    ),
                ],
            )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        # 권한 거부가 invalid timeframe 검증보다 먼저 발화한다.
        assert payload["code"] == "permission_denied"
        assert payload["code"] != "DATA_VALIDATE_INVALID_TIMEFRAME"
        assert "data:write" in payload["message"]
        mock_store.assert_not_called()

    def test_read_only_agent_fix_invalid_symbol_denied_first(self):
        """read-only Agent + --fix + invalid symbol → permission_denied 우선."""
        runner = _runner_for(_AGENT_READ_ONLY)
        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    *_validate_args(
                        "--symbol",
                        "BAD",
                        "--timeframe",
                        "1d",
                        "--fix",
                    ),
                ],
            )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        # 권한 거부가 invalid symbol 검증보다 먼저 발화한다.
        assert payload["code"] == "permission_denied"
        assert payload["code"] != "DATA_VALIDATE_INVALID_SYMBOL"
        assert "data:write" in payload["message"]
        mock_store.assert_not_called()


class TestValidateFixScopeAllowed:
    """write 권한 보유/Human 의 `--fix` 통과."""

    def test_read_write_agent_fix_passes(self):
        """{data:read, data:write} Agent + --fix → store.validate(fix=True) 도달."""
        runner = _runner_for(_AGENT_READ_WRITE)
        with patch("ante.data.store.ParquetStore") as mock_store:
            instance = mock_store.return_value
            instance.validate.return_value = {
                "symbol": "005930",
                "timeframe": "1d",
                "total": 1,
                "valid": 1,
                "corrupted": 0,
                "corrupted_files": [],
            }
            result = runner.invoke(
                cli, _validate_args("--symbol", "005930", "--timeframe", "1d", "--fix")
            )
        assert result.exit_code == 0, result.output
        assert "권한이 부족합니다" not in result.output
        instance.validate.assert_called_once_with("005930", "1d", fix=True)

    def test_master_fix_passes_regardless_of_scope(self):
        """Human(master) + --fix → scope 무관 통과."""
        runner = _runner_for(_MOCK_MASTER)
        with patch("ante.data.store.ParquetStore") as mock_store:
            instance = mock_store.return_value
            instance.validate.return_value = {
                "symbol": "005930",
                "timeframe": "1d",
                "total": 1,
                "valid": 1,
                "corrupted": 0,
                "corrupted_files": [],
            }
            result = runner.invoke(
                cli, _validate_args("--symbol", "005930", "--timeframe", "1d", "--fix")
            )
        assert result.exit_code == 0, result.output
        assert "권한이 부족합니다" not in result.output
        instance.validate.assert_called_once_with("005930", "1d", fix=True)


class TestValidateReadNoRegression:
    """`--fix` 없는 read-only 경로 회귀 방지."""

    def test_read_only_agent_validate_without_fix_passes(self):
        """data:read Agent + (no --fix) → 통과(read 유지). store.validate(fix=False)."""
        runner = _runner_for(_AGENT_READ_ONLY)
        with patch("ante.data.store.ParquetStore") as mock_store:
            instance = mock_store.return_value
            instance.validate.return_value = {
                "symbol": "005930",
                "timeframe": "1d",
                "total": 1,
                "valid": 1,
                "corrupted": 0,
                "corrupted_files": [],
            }
            result = runner.invoke(
                cli, _validate_args("--symbol", "005930", "--timeframe", "1d")
            )
        assert result.exit_code == 0, result.output
        assert "권한이 부족합니다" not in result.output
        instance.validate.assert_called_once_with("005930", "1d", fix=False)


class TestValidateFixWriteOnlyDeniedByReadDecorator:
    """write-only Agent 는 `@require_scope("data:read")` 데코레이터가 먼저 거부.

    flat scope 모델에서 `validate --fix` 는 data:read 와 data:write 를 모두
    요구한다. data:read 가 없으면 본문 `enforce_scope` 에 도달하기 전에
    데코레이터에서 거부된다.
    """

    def test_write_only_agent_fix_denied_by_read_decorator(self):
        """data:write만 가진 Agent + --fix → data:read 부족으로 데코레이터 거부."""
        runner = _runner_for(_AGENT_WRITE_ONLY)
        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    *_validate_args("--symbol", "005930", "--timeframe", "1d", "--fix"),
                ],
            )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "permission_denied"
        # 데코레이터가 먼저 data:read 부족을 보고한다(enforce_scope 미도달).
        assert "data:read" in payload["message"]
        mock_store.assert_not_called()
