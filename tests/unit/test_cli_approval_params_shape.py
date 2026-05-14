"""CLI ``approval request``/``reopen --params`` non-dict guard 회귀 테스트 (#1519).

대상 invariant:
- ``--params`` 는 service ``params.get()`` 의 SSOT 입력이므로 JSON object
  (dict) 만 허용한다. string/list/number/bool/null 같은 non-dict JSON value
  가 dict guard 없이 통과하면 service 단에서 ``AttributeError`` traceback
  이 stderr 로 노출되는 ingress drift 가 발생한다.
- ``approval request`` 와 ``approval reopen`` 두 사이트 모두에 inline guard
  를 적용하여 IPC 진입 전에 ``APPROVAL_VALIDATION_ERROR`` 로 거부한다.
- ``reopen`` 의 ``--params`` 옵션 미지정 (``params_json is None``) 케이스는
  guard 분기 자체에 진입하지 않으므로 ``params=None`` sentinel 이 보존되고
  IPC payload 에 ``params`` 키가 빠진다 (기존 값 유지 invariant).
- ``reopen --params null`` 명시 입력은 ``json.loads("null") == None`` 이므로
  guard 에서 거부된다 (의도된 정정).

oracle probe: ``cli_approval_params_dict_guard``.

Non-Goals (본 PR 미포함):
- ``ApprovalService.create()``/``reopen()`` defense-in-depth (service 단
  isinstance 검증) 은 follow-up 으로 분리.
- IPC handler payload validation 은 follow-up 으로 분리.

SSOT:
- 구현 사이트: ``src/ante/cli/commands/approval.py::request`` (``params``
  파싱 직후), ``::reopen`` (``params_json is not None`` 분기 내 ``json.loads``
  직후).
- 동형 패턴: 같은 파일 line 57-58 (INVALID_JSON), line 62-66
  (APPROVAL_VALIDATION_ERROR for approval_type).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

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


@pytest.fixture
def runner() -> CliRunner:
    """auth bypass + stderr 분리가 적용된 CliRunner.

    ``ante.cli.main.authenticate_member`` 를 patch 하여 root group 의 인증
    검사를 우회한다 (CLI 테스트 표준 패턴). ``mix_stderr=False`` 로 stderr 와
    stdout 을 분리해 traceback 누출 여부를 양쪽 모두에서 검증한다.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _patch_ipc_success(send_return: dict | None = None):
    """``ipc_send`` 직접 patch — valid 케이스 mock.

    ``approval request``/``reopen`` 은 ``ante.cli.commands.ipc_helpers.ipc_send``
    를 함수 내부 import 하므로 그 심볼을 직접 patch 한다.
    """
    payload = send_return or {"id": "req-1", "status": "pending"}
    return patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=payload),
    )


# 본 PR 가드가 거부해야 하는 non-dict JSON value 매트릭스.
# ``"null"`` 은 ``json.loads`` 후 ``None`` 으로, dict 가 아니므로 거부 대상이다.
_INVALID_PARAMS_MATRIX = [
    pytest.param('"oracle-string"', id="string"),
    pytest.param("123", id="number"),
    pytest.param("[1,2,3]", id="list"),
    pytest.param("true", id="bool"),
    pytest.param("null", id="null"),
]


class TestApprovalRequestInvalidParams:
    """``approval request --params`` non-dict JSON → 거부."""

    @pytest.mark.parametrize("bad_params", _INVALID_PARAMS_MATRIX)
    def test_non_dict_params_rejected_without_traceback(
        self, runner: CliRunner, bad_params: str
    ) -> None:
        """non-dict JSON value 입력은 exit 1 + structured error + no traceback.

        IPC 는 호출되지 않아야 한다 (validation 이 ingress 에서 차단).
        AttributeError 가 stderr 로 노출되면 회귀.
        """
        with _patch_ipc_success() as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                    "--params",
                    bad_params,
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        # traceback / AttributeError 노출 차단 invariant — stdout, stderr 양쪽.
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr
        assert "AttributeError" not in result.stdout
        assert "AttributeError" not in result.stderr
        # 구조화 에러 키워드 invariant: code 또는 한국어 메시지.
        combined = result.stdout + result.stderr
        assert (
            "APPROVAL_VALIDATION_ERROR" in combined
            or "--params는 JSON object" in combined
        )
        mock_ipc.assert_not_called()

    def test_invalid_json_syntax_still_rejected_as_invalid_json(
        self, runner: CliRunner
    ) -> None:
        """JSON syntax 오류는 기존 ``INVALID_JSON`` 분기로 처리 (회귀 보호).

        본 PR 의 dict guard 추가가 기존 syntax 에러 처리를 우회시키지 않음을
        확인한다.
        """
        with _patch_ipc_success() as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                    "--params",
                    "{not-json",
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        combined = result.stdout + result.stderr
        assert "INVALID_JSON" in combined or "잘못된 JSON 형식" in combined
        mock_ipc.assert_not_called()

    def test_invalid_params_json_envelope(self, runner: CliRunner) -> None:
        """``--format json`` 모드에서 non-dict params 는 stdout JSON envelope
        으로 출력되고 traceback 은 노출되지 않는다.
        """
        with _patch_ipc_success() as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                    "--params",
                    '"oracle-string"',
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr
        last_line = result.stdout.strip().splitlines()[-1]
        payload = json.loads(last_line)
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_VALIDATION_ERROR"
        assert "--params는 JSON object" in payload["message"]
        mock_ipc.assert_not_called()


