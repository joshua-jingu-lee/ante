"""ante init CLI 테스트 — 비대화형 재설계 (issue #1125).

5-state 가드: 파일(3) + master row + test account row 조합 전수 검증.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import stat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import click
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


def _split_stderr_runner() -> CliRunner:
    """Click 8.1/8.3 양쪽에서 stderr 분리 캡처를 요청한다."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


def _patch_init(*, master_exists: bool = False, test_account_exists: bool = False):
    """표준 패치 세트.

    기본값은 빈 DB로 간주 (master/test account 둘 다 없음)하여
    state 5 경로와 호환된다. DB 레코드 존재를 제어하려면 명시적으로 전달.

    `_test_account_state`는 3-state ("active"/"inactive"/"missing")를 반환하므로,
    `test_account_exists=True`는 "active"로, False는 "missing"으로 매핑한다.
    "inactive" 시나리오는 개별 테스트에서 직접 mock 한다.
    """
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_test_account",
            new=AsyncMock(side_effect=_mock_create_test_account),
        ),
        patch(
            "ante.cli.commands.init._master_exists_in_db",
            new=AsyncMock(return_value=master_exists),
        ),
        patch(
            "ante.cli.commands.init._test_account_state",
            new=AsyncMock(return_value="active" if test_account_exists else "missing"),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


def _create_db_with_master_row(db_path: Path) -> None:
    """테스트 헬퍼: DB 파일에 members 테이블과 master row를 만든다."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS members (
                member_id TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'default'
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO members (member_id, role) VALUES (?, ?)",
            ("owner", "master"),
        )
        conn.commit()
    finally:
        conn.close()


def _create_db_with_test_account_row(
    db_path: Path,
    *,
    account_id: str = "test",
    broker_type: str = "test",
    status: str = "active",
) -> None:
    """테스트 헬퍼: DB 파일에 accounts 테이블과 test account row를 만든다.

    `_test_account_state`는 실제 AccountService 스키마(account_id + status)를
    기준으로 판정하므로 `status` 컬럼을 포함해야 한다. 기본값은 default test
    account(account_id='test', status='active')과 동일하다.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                broker_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(account_id, broker_type, status) VALUES (?, ?, ?)",
            (account_id, broker_type, status),
        )
        conn.commit()
    finally:
        conn.close()


def _create_full_db(db_path: Path) -> None:
    """테스트 헬퍼: master row + test account row를 모두 채운 DB 생성."""
    _create_db_with_master_row(db_path)
    _create_db_with_test_account_row(db_path)


@pytest.fixture
def runner():
    return CliRunner()


class TestInitFreshEnvironment:
    """시나리오 1: 신규 환경 초기화 (state 5)."""

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
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
            ),
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


