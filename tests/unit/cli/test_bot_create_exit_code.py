"""``ante bot create`` 로컬 검증 실패의 exit code 회귀 (#1534).

배경:
    ``ante --format json bot create --param invalid_no_equals_sign`` 같은
    호출은 stdout 으로 error JSON envelope 를 출력하지만 exit code 가 0 으로
    끝나는 결함이 있었다 (``src/ante/cli/commands/bot.py:237-239`` 의
    BadParameter 분기, ``:272-276`` 의 generic Exception 분기 모두 ``return``
    으로 끝나서 SystemExit 가 발화하지 않음).

    자동화 호출자(특히 CI / agent 파이프라인)는 stdout JSON 만으로 분기하지
    않고 process exit code 를 1차 신호로 사용한다. 본 테스트는 두 분기 모두에서
    JSON / text 모드 양쪽이 exit 1 로 종료되며, stdout/stderr 에 기존 메시지가
    정상 출력됨을 회귀 보장한다.

Coverage map:
    - BadParameter 분기 (``--param invalidformat``)
      - JSON 모드: stdout JSON envelope ``{"status":"error","code":"",
        "message":"잘못된 파라미터 형식: ..."}`` + exit 1.
      - text 모드: stderr ``Error: 잘못된 파라미터 형식: ...`` + exit 1.
    - generic Exception 분기 (``ipc_send`` mock 으로 ``RuntimeError`` raise)
      - JSON 모드: stdout JSON envelope + exit 1.
      - text 모드: stderr ``Error: ...`` + exit 1.

``ante bot positions`` missing-bot exit code 회귀 (#1558):
    ``ante --format json bot positions oracle-missing-bot`` 호출이
    missing-resource 오류가 아니라 exit 0 + ``{"message":"보유 포지션 없음",
    "positions":[]}`` 을 반환해 미존재 bot 이 "실재 bot 의 0 포지션" 과
    구분되지 않는 결함이 있었다 (``bot_positions`` 가 ``get_positions`` 호출
    전 bot 존재 확인을 하지 않고 빈 list 를 성공 메시지로 정규화).

    형제 명령(``bot info`` ``bot.py:138-140`` / ``bot remove``
    ``bot.py:329-330``)과 동일하게 미존재 bot 만 code 없는
    ``봇을 찾을 수 없습니다: <id>`` 에러 + exit 1 로 분기되고, **실재 bot 의
    0 포지션은 기존 계약(exit 0 + "보유 포지션 없음")을 그대로 유지**함을
    회귀 보장한다 (contract-drift 가드).

Coverage map (#1558 → #1810 typed code sweep):
    - 미존재 bot ``bot positions oracle-missing-bot``
      - JSON 모드: stdout ``{"status":"error","code":"BOT_NOT_FOUND",
        "message":"봇을 찾을 수 없습니다: oracle-missing-bot"}`` + exit 1.
      - text 모드: stderr ``Error: 봇을 찾을 수 없습니다: ...`` + exit 1.
    - 실재 bot, 0 포지션: exit 0 + ``{"message":"보유 포지션 없음",
      "positions":[]}`` 유지 (regression guard).
    - 실재 bot, 포지션 >=1: exit 0 + ``{"positions":[...]}`` 유지.

``ante bot positions`` no-bots-table 정규화 회귀 (#1558, Codex P2):
    ``_run_positions`` 가 bot 존재 선조회를 추가하면서, ``bots`` 테이블이
    아직 생성되지 않은 DB(``BotManager.initialize()`` 미실행, 예: ``ante
    init`` 직후)에서 ``sqlite3.OperationalError: no such table: bots`` 가
    호출자까지 누설되는 신규 회귀가 생겼다. ``bots`` 테이블 부재 ⟹ 해당
    bot_id 는 정의상 존재할 수 없으므로 미존재 bot 과 동일하게
    ``봇을 찾을 수 없습니다`` + exit 1 로 정규화됨을 회귀 보장한다.

Coverage map (#1558, Codex P2):
    - bots 테이블이 없는 DB ``bot positions <any-id>``
      - JSON 모드: stdout error envelope + exit 1 (OperationalError 누설 X).
      - text 모드: stderr ``Error: 봇을 찾을 수 없습니다: ...`` + exit 1.

SSOT 참조:
    - ``src/ante/cli/commands/bot.py`` (``bot_create``, ``_parse_param``,
      ``bot_positions``, canonical missing-bot 패턴은 ``bot_info``)
    - ``src/ante/cli/formatter.py`` (``OutputFormatter.error`` 스키마)
    - ``src/ante/bot/manager.py`` (``BOT_SCHEMA``),
      ``src/ante/trade/position.py`` (``POSITION_SCHEMA``)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.bot.manager import BOT_SCHEMA
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.trade.position import POSITION_SCHEMA

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
    """authenticate_member 를 패치해 master member 를 주입하는 runner.

    JSON / stderr 검증을 위해 ``mix_stderr=False`` 로 stdout/stderr 를 분리한다.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001, ANN202
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


