"""ante init CLI 테스트 — 비대화형 재설계 (issue #1125)."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli

_MOCK_MASTER_INFO = {
    "member_id": "owner",
    "name": "Owner",
    "role": "master",
    "emoji": "🦊",
}
_MOCK_TOKEN = "ante_hk_test_token_123"
_MOCK_RECOVERY_KEY = "ANTE-RK-XXXX-YYYY-ZZZZ-AAAA-BBBB-CCCC"

_MOCK_TEST_ACCOUNT = {
    "account_id": "test",
    "broker_type": "test",
    "exchange": "TEST",
}


def _mock_bootstrap(*args, **kwargs):
    """_bootstrap_master mock — 3-tuple (dict, token, recovery_key) 반환."""
    return _MOCK_MASTER_INFO, _MOCK_TOKEN, _MOCK_RECOVERY_KEY


def _mock_create_test_account(*args, **kwargs):
    """_create_test_account mock — test account dict 반환."""
    return _MOCK_TEST_ACCOUNT


def _patch_init():
    """표준 패치 3종: _bootstrap_master + _create_test_account + authenticate_member."""
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_test_account",
            new=AsyncMock(side_effect=_mock_create_test_account),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


@pytest.fixture
def runner():
    return CliRunner()


class TestInitFreshEnvironment:
    """시나리오 1: 신규 환경 초기화."""

    def test_init_creates_all_artifacts(self, runner, tmp_path):
        """ante init (플래그 없음) → 3개 파일 생성, 토큰·recovery key·패스워드 출력."""
        target = tmp_path / "config"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        # 3개 파일 존재
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()
        # DB는 _bootstrap mock에 의존 — 파일 존재는 보장되지 않음
        # 출력에 토큰·recovery·패스워드 섹션 포함
        assert _MOCK_TOKEN in result.output
        assert _MOCK_RECOVERY_KEY in result.output
        assert "패스워드" in result.output
        # master member_id와 name이 text 출력에 표시된다 (Codex finding 3)
        assert _MOCK_MASTER_INFO["member_id"] in result.output
        assert _MOCK_MASTER_INFO["name"] in result.output
        # 테스트 계좌 표시
        assert "test" in result.output


class TestInitFlagsSetIdentity:
    """시나리오 2: 플래그로 정체성 지정."""

    def test_custom_member_id_and_name(self, runner, tmp_path):
        """--member-id alice --name Alice 시 해당 값이 _bootstrap_master에 전달된다."""
        target = tmp_path / "config"

        custom_info = {
            "member_id": "alice",
            "name": "Alice",
            "role": "master",
            "emoji": "🦊",
        }

        def _mock_bootstrap_alice(*args, **kwargs):
            return custom_info, _MOCK_TOKEN, _MOCK_RECOVERY_KEY

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap_alice)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(
                cli,
                [
                    "init",
                    "--dir",
                    str(target),
                    "--member-id",
                    "alice",
                    "--name",
                    "Alice",
                ],
            )

        assert result.exit_code == 0, result.output
        # bootstrap_mock 호출 시 member_id='alice', name='Alice' 전달 확인
        call_args = bootstrap_mock.call_args
        # 포지셔널: (db_path, member_id, name, password)
        args = call_args.args
        assert args[1] == "alice"
        assert args[2] == "Alice"
        # install.feature Scenario 6: stdout에 member_id와 name이 모두 노출
        assert "alice" in result.output
        assert "Alice" in result.output


class TestInitIdempotency:
    """시나리오 3 & 4: 멱등성 — 전체 존재 시 거부, 부분 누락 시 보완."""

    def test_init_refuses_when_all_artifacts_exist(self, runner, tmp_path):
        """system.toml + secrets.env + db/ante.db 모두 존재 시 거부."""
        target = tmp_path / "config"
        target.mkdir()
        (target / "system.toml").write_text("existing")
        (target / "secrets.env").write_text("existing")
        db_dir = target / "db"
        db_dir.mkdir()
        (db_dir / "ante.db").write_text("")

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code != 0
        assert "init이 이미 완료된 상태입니다" in result.output

    def test_init_skips_db_when_only_config_files_exist(self, runner, tmp_path):
        """멱등성 경계 — secrets.env만 존재할 때 나머지 산출물이 채워진다.

        arch-review 권고: system.toml과 db/ante.db 둘 다 누락이면
        `_all_artifacts_exist` 는 False 이므로 init은 진행해야 한다.
        단 db/ante.db가 실제로 없을 때만 master bootstrap이 실행되어야 한다.

        이 테스트는 보완 케이스: secrets.env만 존재 → 나머지 생성.
        """
        target = tmp_path / "config"
        target.mkdir()
        (target / "secrets.env").write_text("existing")

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert (target / "system.toml").exists()
        # secrets.env 기존 내용 보존
        assert (target / "secrets.env").read_text() == "existing"

    def test_init_preserves_existing_config_files(self, runner, tmp_path):
        """시나리오 4: system.toml + secrets.env 있고 db 누락 → DB만 재생성."""
        target = tmp_path / "config"
        target.mkdir()
        (target / "system.toml").write_text("# custom config\n")
        (target / "secrets.env").write_text("CUSTOM=1\n")

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        # 기존 설정 파일 보존
        assert (target / "system.toml").read_text() == "# custom config\n"
        assert (target / "secrets.env").read_text() == "CUSTOM=1\n"
        # DB 재발급에 따른 토큰·recovery key 출력
        assert _MOCK_TOKEN in result.output
        assert _MOCK_RECOVERY_KEY in result.output


class TestInitSeedFlagRemoved:
    """시나리오 5: --seed 플래그가 제거되었음을 검증."""

    def test_seed_flag_is_unknown_option(self, runner, tmp_path):
        """--seed 옵션은 Click이 'no such option'으로 거부해야 한다."""
        target = tmp_path / "config"

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(cli, ["init", "--dir", str(target), "--seed"])

        # Click unknown option → exit code 2
        assert result.exit_code != 0
        # 에러 메시지에 --seed 관련 문구 포함 (Click 기본 메시지)
        combined = result.output + (result.stderr if result.stderr_bytes else "")
        assert "no such option" in combined.lower() or "--seed" in combined


class TestInitJsonOutput:
    """시나리오 7: --format json 출력."""

    def test_json_output_contains_all_secrets(self, runner, tmp_path):
        """--format json 시 password/token/recovery_key/config_dir/test_account 포함."""
        target = tmp_path / "config"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli,
                ["--format", "json", "init", "--dir", str(target)],
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output

        # JSON 파싱
        lines = result.output.strip().splitlines()
        json_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                json_start = i
                break
        assert json_start is not None, f"JSON 출력 없음: {result.output}"
        data = json.loads("\n".join(lines[json_start:]))

        assert data["member_id"] == "owner"
        assert data["name"] == "Owner"
        assert data["token"] == _MOCK_TOKEN
        assert data["recovery_key"] == _MOCK_RECOVERY_KEY
        assert "password" in data
        assert len(data["password"]) >= 20
        assert "config_dir" in data
        assert "test_account" in data
        assert data["test_account"]["account_id"] == "test"


class TestInitSecretsEnvPermission:
    """secrets.env 파일 권한 0600."""

    def test_secrets_env_is_0600(self, runner, tmp_path):
        """secrets.env 생성 후 권한이 0600 (u+rw, others 없음)이어야 한다."""
        target = tmp_path / "config"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        secrets_env = target / "secrets.env"
        assert secrets_env.exists()
        mode = secrets_env.stat().st_mode
        # 0600 === rw-------
        perms = stat.S_IMODE(mode)
        assert perms == 0o600, f"secrets.env 권한이 0600이 아님: {oct(perms)}"


class TestInitCreatesTestAccount:
    """default test account 자동 생성 검증."""

    def test_create_test_account_is_called(self, runner, tmp_path):
        """DB가 새로 생성될 때 _create_test_account가 호출된다."""
        target = tmp_path / "config"

        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch(
                "ante.cli.commands.init._bootstrap_master",
                new=AsyncMock(side_effect=_mock_bootstrap),
            ),
            patch(
                "ante.cli.commands.init._create_test_account",
                new=create_acc_mock,
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        create_acc_mock.assert_called_once()


class TestInitDefaultDir:
    """--dir 미지정 시 ~/.config/ante/ 사용."""

    def test_default_dir(self, runner, tmp_path):
        from pathlib import Path

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            with patch.object(Path, "home", return_value=tmp_path):
                result = runner.invoke(cli, ["init"])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".config" / "ante" / "system.toml").exists()


class TestInitDefaultFlagValues:
    """플래그 기본값 owner/Owner이 bootstrap으로 전달된다."""

    def test_defaults_are_owner_and_owner(self, runner, tmp_path):
        target = tmp_path / "config"
        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        args = bootstrap_mock.call_args.args
        assert args[1] == "owner"
        assert args[2] == "Owner"
        # 패스워드는 랜덤 생성 (길이 최소 20자 이상)
        assert len(args[3]) >= 20


class TestInitAuthExempt:
    """ante init은 인증 면제 커맨드여야 한다 — issue #1125 Codex finding B.

    middleware._AUTH_EXEMPT_COMMANDS에 'init'이 포함되어 있으므로
    stale/invalid한 ANTE_MEMBER_TOKEN이 있어도 init은 막히면 안 된다.
    """

    def test_init_runs_when_stale_ante_member_token_set(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stale한 ANTE_MEMBER_TOKEN이 설정돼도 init은 면제로 실행돼야 한다."""
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid_token")
        # 토큰 파일 fallback도 끄기 위해 존재하지 않는 경로로 우회
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))

        target = tmp_path / "cfg"

        # authenticate_member는 patch하지 않는다 — 실제 middleware가 init을 면제해야 함
        with (
            patch(
                "ante.cli.commands.init._bootstrap_master",
                new=AsyncMock(side_effect=_mock_bootstrap),
            ),
            patch(
                "ante.cli.commands.init._create_test_account",
                new=AsyncMock(side_effect=_mock_create_test_account),
            ),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        assert "인증 실패" not in result.output
        assert "init이 이미 완료된 상태입니다" not in result.output


class TestInitReentryWithOrphanDb:
    """DB 파일만 존재하고 config 파일은 없을 때의 재진입 경로.

    issue #1125 Codex finding A의 회귀 테스트:
    서버가 먼저 기동되어 DB 파일을 생성해 둔 뒤 ante init이 호출되면
    db_existed_before=True로 master bootstrap이 skip되어야 한다.
    """

    def test_init_skips_master_when_db_exists_but_config_missing(
        self, runner, tmp_path: Path
    ) -> None:
        """DB만 있고 config 없으면 파일만 재생성하고 bootstrap은 skip."""
        cfg = tmp_path / "cfg"
        (cfg / "db").mkdir(parents=True)
        (cfg / "db" / "ante.db").write_bytes(b"")  # 빈 DB 파일 흉내

        bootstrap_mock = Mock()
        create_account_mock = Mock()

        with (
            patch(
                "ante.cli.commands.init._bootstrap_master",
                new=bootstrap_mock,
            ),
            patch(
                "ante.cli.commands.init._create_test_account",
                new=create_account_mock,
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["--format", "json", "init", "--dir", str(cfg)])

        assert result.exit_code == 0, result.output
        bootstrap_mock.assert_not_called()
        create_account_mock.assert_not_called()
        # system.toml / secrets.env는 재생성
        assert (cfg / "system.toml").exists()
        assert (cfg / "secrets.env").exists()
        # JSON 출력에는 token/recovery_key 없음 (master bootstrap이 skip됐으므로)
        lines = result.output.strip().splitlines()
        json_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                json_start = i
                break
        assert json_start is not None, f"JSON 출력 없음: {result.output}"
        data = json.loads("\n".join(lines[json_start:]))
        assert "token" not in data or data.get("token") in (None, "")
        assert "recovery_key" not in data or data.get("recovery_key") in (None, "")
        assert "test_account" not in data


class TestInitJsonErrorContract:
    """`ante --format json init` 실패 경로가 JSON 계약을 유지해야 한다.

    `click.ClickException`은 JSON 모드에서도 stderr에 "Error: ..." 텍스트를 내
    Agent의 JSON 파서를 깨뜨린다. init은 세 가지 실패 경로(이미 초기화 / bootstrap
    ValueError / test account Exception) 모두 stdout에 구조화된 JSON을 내고
    exit code 1로 종료해야 한다.

    스펙: docs/specs/cli/02-design-decisions.md (--format json은 모든 커맨드
    출력을 파싱 가능해야 함). 관련 이슈: #1125 (Codex branch review, 3차 FAIL).
    """

    @staticmethod
    def _parse_error_json(output: str) -> dict:
        """stdout의 마지막 JSON 오브젝트를 파싱해 반환."""
        stripped = output.strip()
        assert stripped, "stdout이 비어 있음 (JSON 실패 계약 위반)"
        # fmt.error는 indent 없이 한 줄 JSON을 낸다
        for line in reversed(stripped.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise AssertionError(f"JSON 오브젝트를 찾을 수 없음: {output!r}")

    def test_init_already_initialized_json_output(self, runner, tmp_path):
        """이미 초기화된 상태에서 --format json으로 재실행하면 JSON 에러 + exit 1."""
        target = tmp_path / "config"
        target.mkdir()
        (target / "system.toml").write_text("x")
        (target / "secrets.env").write_text("x")
        db_dir = target / "db"
        db_dir.mkdir()
        (db_dir / "ante.db").write_text("")

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(
                cli, ["--format", "json", "init", "--dir", str(target)]
            )

        assert result.exit_code == 1, (
            f"exit=1 기대 (got {result.exit_code}): {result.output}"
        )
        data = self._parse_error_json(result.output)
        assert "error" in data
        assert "init이 이미 완료된 상태입니다" in data["error"]
        assert data.get("code") == "already_initialized"

    def test_init_bootstrap_failure_json_output(self, runner, tmp_path):
        """_bootstrap_master가 ValueError를 던지면 JSON 에러 + exit 1."""
        target = tmp_path / "config"

        bootstrap_mock = AsyncMock(side_effect=ValueError("패스워드 정책 위반"))

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch(
                "ante.cli.commands.init._create_test_account",
                new=AsyncMock(side_effect=_mock_create_test_account),
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "init", "--dir", str(target)]
            )

        assert result.exit_code == 1, (
            f"exit=1 기대 (got {result.exit_code}): {result.output}"
        )
        data = self._parse_error_json(result.output)
        assert "error" in data
        assert "패스워드 정책 위반" in data["error"]
        assert data.get("code") == "bootstrap_failed"

    def test_init_test_account_failure_json_output(self, runner, tmp_path):
        """_create_test_account가 Exception을 던지면 JSON 에러 + exit 1."""
        target = tmp_path / "config"

        create_acc_mock = AsyncMock(side_effect=RuntimeError("DB lock"))

        with (
            patch(
                "ante.cli.commands.init._bootstrap_master",
                new=AsyncMock(side_effect=_mock_bootstrap),
            ),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "init", "--dir", str(target)]
            )

        assert result.exit_code == 1, (
            f"exit=1 기대 (got {result.exit_code}): {result.output}"
        )
        data = self._parse_error_json(result.output)
        assert "error" in data
        assert "테스트 계좌 생성 실패" in data["error"]
        assert "DB lock" in data["error"]
        assert data.get("code") == "test_account_failed"

    def test_init_already_initialized_text_mode_preserves_message(
        self, runner, tmp_path
    ):
        """text 모드에서도 멱등성 거부 메시지가 유지되어야 한다 (기존 테스트 호환)."""
        target = tmp_path / "config"
        target.mkdir()
        (target / "system.toml").write_text("x")
        (target / "secrets.env").write_text("x")
        db_dir = target / "db"
        db_dir.mkdir()
        (db_dir / "ante.db").write_text("")

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 1
        # text 모드에서는 OutputFormatter.error가 "Error: ..." 를 stderr로 보낸다
        # CliRunner 기본 mix_stderr=True이면 result.output에 섞여 보인다
        assert "init이 이미 완료된 상태입니다" in result.output
