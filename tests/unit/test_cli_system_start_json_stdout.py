"""#1757 회귀: ``ante system start --format json`` stdout 격리 회귀 테스트.

ante-oracle A7 host probe ``cli_system_start_json_stdout_contract`` 는
부모 stdout 이 single JSON document 만 포함해야 한다고 계약한다. ``system start``
가 자식 ``python -m ante.main`` 의 stdout/stderr 를 inherit 시키면 runtime logger
출력이 JSON 응답에 이어 붙어 ``json.loads`` 파싱이 깨진다. (oracle cycle
``2026-05-24T003038Z_ae19043``, fingerprint ``6e987e08022b``)

본 모듈은 ``subprocess.run`` 을 mock 해 child 기동 비용을 회피하고 다음을 검증한다:

- R1 (JSON 모드): ``subprocess.run`` 호출 인자에 ``stdout=sys.stderr`` /
  ``stderr=sys.stderr`` 가 명시되어 자식 출력이 부모 stdout 으로 흘러들지 않는다.
  부모 stdout 은 ``fmt.success`` 가 출력한 단일 JSON document 만 포함하고
  ``json.loads`` 로 정상 파싱된다.
- R2 (text 모드 sanity): 기존 동작 보존 — ``subprocess.run`` 인자에 stdout/stderr
  override 가 없고 inherit 동작이 유지된다.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

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
def runner():
    """master 인증을 자동 주입하는 ``CliRunner``.

    ``mix_stderr=False`` 로 생성한다 — CliRunner 기본값(``True``) 은 ``sys.stderr``
    를 ``sys.stdout`` 과 동일 stream 으로 미러링해 본 회귀 테스트의 격리 검증
    의도(자식 stdout 이 부모 stderr 로 redirect 되는지) 가 불가능해진다.
    분리 stream 환경에서만 ``subprocess.run`` 의 ``stdout=sys.stderr`` 인자
    구별이 의미를 가진다.

    ``ante.cli.main.authenticate_member`` 를 mock 해 ``ctx.obj["member"]`` 에
    master 멤버를 채운다. ``test_cli_system.py`` 와 동일한 패턴.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


class TestSystemStartJsonStdoutIsolation:
    """#1757: JSON 모드에서 자식 stdout/stderr 가 부모 stdout 으로 새지 않는다."""

    def test_json_mode_redirects_child_stdout_and_stderr_to_parent_stderr(self, runner):
        """R1 — JSON 모드: ``subprocess.run`` 인자에 ``stdout=sys.stderr`` /
        ``stderr=sys.stderr`` 가 명시되어 자식 출력이 부모 stdout 을 오염시키지
        않는다.

        oracle A7 probe ``cli_system_start_json_stdout_contract`` 가 호출하는
        파서는 ``json.loads(stdout)`` 을 한 번에 수행하므로, stdout 에는 fmt.success
        가 출력한 single JSON document 만 남아야 한다.
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0

        # ``subprocess.run`` 호출 시점의 ``sys.stdout`` / ``sys.stderr`` 객체를
        # 캡처한다. CliRunner 가 invoke 동안 양쪽 stream 을 교체했다가 종료
        # 후 복원하므로, 테스트 본문에서 ``sys.stderr`` 를 비교하면 다른 객체를
        # 가리킨다. side_effect 안에서 캡처해야 invoke 시점 stream 과
        # ``mock.call_args.kwargs`` 의 stream 을 같은 frame 에서 비교할 수 있다.
        captured: dict[str, object] = {}

        def _capture_streams(*args: object, **kwargs: object) -> MagicMock:
            captured["stdout"] = sys.stdout
            captured["stderr"] = sys.stderr
            return mock_proc

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.system.subprocess.run",
                side_effect=_capture_streams,
            ) as mock_run,
        ):
            result = runner.invoke(cli, ["--format", "json", "system", "start"])

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()

        # subprocess.run 의 kwargs 에 stdout / stderr 가 부모 stderr 로 명시되어
        # 자식의 모든 stdout/stderr 출력이 부모 stderr 로 흐른다 (격리).
        kwargs = mock_run.call_args.kwargs
        invoke_stderr = captured["stderr"]
        invoke_stdout = captured["stdout"]
        assert kwargs.get("stdout") is invoke_stderr, (
            "JSON 모드는 자식 stdout 을 부모 stderr 로 redirect 해야 한다 (#1757)."
            f" 실제 stdout 인자={kwargs.get('stdout')!r},"
            f" invoke 시점 sys.stderr={invoke_stderr!r}"
        )
        assert kwargs.get("stderr") is invoke_stderr, (
            "JSON 모드는 자식 stderr 를 부모 stderr 로 redirect 해야 한다 (#1757)."
            f" 실제 stderr 인자={kwargs.get('stderr')!r},"
            f" invoke 시점 sys.stderr={invoke_stderr!r}"
        )
        # mix_stderr=False 환경에서 stdout 과 stderr 는 서로 다른 stream 이어야
        # 격리 단언이 의미를 가진다 — runner fixture 가 mix_stderr=False 로
        # 설정되었는지 회귀 보호.
        assert invoke_stdout is not invoke_stderr, (
            "runner fixture 는 mix_stderr=False 여야 stdout/stderr 격리 검증이"
            " 가능하다."
        )

        # 부모 stdout 은 fmt.success 가 출력한 단일 JSON document 하나만
        # 포함하므로 json.loads 가 정상 파싱한다. 자식 subprocess 가 mock 되어
        # 실제 자식 로그가 발생하지 않으므로 result.stdout 은 fmt.success JSON
        # 만 포함한다 (mix_stderr=False).
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["message"] == "시스템 시작 중..."

    def test_text_mode_preserves_inherited_child_streams(self, runner):
        """R2 (sanity) — text 모드: ``subprocess.run`` 호출에 stdout/stderr
        override 가 없다 (기존 inherit 동작 보존).

        Non-Goals 에 따라 text 모드 출력 형식은 무변경이며, 자식 logger 출력은
        기존대로 부모 stdout 에 노출된다.
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.system.subprocess.run", return_value=mock_proc
            ) as mock_run,
        ):
            result = runner.invoke(cli, ["system", "start"])

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()

        kwargs = mock_run.call_args.kwargs
        # text 모드는 stdout/stderr 인자를 넘기지 않고 inherit 한다.
        assert "stdout" not in kwargs, (
            "text 모드는 자식 stdout 을 inherit 해야 한다 (#1757 non-goal)."
            f" 실제 kwargs={kwargs!r}"
        )
        assert "stderr" not in kwargs, (
            "text 모드는 자식 stderr 를 inherit 해야 한다 (#1757 non-goal)."
            f" 실제 kwargs={kwargs!r}"
        )