def _parse_json_line(stdout: str) -> dict[str, object]:
    """stdout 첫 JSON 라인을 파싱해서 dict 로 반환."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"stdout 에서 JSON dict 를 찾지 못함: {stdout!r}")


# ── BadParameter 분기 (``--param invalidformat``) ───────────────────────────


class TestBotCreateBadParamExitCode:
    """``--param`` 로컬 파싱 실패 분기에서 exit 1 회귀."""

    def test_bad_param_json_mode_emits_json_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout JSON envelope + exit 1."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "bot",
                "create",
                "--name",
                "테스트봇",
                "--strategy",
                "stg-1",
                "--account",
                "test",
                "--param",
                "invalidformat",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        # #1784 Group A sweep: invalid --param 입력은 안정 코드
        # ``BOT_INVALID_PARAM`` 으로 surface 한다 (이전: empty ``code``).
        # 자동화/오라클이 메시지 텍스트 파싱 없이 invalid-input 분류 가능.
        assert payload["code"] == "BOT_INVALID_PARAM", payload
        assert "잘못된 파라미터 형식" in str(payload["message"]), payload
        # text 메시지가 stderr 로 동시에 새지 않아야 한다.
        assert "잘못된 파라미터 형식" not in result.stderr, result.stderr

    def test_bad_param_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """text 모드: stderr ``Error: 잘못된 파라미터 형식 ...`` + exit 1."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "text",
                "bot",
                "create",
                "--name",
                "테스트봇",
                "--strategy",
                "stg-1",
                "--account",
                "test",
                "--param",
                "invalidformat",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # text 모드: stdout 에 JSON 이 새지 않아야 한다.
        assert result.stdout.strip() == "", result.stdout
        assert "Error: 잘못된 파라미터 형식" in result.stderr, result.stderr


# ── generic Exception 분기 (``ipc_send`` raise) ─────────────────────────────