class TestInitFiveStateGuard:
    """스펙 I4 — 파일 + master 레코드 기반 멱등성. 5-state 가드 전수 검증."""

    def test_state1_all_exist_rejects(self, runner, tmp_path):
        """state 1: 모든 상태 완료 → 거부 (exit 1, 'init이 이미 완료된 상태입니다')."""
        target = tmp_path / "config"
        target.mkdir()
        (target / "system.toml").write_text("x")
        (target / "secrets.env").write_text("x")
        db_path = target / "db" / "ante.db"
        _create_full_db(db_path)

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 1, result.output
        assert "init이 이미 완료된 상태입니다" in result.output
        bootstrap_mock.assert_not_called()
        create_acc_mock.assert_not_called()

    def test_state2_files_missing_db_complete_regenerates_files_only(
        self, runner, tmp_path
    ):
        """state 2: 파일만 누락, DB 완전 → 파일만 재생성.

        bootstrap/account는 호출되지 않아야 한다.
        """
        target = tmp_path / "config"
        target.mkdir()
        # 파일은 없음
        db_path = target / "db" / "ante.db"
        _create_full_db(db_path)

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        # 파일 재생성됨
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()
        # master/test account는 손대지 않음
        bootstrap_mock.assert_not_called()
        create_acc_mock.assert_not_called()

    def test_state3_master_exists_but_test_account_missing(self, runner, tmp_path):
        """state 3: master 있으나 test account 없음 → test account만 생성."""
        target = tmp_path / "config"
        target.mkdir()
        db_path = target / "db" / "ante.db"
        # master row만 있는 DB
        _create_db_with_master_row(db_path)

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        # master bootstrap은 호출 안 됨
        bootstrap_mock.assert_not_called()
        # test account만 생성
        create_acc_mock.assert_called_once()
        # text 모드에서 master는 이미 존재 알림
        assert "Master" in result.output or "master" in result.output.lower()

    def test_state4_orphan_db_no_master(self, runner, tmp_path):
        """state 4: DB 파일 있지만 master 없음 → master bootstrap + test account."""
        target = tmp_path / "config"
        target.mkdir()
        # 빈 DB 파일 (orphan)
        db_path = target / "db" / "ante.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"")

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        # orphan 수복: 둘 다 호출
        bootstrap_mock.assert_called_once()
        create_acc_mock.assert_called_once()
        # 비밀값 출력 확인
        assert _MOCK_TOKEN in result.output
        assert _MOCK_RECOVERY_KEY in result.output

    def test_state5_fresh_install(self, runner, tmp_path):
        """state 5: DB 파일 없음 → 전체 신규 생성 (기존 동작)."""
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
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()
        assert _MOCK_TOKEN in result.output
        assert _MOCK_RECOVERY_KEY in result.output

    def test_master_credentials_emitted_before_test_account_attempt(
        self, runner, tmp_path
    ):
        """옵션 P: master 비밀값은 test account 단계 전에 출력돼야 한다.

        _create_test_account가 Exception을 던져도 stdout/stderr에 token/
        recovery_key/password가 남아야 한다.
        """
        target = tmp_path / "config"

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=RuntimeError("DB lock 실패"))

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 1, result.output
        # test account 실패했지만 master 비밀값은 이미 노출
        combined = result.output
        assert _MOCK_TOKEN in combined
        assert _MOCK_RECOVERY_KEY in combined
        assert "패스워드" in combined
        # 에러 메시지에서 test_account_failed 코드 확인
        assert "테스트 계좌 생성 실패" in combined

    def test_master_credentials_json_mode_stderr_event_on_test_account_failure(
        self, runner, tmp_path
    ):
        """옵션 P (JSON 모드): master bootstrap 직후 stderr 1줄 JSON 이벤트.

        test account 실패 시에도 Agent는 stderr에서 비밀값을 파싱할 수 있어야 한다.
        """
        target = tmp_path / "config"

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=RuntimeError("DB lock"))

        # Click 버전별 stderr 캡처 API 차이를 흡수한다.
        runner_split = _split_stderr_runner()

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner_split.invoke(
                cli, ["--format", "json", "init", "--dir", str(target)]
            )

        assert result.exit_code == 1
        # stderr에 master_bootstrap_complete 이벤트
        stderr = result.stderr
        assert "master_bootstrap_complete" in stderr
        # stderr에서 JSON 라인 추출
        master_event = None
        for line in stderr.splitlines():
            line_s = line.strip()
            if line_s.startswith("{") and "master_bootstrap_complete" in line_s:
                master_event = json.loads(line_s)
                break
        assert master_event is not None, f"stderr에 JSON 이벤트 없음: {stderr!r}"
        assert master_event["stage"] == "master_bootstrap_complete"
        assert master_event["token"] == _MOCK_TOKEN
        assert master_event["recovery_key"] == _MOCK_RECOVERY_KEY
        assert "password" in master_event


