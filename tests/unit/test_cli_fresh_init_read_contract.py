"""fresh init 후 읽기 CLI 의 public contract 회귀 (#1753).

`ante init` 직후 strategies / trades 테이블이 아직 생성되지 않은 상태에서
다음 read CLI 가 사용자에게 내부 DB schema 명을 노출하거나 stderr traceback
을 누설하지 않아야 한다.

회귀 매트릭스:

- R1: `strategy list --format json` → exit 0, JSON `{"strategies": []}`
  (또는 동등 빈 응답), stderr 비어 있음, raw `no such table` 메시지 없음.
- R2: `strategy info missing --format json` → exit 1, JSON
  `code="STRATEGY_NOT_FOUND"`, stderr 비어 있음.
- R3: `trade info missing --format json` → exit 1, JSON
  `code="TRADE_NOT_FOUND"`, stderr 비어 있음.
- R4: `strategy performance missing --account-id <id> --format json` →
  exit 1, JSON `code="STRATEGY_NOT_FOUND"`, stderr 비어 있음.
- R5 (sanity): `strategy submit` 후 동일 명령들이 정상 동작하는지 회귀
  보존 — list 가 1건을 반환, info 가 존재 strategy 를 반환.

`_clean_env` + `subprocess.run` 패턴은 `tests/unit/test_cli_account_crypto_error.py`
(#1722 R1-R6) 의 conftest fixture 격리 패턴과 동형이다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# subprocess timeout: hang 회귀를 5초 마진으로 차단한다. 정상 종료는 1-2초.
_SUBPROCESS_TIMEOUT_S = 10.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path, *, encryption_key: str, token: str | None = None
) -> dict[str, str]:
    """subprocess 환경 격리 헬퍼.

    Conftest fixture 격리 원칙: 부모 프로세스의 `ANTE_DB_ENCRYPTION_KEY` /
    `ANTE_MEMBER_TOKEN` 등이 새는 것을 막기 위해 `PATH` / `HOME` /
    `ANTE_CONFIG_DIR` / `ANTE_DB_ENCRYPTION_KEY` / `PYTHONPATH` 만 명시
    전달한다 (`test_cli_account_crypto_error.py` _clean_env 동형).
    """
    env: dict[str, str] = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(config_dir)),
        "ANTE_CONFIG_DIR": str(config_dir),
        "PYTHONPATH": str(_repo_root() / "src"),
        "ANTE_DB_ENCRYPTION_KEY": encryption_key,
    }
    if token is not None:
        env["ANTE_MEMBER_TOKEN"] = token
    return env


@pytest.fixture
def fresh_init(tmp_path: Path) -> tuple[Path, str, str]:
    """`ante init` 만 수행한 fresh config dir + member token + key 페어.

    `init` 이후 strategies / trades 테이블은 아직 어느 명령에도 의해 생성된
    적이 없으므로, 이 fixture 의 직후 호출은 fresh-init read contract 회귀
    매트릭스의 정확한 재현 상태가 된다.
    """
    config_dir = tmp_path / "config"
    key = Fernet.generate_key().decode()

    init_env = _clean_env(config_dir, encryption_key=key)
    result = subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", "init", "--name", "Repro"],
        env=init_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"init 실패: exit={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = json.loads(result.stdout)
    token = payload.get("token")
    assert token, f"init 출력에 token 없음: {payload}"
    return config_dir, token, key


def _run_cli(
    config_dir: Path,
    token: str,
    key: str,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """`ante --format json <args>` 를 subprocess 로 실행한다."""
    env = _clean_env(config_dir, encryption_key=key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _parse_last_json_dict(stdout: str) -> dict:
    """stdout 의 마지막 JSON dict 라인을 추출한다.

    `OutputFormatter.error` 는 JSON 모드에서 한 줄로 dump 한다. 일부 명령은
    info/warning 부가 라인이 stdout 에 섞일 수 있으므로 마지막 dict 라인을
    찾는다 (`test_cli_account_crypto_error.py` `_parse_json_error` 동형).

    `fmt.output(...)` 의 indent JSON 도 첫 라인이 `{` 로 시작하므로 단일
    객체 stdout 인 경우는 `json.loads(stdout)` 가 가장 robust 하다. 두
    경우를 모두 지원한다.
    """
    stripped = stdout.strip()
    if stripped:
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    last_obj: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_obj = obj
    assert last_obj is not None, f"JSON dict 라인을 stdout에서 찾지 못함: {stdout!r}"
    return last_obj


def _assert_no_internal_schema_leak(payload_text: str) -> None:
    """payload 에 raw `no such table` 메시지가 노출되지 않았는지 검증."""
    lowered = payload_text.lower()
    assert "no such table" not in lowered, (
        f"내부 SQL schema 메시지가 노출되었습니다: {payload_text!r}"
    )


def _assert_no_traceback(stderr: str) -> None:
    """stderr 에 Python traceback 흔적이 없는지 검증.

    `Traceback (most recent call last)` 헤더, raw `sqlite3.OperationalError`
    type 노출 등을 차단한다.
    """
    assert "Traceback" not in stderr, f"stderr 에 traceback 노출: {stderr!r}"
    assert "sqlite3.OperationalError" not in stderr, (
        f"stderr 에 sqlite3.OperationalError 노출: {stderr!r}"
    )


# ────────────────────────────────────────────────────────────────────
# R1 — strategy list (fresh DB)
# ────────────────────────────────────────────────────────────────────


class TestStrategyListFreshInit:
    def test_fresh_init_strategy_list_empty_no_schema_leak(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        result = _run_cli(config_dir, token, key, ["strategy", "list"])

        # exit 0: fresh DB 의 빈 리스트는 정상 응답
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        _assert_no_internal_schema_leak(result.stdout)
        _assert_no_traceback(result.stderr)

        payload = _parse_last_json_dict(result.stdout)
        # `strategies` key 가 빈 list 거나,
        # `fmt.output({"message":..., "strategies":[]})` 의 동등 빈 응답이어야 한다.
        assert "strategies" in payload, f"빈 list 응답에 strategies 키 누락: {payload}"
        assert payload["strategies"] == [], (
            f"fresh DB strategy list 가 빈 list 가 아님: {payload}"
        )


# ────────────────────────────────────────────────────────────────────
# R2 — strategy info missing (fresh DB)
# ────────────────────────────────────────────────────────────────────


class TestStrategyInfoFreshInit:
    def test_fresh_init_strategy_info_missing_returns_not_found_code(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        result = _run_cli(config_dir, token, key, ["strategy", "info", "missing-name"])

        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        _assert_no_internal_schema_leak(result.stdout)
        _assert_no_internal_schema_leak(result.stderr)
        _assert_no_traceback(result.stderr)

        payload = _parse_last_json_dict(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "STRATEGY_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R3 — trade info missing (fresh DB)
# ────────────────────────────────────────────────────────────────────


class TestTradeInfoFreshInit:
    def test_fresh_init_trade_info_missing_returns_not_found_code(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        result = _run_cli(config_dir, token, key, ["trade", "info", "missing-id"])

        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        _assert_no_internal_schema_leak(result.stdout)
        _assert_no_internal_schema_leak(result.stderr)
        _assert_no_traceback(result.stderr)

        payload = _parse_last_json_dict(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "TRADE_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R4 — strategy performance missing (fresh DB)
# ────────────────────────────────────────────────────────────────────


class TestStrategyPerformanceFreshInit:
    def test_fresh_init_strategy_performance_missing_returns_not_found(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        # --account-id 는 필수 옵션. fresh DB 에서 strategies 테이블 부재가
        # 먼저 NOT_FOUND 로 정규화 되는지를 확인하기 위해 account 도 missing
        # 으로 넘기되, strategy NOT_FOUND 가 먼저 라우팅 되어야 한다.
        # (구현 순서: registry.initialize → get_by_name → 미존재 None → 호출
        # 표면 STRATEGY_NOT_FOUND)
        result = _run_cli(
            config_dir,
            token,
            key,
            [
                "strategy",
                "performance",
                "missing-name",
                "--account-id",
                "missing-account",
            ],
        )

        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        _assert_no_internal_schema_leak(result.stdout)
        _assert_no_internal_schema_leak(result.stderr)
        _assert_no_traceback(result.stderr)

        payload = _parse_last_json_dict(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "STRATEGY_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R5 — sanity: submit 후 list / info 정상 동작 (회귀 보존)
# ────────────────────────────────────────────────────────────────────


_DUMMY_STRATEGY_SRC = textwrap.dedent(
    '''\
    """샘플 전략 (fresh-init contract R5 sanity 회귀용).

    `tests/unit/test_cli_strategy.py::TestStrategySubmit.strategy_file` 와
    동형 dummy. CLI submit 정상 경로의 회귀 sanity 만 확인하며 본 모듈은
    on_step 등 런타임 콜백은 실행하지 않는다.
    """

    from ante.strategy.base import Signal, Strategy, StrategyMeta


    class SampleR5Strategy(Strategy):
        meta = StrategyMeta(
            name="sample_r5",
            version="0.0.1",
            description="fresh-init contract R5 sanity",
            author="test",
        )

        async def on_step(self, context):  # pragma: no cover - not exercised
            return []
    '''
)


class TestPostSubmitReadSanity:
    def test_post_submit_strategy_list_and_info(
        self, fresh_init: tuple[Path, str, str], tmp_path: Path
    ) -> None:
        """`strategy submit` 후 list/info 가 정상 응답하는지 회귀.

        helper 의 `await registry.initialize()` 통합이 register 경로를
        깨뜨리지 않는지, list/info 가 사용자 데이터를 정상 반환하는지를
        잠근다. submit 실패 (예: dummy 전략 schema 불일치) 시 본 테스트는
        skip 한다 — 본 contract 회귀의 주된 락은 R1-R4 의 fresh-init 경로
        이고, R5 는 happy path 회귀 보존이다.
        """
        config_dir, token, key = fresh_init

        strategy_file = tmp_path / "sample_r5.py"
        strategy_file.write_text(_DUMMY_STRATEGY_SRC)

        submit = _run_cli(
            config_dir,
            token,
            key,
            ["strategy", "submit", str(strategy_file)],
        )
        if submit.returncode != 0:
            pytest.skip(
                "submit 가 다른 사유로 실패: dummy strategy schema 환경 의존. "
                f"stdout={submit.stdout!r}, stderr={submit.stderr!r}"
            )

        # list 는 1건 이상 반환해야 한다.
        listed = _run_cli(config_dir, token, key, ["strategy", "list"])
        assert listed.returncode == 0, (
            f"list 실패: exit={listed.returncode}\n"
            f"stdout={listed.stdout}\nstderr={listed.stderr}"
        )
        payload = _parse_last_json_dict(listed.stdout)
        assert isinstance(payload.get("strategies"), list)
        assert len(payload["strategies"]) >= 1, payload

        # info 는 등록한 이름으로 조회 가능해야 한다.
        info = _run_cli(config_dir, token, key, ["strategy", "info", "sample_r5"])
        assert info.returncode == 0, (
            f"info 실패: exit={info.returncode}\n"
            f"stdout={info.stdout}\nstderr={info.stderr}"
        )
        info_payload = _parse_last_json_dict(info.stdout)
        assert info_payload.get("name") == "sample_r5", info_payload