class TestBotCreateIPCExceptionExitCode:
    """``ipc_send`` 가 generic Exception 을 raise 했을 때 exit 1 회귀."""

    @staticmethod
    def _build_ipc_mock_failing(message: str) -> AsyncMock:
        """``ipc_send`` 를 mock 해서 ``RuntimeError(message)`` 를 raise."""
        mock = AsyncMock(side_effect=RuntimeError(message))
        return mock

    def test_ipc_exception_json_mode_emits_json_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout JSON envelope + exit 1."""
        ipc_mock = self._build_ipc_mock_failing("IPC 연결 실패")

        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_mock):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "stg-1",
                    "--account",
                    "test",
                ],
            )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        # #1843 sub-PR 3: ``bot create`` generic except 가 ``emit_cli_error``
        # 로 정렬되어, registry 미등록 + ``.code`` 부재 (RuntimeError) 인
        # 경우 taxonomy SSOT (``docs/specs/contracts/error-taxonomy.md``)
        # 의 ``EXECUTION_ERROR`` fallback 으로 surface 한다. 이전 ad-hoc
        # ``code=""`` 동작은 의도된 taxonomy 정렬 (#1840 helper SSOT) 로
        # 교체된 결과다. CLI direct ↔ IPC envelope 동일 코드 surface 의
        # 의도된 결과 — IPC server.py:322 도 ``getattr(e, "code",
        # "EXECUTION_ERROR")`` 로 동일 fallback 을 사용한다.
        assert payload["code"] == "EXECUTION_ERROR", payload
        assert "IPC 연결 실패" in str(payload["message"]), payload
        # text fallback 이 stderr 로 동시에 새지 않아야 한다.
        assert "IPC 연결 실패" not in result.stderr, result.stderr

    def test_ipc_exception_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """text 모드: stderr ``Error: IPC 연결 실패`` + exit 1."""
        ipc_mock = self._build_ipc_mock_failing("IPC 연결 실패")

        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_mock):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "text",
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "stg-1",
                    "--account",
                    "test",
                ],
            )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # text 모드: stdout 에 JSON 이 새지 않아야 한다.
        assert result.stdout.strip() == "", result.stdout
        assert "Error: IPC 연결 실패" in result.stderr, result.stderr


# ── bot positions missing-bot exit code 회귀 (#1558) ────────────────────────


_MISSING_BOT_ID = "oracle-missing-bot"
_REAL_BOT_ID = "real-bot-1"
_BOT_NOT_FOUND_MESSAGE = f"봇을 찾을 수 없습니다: {_MISSING_BOT_ID}"


def _seed_db(db_path: Path, *, with_position: bool) -> None:
    """``bot positions`` 가 여는 실 DB 를 미리 시드한다.

    - ``bots`` 테이블에 ``_REAL_BOT_ID`` 만 넣는다 (``_MISSING_BOT_ID`` 는
      넣지 않아 미존재 상태를 만든다).
    - ``with_position`` 이면 ``positions`` 에 실재 bot 의 포지션 1건을 넣는다.
      아니면 0 포지션 (실재 bot, 빈 결과) 상태로 둔다.

    스키마는 production SSOT(``BOT_SCHEMA`` / ``POSITION_SCHEMA``) 를 그대로
    사용한다 (테스트 로컬 DDL 하드코딩 금지).
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(BOT_SCHEMA)
        conn.executescript(POSITION_SCHEMA)
        conn.execute(
            "INSERT INTO bots (bot_id, name, strategy_id, account_id, "
            "config_json, status) VALUES (?, ?, ?, ?, ?, ?)",
            (_REAL_BOT_ID, "실재봇", "stg-1", "test", "{}", "created"),
        )
        if with_position:
            conn.execute(
                "INSERT INTO positions (bot_id, symbol, quantity, "
                "avg_entry_price, realized_pnl, account_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_REAL_BOT_ID, "005930", 10.0, 70000.0, 1500.0, "test"),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_db_without_bots_table(db_path: Path) -> None:
    """``bots`` 테이블 DDL 만 생략한 변형 시드 (#1558, Codex P2).

    ``_run_positions`` 는 raw ``Database`` 만 쓰고 ``BotManager.
    initialize()`` 를 호출하지 않으므로, ``ante init`` 직후처럼 ``bots``
    테이블이 아직 없는 상태가 실제로 발생한다. 그 상태를 재현하기 위해
    DB 파일은 만들되 ``BOT_SCHEMA`` 적용만 건너뛴다. (``POSITION_SCHEMA``
    는 선조회가 ``bots`` 에서 먼저 실패하므로 유무가 결과에 무관하지만,
    "DB 파일은 존재한다" 는 사실관계를 명확히 하기 위해 적용한다.)
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(POSITION_SCHEMA)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def seeded_db_path(tmp_path: Path) -> Iterator[Path]:
    """시드된 DB 경로를 ``get_db_path`` 에 주입하는 fixture.

    ``bot_positions._run_positions`` 는 ``from ante.cli.main import
    get_db_path`` 를 함수 로컬 import 로 호출하므로 ``ante.cli.main.
    get_db_path`` 모듈 속성을 패치하면 결정적으로 시드된 DB 를 연다.
    """
    db_path = tmp_path / "ante.db"
    yield db_path


def _invoke_positions(
    runner: CliRunner,
    db_path: Path,
    *,
    bot_id: str,
    fmt: str,
) -> object:
    """``get_db_path`` 를 시드 DB 로 패치한 뒤 ``bot positions`` 호출."""
    with patch("ante.cli.main.get_db_path", return_value=str(db_path)):
        return runner.invoke(
            cli,
            ["--format", fmt, "bot", "positions", bot_id],
        )


class TestBotPositionsMissingBotExitCode:
    """미존재 bot 은 exit 1 + ``봇을 찾을 수 없습니다`` 에러로 분기된다 (#1558).

    형제 명령(``bot info`` / ``bot remove``)과 동일하게 code 없는 에러
    메시지 + exit 1. 결함 시점에는 exit 0 + ``보유 포지션 없음`` 이었다.
    """

    def test_missing_bot_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner, seeded_db_path: Path
    ) -> None:
        """JSON 모드: stdout error envelope + exit 1 (결함 재현 케이스)."""
        _seed_db(seeded_db_path, with_position=False)

        result = _invoke_positions(
            runner, seeded_db_path, bot_id=_MISSING_BOT_ID, fmt="json"
        )

        assert result.exit_code == 1, (
            f"expected exit 1 for missing bot, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        # #1810: 미존재 bot 은 안정 코드 ``BOT_NOT_FOUND`` 로 surface 한다
        # (이전 #1558 의 "code 없음" 계약은 자동화 분류 불가 결함으로
        # 보고되어 본 sweep 에서 폐기, ``bot info``/``bot remove`` 형제
        # 패턴과 정렬).
        assert payload["code"] == "BOT_NOT_FOUND", payload
        assert _BOT_NOT_FOUND_MESSAGE in str(payload["message"]), payload
        # 결함 시점의 success envelope 가 더는 새지 않아야 한다.
        assert "보유 포지션 없음" not in result.stdout, result.stdout

    def test_missing_bot_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner, seeded_db_path: Path
    ) -> None:
        """text 모드: stderr ``Error: 봇을 찾을 수 없습니다: ...`` + exit 1."""
        _seed_db(seeded_db_path, with_position=False)

        result = _invoke_positions(
            runner, seeded_db_path, bot_id=_MISSING_BOT_ID, fmt="text"
        )

        assert result.exit_code == 1, (
            f"expected exit 1 for missing bot, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # text 모드: stdout 에 success/JSON 이 새지 않아야 한다.
        assert "보유 포지션 없음" not in result.stdout, result.stdout
        assert f"Error: {_BOT_NOT_FOUND_MESSAGE}" in result.stderr, result.stderr


class TestBotPositionsRealBotContractUnchanged:
    """contract-drift 가드: 실재 bot 의 0/N 포지션 출력 계약은 불변 (#1558)."""

    def test_real_bot_zero_positions_keeps_exit_0_envelope(
        self, runner: CliRunner, seeded_db_path: Path
    ) -> None:
        """실재 bot, 0 포지션: exit 0 + ``보유 포지션 없음`` 유지 (regression
        guard). 미존재 bot 분기가 blanket "빈 결과 → 에러" 로 번지면 실패."""
        _seed_db(seeded_db_path, with_position=False)

        result = _invoke_positions(
            runner, seeded_db_path, bot_id=_REAL_BOT_ID, fmt="json"
        )

        assert result.exit_code == 0, (
            f"expected exit 0 for real bot w/ 0 positions, "
            f"got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # 실재 bot 0 포지션의 정상 계약은 ``fmt.output`` 으로 indent=2
        # 멀티라인 JSON 을 출력하므로(에러 envelope 의 한 줄 형식이 아님),
        # stdout 전체를 파싱한다.
        payload = json.loads(result.stdout)
        assert payload == {
            "message": "보유 포지션 없음",
            "positions": [],
        }, payload

    def test_real_bot_with_positions_keeps_exit_0_output(
        self, runner: CliRunner, seeded_db_path: Path
    ) -> None:
        """실재 bot, 포지션 >=1: exit 0 + ``{"positions":[...]}`` 유지."""
        _seed_db(seeded_db_path, with_position=True)

        result = _invoke_positions(
            runner, seeded_db_path, bot_id=_REAL_BOT_ID, fmt="json"
        )

        assert result.exit_code == 0, (
            f"expected exit 0 for real bot w/ positions, "
            f"got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict), payload
        assert "positions" in payload, payload
        positions = payload["positions"]
        assert isinstance(positions, list) and len(positions) == 1, payload
        assert positions[0]["symbol"] == "005930", payload
        assert positions[0]["quantity"] == 10.0, payload


class TestBotPositionsNoBotsTableNormalized:
    """``bots`` 테이블 부재 DB 도 미존재 bot 으로 정규화된다 (#1558, Codex P2).

    bot 존재 선조회가 ``sqlite3.OperationalError: no such table: bots`` 를
    호출자까지 누설하지 않고, 형제 명령과 동일한 ``봇을 찾을 수 없습니다``
    + exit 1 계약으로 흡수됨을 잠근다. 수정 전에는 OperationalError 가
    누설되어 click 가 exit 1 (uncaught) 로 끝나거나 traceback 이 새어
    ``봇을 찾을 수 없습니다`` 메시지 계약이 깨졌다.
    """

    def test_no_bots_table_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner, seeded_db_path: Path
    ) -> None:
        """JSON 모드: stdout error envelope + exit 1 (OperationalError 누설 X)."""
        _seed_db_without_bots_table(seeded_db_path)

        result = _invoke_positions(
            runner, seeded_db_path, bot_id=_MISSING_BOT_ID, fmt="json"
        )

        assert result.exit_code == 1, (
            f"expected exit 1 when bots table missing, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # OperationalError 가 traceback 으로 새지 않아야 한다.
        assert "OperationalError" not in result.stdout, result.stdout
        assert "OperationalError" not in result.stderr, result.stderr
        assert "no such table" not in result.stdout, result.stdout
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        # #1810: 미존재 bot (bots 테이블 부재 정규화 포함) 은 안정 코드
        # ``BOT_NOT_FOUND`` 로 surface 한다.
        assert payload["code"] == "BOT_NOT_FOUND", payload
        assert _BOT_NOT_FOUND_MESSAGE in str(payload["message"]), payload

    def test_no_bots_table_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner, seeded_db_path: Path
    ) -> None:
        """text 모드: stderr ``Error: 봇을 찾을 수 없습니다: ...`` + exit 1."""
        _seed_db_without_bots_table(seeded_db_path)

        result = _invoke_positions(
            runner, seeded_db_path, bot_id=_MISSING_BOT_ID, fmt="text"
        )

        assert result.exit_code == 1, (
            f"expected exit 1 when bots table missing, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "OperationalError" not in result.stdout, result.stdout
        assert "OperationalError" not in result.stderr, result.stderr
        assert f"Error: {_BOT_NOT_FOUND_MESSAGE}" in result.stderr, result.stderr