class TestApprovalRequestValidParams:
    """valid params 회귀 — 정상 dict 입력은 IPC 까지 도달."""

    @pytest.mark.parametrize(
        "good_params",
        [
            pytest.param('{"foo": "bar"}', id="non-empty-object"),
            pytest.param("{}", id="empty-object"),
        ],
    )
    def test_valid_dict_params_passes_to_ipc(
        self, runner: CliRunner, good_params: str
    ) -> None:
        """valid JSON object 입력은 guard 를 통과해 IPC 가 호출된다.

        본 invariant 는 guard 가 정상 dict 경로를 깨뜨리지 않음을 회귀 보호.
        """
        with _patch_ipc_success({"id": "req-good", "status": "pending"}) as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                    "--params",
                    good_params,
                ],
            )

        assert result.exit_code == 0, (result.stdout, result.stderr)
        mock_ipc.assert_called_once()
        # IPC payload 의 params 는 dict 여야 한다.
        call_args = mock_ipc.call_args
        ipc_payload = call_args[0][1]
        assert isinstance(ipc_payload["params"], dict)


class TestApprovalReopenInvalidParams:
    """``approval reopen --params`` non-dict JSON → 거부."""

    @pytest.mark.parametrize("bad_params", _INVALID_PARAMS_MATRIX)
    def test_non_dict_params_rejected_without_traceback(
        self, runner: CliRunner, bad_params: str
    ) -> None:
        """reopen 사이트도 request 와 동형으로 non-dict 를 거부한다.

        ``null`` 명시 입력 (``--params null``) 케이스도 가드에서 거부된다
        (의도된 정정; ``params_json is None`` 즉 옵션 미지정 케이스와 구별).
        """
        with _patch_ipc_success() as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "reopen",
                    "some-id",
                    "--params",
                    bad_params,
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr
        assert "AttributeError" not in result.stdout
        assert "AttributeError" not in result.stderr
        combined = result.stdout + result.stderr
        assert (
            "APPROVAL_VALIDATION_ERROR" in combined
            or "--params는 JSON object" in combined
        )
        mock_ipc.assert_not_called()


class TestApprovalReopenValidParams:
    """``approval reopen`` valid 경로 + 옵션 미지정 sentinel 회귀."""

    def test_valid_dict_params_passes_to_ipc(self, runner: CliRunner) -> None:
        """valid dict 입력은 guard 를 통과해 IPC payload 에 ``params`` 가
        포함된다.
        """
        with _patch_ipc_success({"id": "req-rop", "status": "pending"}) as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "reopen",
                    "some-id",
                    "--params",
                    '{"updated": "value"}',
                ],
            )

        assert result.exit_code == 0, (result.stdout, result.stderr)
        mock_ipc.assert_called_once()
        call_args = mock_ipc.call_args
        ipc_payload = call_args[0][1]
        assert isinstance(ipc_payload.get("params"), dict)
        assert ipc_payload["params"] == {"updated": "value"}

    def test_params_option_omitted_preserves_sentinel(self, runner: CliRunner) -> None:
        """``--params`` 옵션 미지정 시 ``params_json is None`` → guard 분기에
        진입하지 않으므로 ``params=None`` sentinel 이 보존되어 IPC payload 에
        ``params`` 키가 포함되지 않는다 (기존 값 유지 invariant).
        """
        with _patch_ipc_success({"id": "req-rop", "status": "pending"}) as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "reopen",
                    "some-id",
                ],
            )

        assert result.exit_code == 0, (result.stdout, result.stderr)
        mock_ipc.assert_called_once()
        call_args = mock_ipc.call_args
        ipc_payload = call_args[0][1]
        # params 옵션 미지정 → IPC payload 에 params 키 없음 (기존 값 유지).
        assert "params" not in ipc_payload