class TestInitIdempotency:
    """시나리오 3 & 4: 멱등성 — 부분 누락 시 보완 (state 2/3/4/5)."""

    def test_init_skips_db_when_only_config_files_exist(self, runner, tmp_path):
        """보완 케이스: secrets.env만 존재 → 나머지 생성 (state 5 경로).

        이슈 #1721 이후: 기존 secrets.env에 ANTE_DB_ENCRYPTION_KEY 라인이 없으면
        init이 신규 키 라인을 append한다(기존 콘텐츠는 보존). 따라서 기존 콘텐츠가
        prefix로 보존되는지를 검증한다(전체 동일성이 아닌 prefix 보존).
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
        # 기존 콘텐츠 보존 + 키 라인 추가
        new_text = (target / "secrets.env").read_text()
        assert new_text.startswith("existing"), (
            f"기존 콘텐츠 'existing' prefix가 사라짐: {new_text!r}"
        )
        assert "ANTE_DB_ENCRYPTION_KEY=" in new_text

    def test_init_preserves_existing_config_files(self, runner, tmp_path):
        """system.toml + secrets.env 있고 DB 없음 → DB 재생성, 설정 파일 보존.

        이슈 #1721 이후: secrets.env는 기존 콘텐츠를 보존하면서 부족한
        ANTE_DB_ENCRYPTION_KEY 라인만 append한다.
        """
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
        # 기존 설정 파일 보존 (system.toml은 _ensure_file 가드라 그대로)
        assert (target / "system.toml").read_text() == "# custom config\n"
        # secrets.env는 기존 CUSTOM=1 라인 보존 + 키 라인 append
        new_text = (target / "secrets.env").read_text()
        assert "CUSTOM=1" in new_text
        assert "ANTE_DB_ENCRYPTION_KEY=" in new_text
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

        # JSON 파싱 — 최종 payload는 stdout의 마지막 멀티라인 JSON 오브젝트
        lines = result.output.strip().splitlines()
        # 최종 JSON은 indent=2로 출력되므로 마지막 "}" 역순으로 매칭된 "{" 지점을 찾는다
        json_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{":
                json_start = i
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
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
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
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
            ),
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

    middleware._AUTH_EXEMPT_COMMAND_PATHS에 ('init',)이 포함되어 있으므로
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
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
            ),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        assert "인증 실패" not in result.output
        assert "init이 이미 완료된 상태입니다" not in result.output


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
        db_path = target / "db" / "ante.db"
        _create_full_db(db_path)

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(
                cli, ["--format", "json", "init", "--dir", str(target)]
            )

        assert result.exit_code == 1, (
            f"exit=1 기대 (got {result.exit_code}): {result.output}"
        )
        data = self._parse_error_json(result.output)
        assert data["status"] == "error"
        assert "init이 이미 완료된 상태입니다" in data["message"]
        assert data.get("code") == "CLI_ALREADY_INITIALIZED"

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
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
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
        assert data["status"] == "error"
        assert "패스워드 정책 위반" in data["message"]
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
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
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
        assert data["status"] == "error"
        assert "테스트 계좌 생성 실패" in data["message"]
        assert "DB lock" in data["message"]
        assert data.get("code") == "test_account_failed"

    def test_init_already_initialized_text_mode_preserves_message(
        self, runner, tmp_path
    ):
        """text 모드에서도 멱등성 거부 메시지가 유지되어야 한다 (기존 테스트 호환)."""
        target = tmp_path / "config"
        target.mkdir()
        (target / "system.toml").write_text("x")
        (target / "secrets.env").write_text("x")
        db_path = target / "db" / "ante.db"
        _create_full_db(db_path)

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 1
        # text 모드에서는 OutputFormatter.error가 "Error: ..." 를 stderr로 보낸다
        # CliRunner 기본 mix_stderr=True이면 result.output에 섞여 보인다
        assert "init이 이미 완료된 상태입니다" in result.output


class TestInitCredentialsSingleEmission:
    """Codex 5차 리뷰 Finding 1 회귀 — 비밀값은 각 스트림에서 정확히 1회 노출."""

    def test_master_credentials_emitted_once_in_text_mode(self, runner, tmp_path):
        """성공 경로에서 password/token/recovery_key는 stdout에 정확히 1회만."""
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
        # 각 비밀값은 stdout에 정확히 1회만 (성공 경로 중복 노출 방지)
        assert result.output.count(_MOCK_TOKEN) == 1, (
            f"token 중복 노출: {result.output}"
        )
        assert result.output.count(_MOCK_RECOVERY_KEY) == 1, (
            f"recovery_key 중복 노출: {result.output}"
        )
        # password — bootstrap 호출 args[3]에서 추출
        bootstrap_args = None
        for p in patches:
            target_obj = getattr(p, "new", None)
            if target_obj and hasattr(target_obj, "call_args") and target_obj.call_args:
                args = target_obj.call_args.args
                if len(args) >= 4 and args[0].endswith("ante.db"):
                    bootstrap_args = args
                    break
        assert bootstrap_args is not None, "bootstrap mock 호출 미확인"
        password = bootstrap_args[3]
        assert result.output.count(password) == 1, (
            f"password 중복 노출: {result.output}"
        )

    def test_master_credentials_emitted_only_in_stdout_on_json_success(
        self, runner, tmp_path
    ):
        """JSON 성공 경로 — stderr에 master_bootstrap_complete 이벤트 없음."""
        target = tmp_path / "config"
        runner_split = _split_stderr_runner()

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner_split.invoke(
                cli, ["--format", "json", "init", "--dir", str(target)]
            )

        assert result.exit_code == 0, f"stdout={result.output} stderr={result.stderr}"
        # stderr에는 master_bootstrap_complete 이벤트가 없어야 한다 (중복 노출 방지)
        assert "master_bootstrap_complete" not in result.stderr, (
            f"성공 경로에서 stderr 이벤트 중복: {result.stderr!r}"
        )
        # stdout JSON payload는 token/recovery_key/password 포함
        lines = result.output.strip().splitlines()
        json_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{":
                json_start = i
        assert json_start is not None, f"stdout에 JSON 없음: {result.output!r}"
        data = json.loads("\n".join(lines[json_start:]))
        assert data["token"] == _MOCK_TOKEN
        assert data["recovery_key"] == _MOCK_RECOVERY_KEY
        assert "password" in data
        # stdout에서 token도 정확히 1회
        assert result.output.count(_MOCK_TOKEN) == 1

    def test_json_failure_preserves_credentials_in_stderr(self, runner, tmp_path):
        """JSON 실패 경로 — stderr에 master_bootstrap_complete 이벤트(비밀값 포함)."""
        target = tmp_path / "config"
        runner_split = _split_stderr_runner()

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=RuntimeError("DB lock"))

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="missing"),
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner_split.invoke(
                cli, ["--format", "json", "init", "--dir", str(target)]
            )

        assert result.exit_code == 1
        # stderr에 master_bootstrap_complete 이벤트 (복구 수단)
        assert "master_bootstrap_complete" in result.stderr
        # stdout에는 에러 payload, 비밀값 미포함
        stdout = result.stdout
        assert _MOCK_TOKEN not in stdout, (
            f"JSON 실패 payload(stdout)에 토큰 포함: {stdout!r}"
        )
        assert _MOCK_RECOVERY_KEY not in stdout
        # stderr에는 비밀값 정확히 1회
        assert result.stderr.count(_MOCK_TOKEN) == 1
        assert result.stderr.count(_MOCK_RECOVERY_KEY) == 1


class TestInitTestAccountDetectionNarrowed:
    """Codex 5차 리뷰 Finding 2 회귀 — test account 판정은 default 조건만 매치."""

    def test_state4_with_custom_test_broker_still_creates_default(
        self, runner, tmp_path
    ):
        """custom broker_type='test' 계좌(account_id!='test')여도 default 생성."""
        target = tmp_path / "config"
        target.mkdir()
        db_path = target / "db" / "ante.db"
        # master row + custom test broker 계좌 (account_id='custom-test')
        _create_db_with_master_row(db_path)
        _create_db_with_test_account_row(
            db_path, account_id="custom-test", broker_type="test", status="active"
        )

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0, result.output
        # default test account(account_id='test')는 따로 생성돼야 한다
        create_acc_mock.assert_called_once()
        # master는 이미 있으므로 bootstrap은 호출 안 됨
        bootstrap_mock.assert_not_called()

    def test_test_account_suspended_raises_clear_error(self, runner, tmp_path):
        """Finding 3 (Codex 6차 review) — status='suspended'인 'test' account는
        명시적 에러로 안내해야 한다.

        과거 구현은 suspended/deleted 상태를 `False` (없음)로 판정해 재생성 시도를
        했지만 `AccountService.create_default_test_account()`는 `account_id='test'`
        중복 검사에 걸려 예외를 던진다 → init 자체가 실패하면서 사용자에게는
        원인이 불명확하다. 이제는 3-state (active/inactive/missing) 판정으로
        inactive를 만나면 `test_account_inactive` 에러 코드로 안내한다.
        """
        target = tmp_path / "config"
        target.mkdir()
        db_path = target / "db" / "ante.db"
        # master row + suspended test account (account_id='test', status='suspended')
        _create_db_with_master_row(db_path)
        _create_db_with_test_account_row(
            db_path, account_id="test", broker_type="test", status="suspended"
        )

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 1, result.output
        # 명시적 에러 안내 — suspended/deleted 상태임을 사용자가 바로 인지 가능
        assert "비활성 상태" in result.output
        assert "account activate" in result.output
        # 묵시적 재생성/bootstrap 시도 금지
        create_acc_mock.assert_not_called()
        bootstrap_mock.assert_not_called()

    def test_test_account_deleted_raises_clear_error(self, runner, tmp_path):
        """Finding 3 — status='deleted'인 'test' account도 동일하게 명시적 에러."""
        target = tmp_path / "config"
        target.mkdir()
        db_path = target / "db" / "ante.db"
        _create_db_with_master_row(db_path)
        _create_db_with_test_account_row(
            db_path, account_id="test", broker_type="test", status="deleted"
        )

        bootstrap_mock = AsyncMock(side_effect=_mock_bootstrap)
        create_acc_mock = AsyncMock(side_effect=_mock_create_test_account)

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch("ante.cli.commands.init._create_test_account", new=create_acc_mock),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 1, result.output
        assert "비활성 상태" in result.output
        create_acc_mock.assert_not_called()
        bootstrap_mock.assert_not_called()


class TestInitConfigDirContract:
    """ante init이 전역 --config-dir / ANTE_CONFIG_DIR 계약을 따라야 한다.

    Codex 12차 리뷰 Finding 1 회귀 — `_resolve_config_path`가 `--dir` 인자만
    보고 `~/.config/ante`로 폴백하면 후속 CLI들이 `get_db_path()`로 보는
    `<config_dir>/db/ante.db`와 init이 만든 DB 경로가 어긋난다.
    """

    def test_resolve_uses_ctx_config_dir_when_dir_not_given(self, tmp_path):
        """--dir 없으면 ctx.obj['config_dir']를 우선 사용 (root --config-dir)."""
        from ante.cli.commands.init import _resolve_config_path

        custom = tmp_path / "ctx-cfg"
        ctx = click.Context(cli, obj={"config_dir": custom})
        result = _resolve_config_path(ctx, target_dir=None)
        assert result == custom

    def test_resolve_uses_ctx_config_dir_string_value(self, tmp_path):
        """ctx.obj['config_dir']가 str여도 Path로 변환하여 사용."""
        from ante.cli.commands.init import _resolve_config_path

        custom = tmp_path / "ctx-cfg-str"
        ctx = click.Context(cli, obj={"config_dir": str(custom)})
        result = _resolve_config_path(ctx, target_dir=None)
        assert result == custom

    def test_resolve_uses_ante_config_dir_env(self, tmp_path, monkeypatch):
        """--dir, ctx config_dir 모두 없으면 ANTE_CONFIG_DIR 사용."""
        from ante.cli.commands.init import _resolve_config_path

        custom = tmp_path / "env-cfg"
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(custom))
        ctx = click.Context(cli, obj={})
        result = _resolve_config_path(ctx, target_dir=None)
        assert result == custom

    def test_resolve_dir_arg_takes_precedence_over_ctx_config_dir(self, tmp_path):
        """--dir 인자가 지정되면 ctx config_dir/ANTE_CONFIG_DIR 모두 무시."""
        from ante.cli.commands.init import _resolve_config_path

        explicit = tmp_path / "explicit"
        ctx_cfg = tmp_path / "ctx-cfg"
        ctx = click.Context(cli, obj={"config_dir": ctx_cfg})
        result = _resolve_config_path(ctx, target_dir=str(explicit))
        assert result == explicit

    def test_resolve_dir_arg_takes_precedence_over_env(self, tmp_path, monkeypatch):
        """--dir 인자가 ANTE_CONFIG_DIR 환경변수보다 우선."""
        from ante.cli.commands.init import _resolve_config_path

        explicit = tmp_path / "explicit-env"
        env_cfg = tmp_path / "env-cfg"
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_cfg))
        ctx = click.Context(cli, obj={})
        result = _resolve_config_path(ctx, target_dir=str(explicit))
        assert result == explicit

    def test_init_writes_to_config_dir_from_root_option(self, runner, tmp_path):
        """`ante --config-dir <path> init`이 그 디렉토리에 산출물을 쓴다.

        통합 검증 — root group이 ctx.obj['config_dir']를 세팅하고 init이
        그 값을 사용해야 한다.
        """
        target = tmp_path / "root-cfg"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["--config-dir", str(target), "init"])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()

    def test_init_writes_to_ante_config_dir_env(self, runner, tmp_path, monkeypatch):
        """`ANTE_CONFIG_DIR=<path> ante init`이 그 디렉토리에 산출물을 쓴다."""
        target = tmp_path / "env-cfg-init"
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(target))

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init"])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()


class TestInitSystemTomlAbsoluteDbPath:
    """init이 생성하는 system.toml의 db.path가 절대 경로여야 한다.

    Codex 12차 리뷰 Finding 2 회귀 — 상대 경로 `db/ante.db`를 그대로 쓰면
    서버(`ante system start`)와 IPC가 cwd 기준 `./db/ante.db`를 보고,
    CLI는 `<config_dir>/db/ante.db`를 보아 두 DB가 어긋난다.
    """

    def test_system_toml_db_path_is_absolute(self, runner, tmp_path):
        """fresh init 후 system.toml의 db.path가 `<config>/db/ante.db` 절대 경로."""
        target = tmp_path / "abs-cfg"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output

        toml_text = (target / "system.toml").read_text()
        expected = (target / "db" / "ante.db").resolve()
        assert f'path = "{expected}"' in toml_text, (
            f"db.path 절대 경로가 system.toml에 없음:\n{toml_text}"
        )
        # 더 이상 상대 경로 'db/ante.db' (큰따옴표 포함)가 system.toml에 없어야
        assert 'path = "db/ante.db"' not in toml_text

    def test_system_toml_db_path_with_root_config_dir(self, runner, tmp_path):
        """`--config-dir <path> init` 경로에서도 db.path가 절대 경로."""
        target = tmp_path / "abs-root"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["--config-dir", str(target), "init"])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        toml_text = (target / "system.toml").read_text()
        expected = (target / "db" / "ante.db").resolve()
        assert f'path = "{expected}"' in toml_text


class TestInitSystemTomlRuntimeSection:
    """Refs #1157: ``ante init``이 만든 ``system.toml``에 ``[runtime]`` 섹션이
    들어가고, 섹션이 없는 기존 설치도 default fallback으로 동작해야 한다.
    """

    def test_system_toml_template_includes_runtime_section(self, runner, tmp_path):
        """fresh init 후 system.toml에 ``[runtime] pid_path/socket_path``가 있다."""
        from ante.cli.commands.init import SYSTEM_TOML_TEMPLATE

        # 1) 템플릿 자체에 [runtime] 섹션과 두 키가 정의되어 있어야 한다.
        assert "[runtime]" in SYSTEM_TOML_TEMPLATE
        assert 'pid_path = "run/ante.pid"' in SYSTEM_TOML_TEMPLATE
        assert 'socket_path = "run/ante.sock"' in SYSTEM_TOML_TEMPLATE

        # 2) 실제 init이 만든 system.toml에도 같은 섹션이 보존된다.
        target = tmp_path / "init-runtime"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        toml_text = (target / "system.toml").read_text()
        assert "[runtime]" in toml_text
        assert 'pid_path = "run/ante.pid"' in toml_text
        assert 'socket_path = "run/ante.sock"' in toml_text

    def test_existing_system_toml_without_runtime_section_falls_back_to_defaults(
        self, tmp_path
    ):
        """``[runtime]`` 부재 시 default canonical을 산출.

        기존 ``config_dir``에 자동으로 ``[runtime]`` 섹션을 주입할 필요는 없다 —
        Config DEFAULTS가 ``run/ante.pid``/``run/ante.sock``을 보장한다.
        """
        from ante.config import Config

        # [runtime] 섹션이 없는 baseline system.toml
        (tmp_path / "system.toml").write_text(
            '[system]\nlog_level = "INFO"\n\n[db]\npath = "db/ante.db"\n',
            encoding="utf-8",
        )

        config = Config.load(config_dir=tmp_path)

        assert config.runtime_pid_path() == tmp_path / "run" / "ante.pid"
        assert config.runtime_socket_path() == tmp_path / "run" / "ante.sock"


# ── Issue #1721: ANTE_DB_ENCRYPTION_KEY 자동 생성/동기화 회귀 ───────────────


_KEY_LINE_REGEX = r"^ANTE_DB_ENCRYPTION_KEY=[A-Za-z0-9_-]{43}=$"


def _read_key_line(secrets_env_path: Path) -> str | None:
    """secrets.env에서 ANTE_DB_ENCRYPTION_KEY 라인의 값만 추출."""
    if not secrets_env_path.exists():
        return None
    last: str | None = None
    for raw in secrets_env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "ANTE_DB_ENCRYPTION_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        last = value
    return last


class TestInitDbEncryptionKeyAutoCreate:
    """이슈 #1721 — ``ante init``이 ANTE_DB_ENCRYPTION_KEY를 생성·persist한다."""

    def test_r1_fresh_init_creates_fernet_line(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R1: 신규 init이 secrets.env에 Fernet 형식 키 라인을 생성한다.

        라인 형식 정규식 ``^ANTE_DB_ENCRYPTION_KEY=[A-Za-z0-9_-]{43}=$`` 매치.
        """
        import re

        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        target = tmp_path / "fresh"

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
        text = secrets_env.read_text()
        matches = [
            line
            for line in text.splitlines()
            if re.match(_KEY_LINE_REGEX, line.strip())
        ]
        assert matches, f"Fernet 키 라인 없음:\n{text}"

    def test_r2a_file_missing_no_env_generates_new(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2a: secrets.env 파일 없음 + env 없음 → 신규 키 생성."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        target = tmp_path / "no-file"
        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()
        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value is not None and len(value) == 44 and value.endswith("=")

    def test_r2b_file_exists_no_key_line_appends_line(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2b: secrets.env는 있으나 키 라인이 없음 → 라인 append."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        target = tmp_path / "file-no-line"
        target.mkdir()
        (target / "secrets.env").write_text("# user comment\nFOO=bar\n")

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        text = (target / "secrets.env").read_text()
        # 기존 내용 보존
        assert "# user comment" in text
        assert "FOO=bar" in text
        # 키 라인 추가
        value = _read_key_line(target / "secrets.env")
        assert value is not None and len(value) == 44 and value.endswith("=")

    def test_r2c_file_has_empty_value_replaces(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2c: 키 라인이 빈 값 → 신규 키로 교체 (빈 값은 backup 대상 아님)."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        target = tmp_path / "empty-value"
        target.mkdir()
        (target / "secrets.env").write_text("ANTE_DB_ENCRYPTION_KEY=\n")

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value is not None and len(value) == 44 and value.endswith("=")
        # 빈 값은 backup 대상이 아님
        backups = list(target.glob("secrets.env.bak.*"))
        assert not backups, f"빈 값에 대해 backup이 생성됨: {backups}"

    def test_r2d_file_has_invalid_value_backs_up_and_replaces(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2d: 키 라인 값이 non-empty invalid → backup 후 신규 키 교체."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        target = tmp_path / "invalid-value"
        target.mkdir()
        (target / "secrets.env").write_text(
            "ANTE_DB_ENCRYPTION_KEY=garbage-not-fernet-key\n"
        )

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value is not None and len(value) == 44 and value.endswith("=")
        # backup 생성 확인
        backups = list(target.glob("secrets.env.bak.*"))
        assert len(backups) == 1, f"backup이 정확히 1개 생성돼야 함: {backups}"
        # backup 내용에 invalid 값이 보존되어야 함
        assert "garbage-not-fernet-key" in backups[0].read_text()
        # backup 권한 0600
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600

    def test_r2e_file_has_valid_value_no_env_is_idempotent(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2e: 키 라인이 valid + env 없음 → file 보존, idempotent."""
        from cryptography.fernet import Fernet

        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        target = tmp_path / "valid-file"
        target.mkdir()
        good = Fernet.generate_key().decode()
        (target / "secrets.env").write_text(f"ANTE_DB_ENCRYPTION_KEY={good}\n")

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value == good
        # backup 없음
        assert not list(target.glob("secrets.env.bak.*"))

    def test_r3_valid_env_no_file_syncs_to_file(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R3: non-empty valid env + secrets.env 라인 없음 → env value로 동기화."""
        from cryptography.fernet import Fernet

        env_key = Fernet.generate_key().decode()
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", env_key)
        target = tmp_path / "env-sync"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value == env_key

    def test_r4_valid_env_invalid_file_replaces_with_backup(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R4: valid env + invalid file → env value 기입 + invalid backup."""
        from cryptography.fernet import Fernet

        env_key = Fernet.generate_key().decode()
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", env_key)
        target = tmp_path / "env-replace"
        target.mkdir()
        (target / "secrets.env").write_text("ANTE_DB_ENCRYPTION_KEY=bad-bad-bad\n")

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value == env_key
        # invalid backup 1개 생성, 내용 보존
        backups = list(target.glob("secrets.env.bak.*"))
        assert len(backups) == 1
        assert "bad-bad-bad" in backups[0].read_text()

    def test_r5_empty_env_creates_new_key(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R5: 빈 env (``ANTE_DB_ENCRYPTION_KEY=``) → exit 0 + 신규 라인 생성."""
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "")
        target = tmp_path / "empty-env"

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value is not None and len(value) == 44 and value.endswith("=")

    def test_r6_e2e_subprocess_no_leak_stdout_or_stderr(self, tmp_path: Path) -> None:
        """R6: 실제 subprocess로 e2e 실행 + stdout/stderr 분리 capture 후 키 leak 검사.

        Codex v3 new-must-fix 3 / v4 narrow-to 2: 병합 캡처 금지.
        """
        import subprocess
        import sys

        target = tmp_path / "e2e-config"
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(tmp_path)),
            "ANTE_CONFIG_DIR": str(target),
            # member_token 미설정으로 stale 토큰 검증 우회
        }
        # PYTHONPATH 전파: src 트리에서 import 가능하게
        repo_root = Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = str(repo_root / "src")

        result = subprocess.run(
            [sys.executable, "-m", "ante", "--format", "json", "init", "--name", "E2E"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        # secrets.env 라인 존재
        value = _read_key_line(target / "secrets.env")
        assert value is not None and len(value) == 44 and value.endswith("=")
        # stdout/stderr 모두에서 키 부재 (분리 capture, 병합 금지)
        assert value not in result.stdout, "stdout에 키 leak"
        assert value not in result.stderr, "stderr에 키 leak"

    def test_r7_invalid_env_preserves_valid_file(
        self, runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R7 (Codex v3 new-must-fix 4): non-empty invalid env + valid file.

        - env가 invalid이면 무시한다.
        - file의 valid value를 effective key로 채택한다.
        - file은 그대로 보존(env value가 file을 wipe하지 않음).
        - invalid env value는 절대 file에 기록되지 않는다.
        - backup 없음(file은 valid 상태로 유지).
        """
        from cryptography.fernet import Fernet

        good = Fernet.generate_key().decode()
        invalid_env = "garbage-not-fernet"
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", invalid_env)

        target = tmp_path / "invalid-env-valid-file"
        target.mkdir()
        (target / "secrets.env").write_text(f"ANTE_DB_ENCRYPTION_KEY={good}\n")

        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        value = _read_key_line(target / "secrets.env")
        assert value == good, "valid file이 invalid env에 의해 덮어쓰여짐"
        # invalid env value는 file 어디에도 기록되지 않음
        text = (target / "secrets.env").read_text()
        assert invalid_env not in text
        # backup 없음
        assert not list(target.glob("secrets.env.bak.*"))
