"""check_server_running 유틸 함수 및 --format json 테스트.

이슈 #920: --format json 옵션 지원 검증.
이슈 #1176: 비대화형 업데이트 계약(`click.confirm` 제거, `--yes` 게이트) 검증.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.update import check_server_running
from ante.cli.main import cli


class TestCheckServerRunning:
    """check_server_running 테스트."""

    @patch("ante.cli.commands.update.os.kill")
    @patch("ante.main.read_pid_file", return_value=12345)
    def test_pid_exists_and_process_running(
        self, mock_read_pid: object, mock_kill: object
    ) -> None:
        """PID 파일 존재 + 프로세스 실행 중 -> True."""
        assert check_server_running() is True

    @patch(
        "ante.cli.commands.update.os.kill",
        side_effect=ProcessLookupError,
    )
    @patch("ante.main.read_pid_file", return_value=12345)
    def test_pid_exists_but_stale(
        self, mock_read_pid: object, mock_kill: object
    ) -> None:
        """PID 파일 존재 + 프로세스 미존재 (stale) -> False."""
        assert check_server_running() is False

    @patch("ante.main.read_pid_file", return_value=None)
    def test_no_pid_file(self, mock_read_pid: object) -> None:
        """PID 파일 미존재 -> False."""
        assert check_server_running() is False


# ── --format json 테스트 ──────────────────────────────────────


@pytest.fixture()
def runner() -> CliRunner:
    """인증 우회 CliRunner.

    #1404: ``AuthenticatedGroup``이 leaf callback에 default-deny 인증 가드를
    부착하므로, ``ante.cli.main.authenticate_member`` 를 patch해 master 멤버
    stub을 ``ctx.obj["member"]`` 에 채워야 leaf까지 도달한다.
    """
    from ante.member.models import Member, MemberRole, MemberType

    _master = Member(
        member_id="update-test-master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Update Test Master",
        status="active",
        scopes=[],
    )

    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.ensure_object(dict)
                ctx.obj["member"] = _master

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


class TestUpdateFormatJson:
    """--format json 출력 테스트."""

    def test_check_format_json_valid(self, runner: CliRunner) -> None:
        """--format json 출력이 유효한 JSON이다 (TC#1)."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_check_format_json_fields(self, runner: CliRunner) -> None:
        """JSON 출력에 필수 필드 존재 (TC#2)."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "current_version" in data
        assert "latest_version" in data
        assert "update_available" in data

    def test_check_format_json_update_available_true(self, runner: CliRunner) -> None:
        """업데이트 가능 시 update_available=true."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        data = json.loads(result.output)
        assert data["current_version"] == "0.6.1"
        assert data["latest_version"] == "0.7.0"
        assert data["update_available"] is True

    def test_check_format_json_no_update(self, runner: CliRunner) -> None:
        """이미 최신 버전이면 update_available=false."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.7.0"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["update_available"] is False


class TestUpdateFormatText:
    """--format text (기본) 출력 테스트 (TC#3)."""

    def test_check_default_text(self, runner: CliRunner) -> None:
        """기본 출력은 사람이 읽을 수 있는 텍스트 형식이다."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code == 0
        assert "현재 버전: 0.6.1" in result.output
        assert "업데이트 가능" in result.output

    def test_check_explicit_text(self, runner: CliRunner) -> None:
        """--format text 명시 시에도 텍스트 출력."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "text"])

        assert result.exit_code == 0
        assert "현재 버전: 0.6.1" in result.output


class TestUpdateFormatJsonError:
    """JSON 모드 에러 출력 테스트.

    의도 변경(#1626 D2/D3): 이전 ``test_server_running_json_error``는
    서버 실행 중 ``ante update --check --format json``이 exit 1 JSON
    에러로 차단되는 buggy 순서를 정상으로 단언했다. SSOT(precedence
    normative 규칙)는 ``--check``을 dry-run으로 server-running 무관하게
    처리하도록 명시하므로, 본 케이스는 spec 정합 의미로 갱신한다 —
    ``--check``은 차단되지 않고, server-running JSON 에러는 실제 update
    경로(``--yes`` 게이트 통과 후)에서 ``UPDATE_SERVER_RUNNING`` 코드와
    함께 노출된다.
    """

    def test_check_json_not_blocked_by_server_running(self, runner: CliRunner) -> None:
        """서버 실행 중이어도 ``--check --format json`` dry-run은 성공한다.

        #1626 D3: ``--check``은 server-running과 무관(최우선 dry-run).
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["current_version"] == "0.6.1"
        assert data["latest_version"] == "0.7.0"
        assert data["update_available"] is True

    def test_server_running_json_error_has_update_server_running_code(
        self, runner: CliRunner
    ) -> None:
        """서버 실행 + ``--yes`` + ``--force`` 없음 → JSON ``UPDATE_SERVER_RUNNING``.

        #1626 D2: server-running JSON 에러는 ``code`` 가 null 이 아닌
        ``UPDATE_SERVER_RUNNING`` 이어야 한다 (이전 buggy 동작은 code=null).
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
        ):
            result = runner.invoke(
                cli, ["update", "--yes", "--format", "json"], input=None
            )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "message" in data
        assert data["code"] == "UPDATE_SERVER_RUNNING"
        assert data["code"] is not None

    def test_pypi_failure_json_error(self, runner: CliRunner) -> None:
        """PyPI 조회 실패 시 JSON 에러 출력."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value=None),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "message" in data


class TestUpdateNonInteractive:
    """비대화형 업데이트 계약 검증 (#1176).

    `click.confirm`을 제거하고 `--yes`/`--check`/`--force` 의미를 분리한
    이후의 동작을 검증한다.
    """

    def test_update_without_yes_fails_confirmation_required(
        self, runner: CliRunner
    ) -> None:
        """``--yes`` 누락 → exit 1, prompt 없음, ``CLI_CONFIRMATION_REQUIRED``.

        - stdin prompt가 발생하지 않아야 한다 (input=None).
        - ``pip_upgrade`` 등 부수 효과 함수가 호출되지 않아야 한다.
        - JSON 에러 코드는 ``CLI_CONFIRMATION_REQUIRED``.
        - ``get_latest_version`` (PyPI 조회) 호출 횟수가 0이어야 한다 — 게이트가
          PyPI 조회 앞에 평가되어야 한다 (Codex P2 2차 finding).
        """
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch(
                "ante.update.checker.get_latest_version", return_value="0.7.0"
            ) as mock_latest,
            patch(
                "ante.cli.commands.update.check_disk_space",
                return_value=(True, ""),
            ),
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
            patch("ante.db.backup.backup_db") as mock_backup,
            patch("ante.update.executor.snapshot_dependencies") as mock_snapshot,
            patch("ante.update.executor.run_post_update_migrations") as mock_migrate,
        ):
            # input=None → click.confirm이 남아 있으면 stdin EOF로 실패한다.
            result = runner.invoke(cli, ["--format", "json", "update"], input=None)

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["code"] == "CLI_CONFIRMATION_REQUIRED"
        assert "--yes" in data["message"]

        # 부수 효과가 발생하지 않아야 한다 (게이트가 막아야 한다).
        mock_pip_upgrade.assert_not_called()
        mock_backup.assert_not_called()
        mock_snapshot.assert_not_called()
        mock_migrate.assert_not_called()
        # PyPI 조회도 발생하지 않아야 한다 (게이트가 PyPI 앞에 평가).
        mock_latest.assert_not_called()

    def test_update_without_yes_fails_when_already_latest(
        self, runner: CliRunner
    ) -> None:
        """이미 최신 버전 + ``--yes`` 누락 → exit 1, ``CLI_CONFIRMATION_REQUIRED``.

        Codex P2 finding (1차): ``--yes`` 게이트는 no-update 조기 반환 **앞에**
        위치해야 한다. 사용자가 명시적 실행 의사(`--yes`)를 표현하지 않은
        ``ante update`` 호출은 버전 상태와 무관하게 거절되어야 한다.

        Codex P2 finding (2차): ``--yes`` 게이트는 PyPI 조회 **앞에** 평가되어야
        한다. 이미 최신 버전 케이스도 PyPI 호출 이전에 거절되므로 mock
        ``get_latest_version`` 호출 횟수는 0이다.

        - ``--yes`` 누락 → prompt 없이 exit 1.
        - JSON 에러 코드는 ``CLI_CONFIRMATION_REQUIRED``.
        - ``pip_upgrade`` 등 부수 효과 함수는 호출되지 않는다.
        - ``get_latest_version`` (PyPI) 호출 횟수 0.
        """
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.7.0"),
            patch(
                "ante.update.checker.get_latest_version", return_value="0.7.0"
            ) as mock_latest,
            patch(
                "ante.cli.commands.update.check_disk_space",
                return_value=(True, ""),
            ),
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
            patch("ante.db.backup.backup_db") as mock_backup,
            patch("ante.update.executor.snapshot_dependencies") as mock_snapshot,
            patch("ante.update.executor.run_post_update_migrations") as mock_migrate,
        ):
            result = runner.invoke(cli, ["--format", "json", "update"], input=None)

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["code"] == "CLI_CONFIRMATION_REQUIRED"
        assert "--yes" in data["message"]

        # 부수 효과가 발생하지 않아야 한다 (게이트가 막아야 한다).
        mock_pip_upgrade.assert_not_called()
        mock_backup.assert_not_called()
        mock_snapshot.assert_not_called()
        mock_migrate.assert_not_called()
        # PyPI 조회도 발생하지 않아야 한다 (게이트가 PyPI 앞에 평가).
        mock_latest.assert_not_called()

    def test_update_without_yes_skips_pypi_when_unreachable(
        self, runner: CliRunner
    ) -> None:
        """PyPI 도달 불가 + ``--yes`` 누락 → ``CLI_CONFIRMATION_REQUIRED`` 우선.

        Codex P2 finding (2차): ``--yes`` 게이트는 PyPI 조회 **앞에** 평가되어야
        한다. PyPI가 도달 불가(``get_latest_version`` 가 ``None`` 반환,
        타임아웃/네트워크 실패 시뮬레이션)인 환경에서도, ``--yes`` 누락 호출은
        PyPI 실패가 아닌 ``CLI_CONFIRMATION_REQUIRED``로 거절되어야 한다 —
        자동화는 네트워크 상태와 무관하게 동일한 구조화 에러 코드를 받는다.

        - ``get_latest_version`` 가 ``None`` (PyPI 실패) 반환하도록 mock.
        - ``--yes`` 누락 → exit 1, JSON 에러 코드는 ``CLI_CONFIRMATION_REQUIRED``
          (``"PyPI 버전 확인 실패"`` 가 아니다).
        - ``get_latest_version`` 호출 횟수 0 — 게이트가 PyPI 앞에 평가됨을 증명.
        - 부수 효과(pip upgrade/backup/migration) 호출 횟수 0.
        """
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            # PyPI 도달 불가 시뮬레이션 — 1차 fix에서는 이 mock이 호출되어
            # ``"PyPI 버전 확인 실패"`` 분기로 빠질 수 있었다. 2차 fix는 이
            # mock이 호출되지 않음을 보장한다.
            patch(
                "ante.update.checker.get_latest_version", return_value=None
            ) as mock_latest,
            patch(
                "ante.cli.commands.update.check_disk_space",
                return_value=(True, ""),
            ),
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
            patch("ante.db.backup.backup_db") as mock_backup,
            patch("ante.update.executor.snapshot_dependencies") as mock_snapshot,
            patch("ante.update.executor.run_post_update_migrations") as mock_migrate,
        ):
            result = runner.invoke(cli, ["--format", "json", "update"], input=None)

        assert result.exit_code == 1
        data = json.loads(result.output)
        # PyPI 실패 메시지가 아닌 confirmation 게이트로 fail 해야 한다.
        assert data["code"] == "CLI_CONFIRMATION_REQUIRED"
        assert "--yes" in data["message"]
        assert "PyPI" not in data["message"]

        # 핵심: PyPI 조회가 시도되지 않아야 한다 (게이트가 앞에 위치).
        mock_latest.assert_not_called()
        # 부수 효과도 일체 발생하지 않아야 한다.
        mock_pip_upgrade.assert_not_called()
        mock_backup.assert_not_called()
        mock_snapshot.assert_not_called()
        mock_migrate.assert_not_called()

    def test_update_with_yes_invokes_pip_upgrade(self, runner: CliRunner) -> None:
        """업데이트 가능 + ``--yes`` 있음 → 기존 업데이트 플로우 진입.

        - ``--yes`` 게이트를 통과해 ``pip_upgrade``가 호출되어야 한다.
        - 정상 종료 시 exit 0.
        """
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
            patch(
                "ante.cli.commands.update.check_disk_space",
                return_value=(True, ""),
            ),
            patch("ante.db.backup.backup_db"),
            patch("ante.update.executor.snapshot_dependencies", return_value=None),
            patch(
                "ante.update.executor.pip_upgrade", return_value=True
            ) as mock_pip_upgrade,
            patch(
                "ante.update.executor.run_post_update_migrations",
                return_value=True,
            ) as mock_migrate,
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = runner.invoke(cli, ["update", "--yes"])

        assert result.exit_code == 0
        mock_pip_upgrade.assert_called_once()
        mock_migrate.assert_called_once()

    def test_check_alone_succeeds_without_yes(self, runner: CliRunner) -> None:
        """``--check`` 단독 → exit 0, ``--yes`` 불필요.

        실제 업데이트를 수행하지 않으므로 ``pip_upgrade``는 호출되지 않는다.
        """
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
        ):
            result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code == 0
        mock_pip_upgrade.assert_not_called()


class TestUpdateGatePrecedence:
    """게이트 평가 우선순위 회귀 (#1626).

    SSOT: ``docs/specs/cli/02-design-decisions.md`` "위험 명령 확인 방식"
    precedence normative 규칙 —
    ``--check`` → ``--yes`` confirmation(``CLI_CONFIRMATION_REQUIRED``)
    → server-running/``--force``(``UPDATE_SERVER_RUNNING``) → 실제 update.

    이전 buggy 순서(server-running 가드가 ``--yes`` 게이트보다 선행, 그리고
    server-running ``fmt.error``에 ``code=`` 누락)를 정상으로 단언하던
    ``test_update.py``/``test_cli_update.py`` 케이스를 spec 정합으로 갱신한
    것과 별개로, oracle A7 contract-drift 재발 방지를 위한 직접 회귀를
    여기에 잠근다.
    """

    def test_server_running_without_yes_yields_confirmation_required(
        self, runner: CliRunner
    ) -> None:
        """서버 실행 + ``--yes`` 누락 → exit≠0, ``CLI_CONFIRMATION_REQUIRED``.

        oracle probe(``cli_update_confirmation_gate_contract``) 재현 케이스:
        서버 실행 중 ``ante --format json update``(no ``--yes``)는
        server-running(code=null)이 아닌 confirmation gate로 거절되어야 한다.
        server 상태 검사·PyPI 조회·side-effect 일체 미진입.
        """
        with (
            patch(
                "ante.cli.commands.update.check_server_running", return_value=True
            ) as mock_srv,
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch(
                "ante.update.checker.get_latest_version", return_value="2.0.0"
            ) as mock_latest,
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
            patch("ante.db.backup.backup_db") as mock_backup,
            patch("ante.update.executor.snapshot_dependencies") as mock_snapshot,
            patch("ante.update.executor.run_post_update_migrations") as mock_migrate,
        ):
            result = runner.invoke(cli, ["--format", "json", "update"], input=None)

        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["code"] == "CLI_CONFIRMATION_REQUIRED"
        assert "--yes" in data["message"]
        # confirmation gate가 server 상태 검사보다 우선 → server 검사 미진입.
        mock_srv.assert_not_called()
        mock_latest.assert_not_called()
        mock_pip_upgrade.assert_not_called()
        mock_backup.assert_not_called()
        mock_snapshot.assert_not_called()
        mock_migrate.assert_not_called()

    def test_server_running_with_yes_no_force_yields_update_server_running(
        self, runner: CliRunner
    ) -> None:
        """서버 실행 + ``--yes`` + ``--force`` 없음 → ``UPDATE_SERVER_RUNNING``.

        #1626 D2: 이전 buggy 동작은 ``code=null`` 이었다. 이 회귀는 code 가
        null 이 아닌 ``UPDATE_SERVER_RUNNING`` 임을 직접 단언한다. update
        side-effect(pip/backup/migration)는 진입하지 않아야 한다.
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch(
                "ante.update.checker.get_latest_version", return_value="2.0.0"
            ) as mock_latest,
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
            patch("ante.db.backup.backup_db") as mock_backup,
            patch("ante.update.executor.snapshot_dependencies") as mock_snapshot,
            patch("ante.update.executor.run_post_update_migrations") as mock_migrate,
        ):
            result = runner.invoke(
                cli, ["--format", "json", "update", "--yes"], input=None
            )

        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["code"] == "UPDATE_SERVER_RUNNING"
        assert data["code"] is not None
        assert "서버가 실행 중입니다" in data["message"]
        # server-running 가드는 update side-effect 이전에 평가됨.
        mock_latest.assert_not_called()
        mock_pip_upgrade.assert_not_called()
        mock_backup.assert_not_called()
        mock_snapshot.assert_not_called()
        mock_migrate.assert_not_called()

    def test_server_not_running_without_yes_yields_confirmation_required(
        self, runner: CliRunner
    ) -> None:
        """서버 미실행 + ``--yes`` 누락 → ``CLI_CONFIRMATION_REQUIRED``.

        server 상태와 무관하게 ``--yes`` 누락은 confirmation gate로 거절.
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=False),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch(
                "ante.update.checker.get_latest_version", return_value="2.0.0"
            ) as mock_latest,
        ):
            result = runner.invoke(cli, ["--format", "json", "update"], input=None)

        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["code"] == "CLI_CONFIRMATION_REQUIRED"
        assert "--yes" in data["message"]
        mock_latest.assert_not_called()

    def test_check_with_server_running_dry_run_succeeds(
        self, runner: CliRunner
    ) -> None:
        """충돌 정책 잠금: 서버 실행 + ``ante update --check`` → dry-run 성공.

        #1626 D3: ``--check``은 server-running과 무관(미차단).
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["update_available"] is True
        mock_pip_upgrade.assert_not_called()

    def test_check_yes_json_check_wins_no_side_effect(self, runner: CliRunner) -> None:
        """충돌 정책 잠금: ``ante update --check --yes --format json``.

        ``--check`` 우선(충돌 정책: ``--check`` 우선). dry-run JSON 성공이며
        ``check_server_running``/update side-effect 에 진입하지 않는다.
        """
        with (
            patch("ante.cli.commands.update.check_server_running") as mock_srv,
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
            patch("ante.db.backup.backup_db") as mock_backup,
            patch("ante.update.executor.run_post_update_migrations") as mock_migrate,
        ):
            result = runner.invoke(
                cli, ["update", "--check", "--yes", "--format", "json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["update_available"] is True
        # `--check` 우선 → server 검사/side-effect 미진입.
        mock_srv.assert_not_called()
        mock_pip_upgrade.assert_not_called()
        mock_backup.assert_not_called()
        mock_migrate.assert_not_called()

    def test_check_yes_server_running_check_wins(self, runner: CliRunner) -> None:
        """충돌 정책 잠금: 서버 실행 + ``--check --yes`` → ``--check`` 우선.

        server 실행 중이어도 ``--check``+``--yes`` 동시 사용 시 ``--check``
        우선 dry-run 성공, side-effect 미진입.
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
            patch("ante.update.executor.pip_upgrade") as mock_pip_upgrade,
        ):
            result = runner.invoke(cli, ["update", "--check", "--yes"])

        assert result.exit_code == 0
        assert "서버가 실행 중입니다" not in result.output
        assert "업데이트 가능: 1.0.0" in result.output
        mock_pip_upgrade.assert_not_called()

    def test_server_running_with_yes_and_force_bypasses_server_guard(
        self, runner: CliRunner
    ) -> None:
        """서버 실행 + ``--yes`` + ``--force`` → ``UPDATE_SERVER_RUNNING`` 우회.

        #1626 (Codex r1 [medium]): 본 케이스는 **``UPDATE_SERVER_RUNNING``
        가드가 우회됨**(server-running으로 거절되지 **않음**)만 검증한다.
        update 성공/실제 진행을 성공 의미로 단언하지 않는다 — graceful
        shutdown 미구현은 본 acceptance 범위 밖(Non-Goal). 검증 방법:
        server-running 거부 코드가 아니고, ``--yes`` 게이트도 통과하여
        실제 update 경로(여기서는 PyPI 조회)로 진입함을 확인한다.
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch(
                "ante.update.checker.get_latest_version", return_value="2.0.0"
            ) as mock_latest,
            patch("ante.cli.commands.update.check_disk_space", return_value=(True, "")),
            patch("ante.db.backup.backup_db"),
            patch("ante.update.executor.snapshot_dependencies", return_value=None),
            patch("ante.update.executor.pip_upgrade", return_value=True),
            patch("ante.update.executor.run_post_update_migrations", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "update", "--yes", "--force"], input=None
            )

        # server-running 거부가 아님 — 가드 우회 검증 (성공 의미 단언 아님).
        if result.output.strip():
            try:
                data = json.loads(result.output)
            except json.JSONDecodeError:
                data = {}
            assert data.get("code") != "UPDATE_SERVER_RUNNING"
            assert data.get("code") != "CLI_CONFIRMATION_REQUIRED"
        # `--yes`+`--force` 게이트 통과 → 실제 update 경로(PyPI 조회) 진입.
        mock_latest.assert_called_once()

    def test_output_shape_json_vs_text(self, runner: CliRunner) -> None:
        """JSON/text 양쪽 출력 shape 1케이스 (server-running 거부).

        JSON: ``{status, code, message}`` 구조. text: 사람이 읽는 메시지.
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
        ):
            json_result = runner.invoke(
                cli, ["--format", "json", "update", "--yes"], input=None
            )
            text_result = runner.invoke(cli, ["update", "--yes"], input=None)

        assert json_result.exit_code != 0
        jdata = json.loads(json_result.output)
        assert jdata["status"] == "error"
        assert jdata["code"] == "UPDATE_SERVER_RUNNING"
        assert "message" in jdata

        assert text_result.exit_code != 0
        assert "서버가 실행 중입니다" in text_result.output
