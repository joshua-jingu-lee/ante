"""Cross-module canonical exchange vocabulary 계약 회귀 (#1579).

per-surface 테스트(#1576/#1577/#1583/#1584/#1585 merged)를 보완하는
**cross-module 계약 회귀 + SSOT drift 가드**다. 에픽 #1561 최종 자식.

본 모듈의 불변식:
  1. ``ORACLE_INVALID_EXCHANGE`` 가 **모든 신규 입력 경계**(instrument CLI
     list/sync/import · StrategyMeta · account ``service.create()`` ·
     DataStore ``write``/``append`` · backtest ``run --exchange``)에서
     성공 처리되지 않는다(#1561 재현 통합 고정).
  2. ``*`` 는 **StrategyMeta 표면에서만** 허용되고 그 외 모든 신규 입력
     경계에서 거부된다.
  3. canonical 5종이 각 표면의 *exchange-vocabulary 게이트*(축 A)에서
     invalid-exchange로 거부되지 **않는다**.
  4. 표면 파생 집합이 SSOT(``ante.core.exchange``)에서 파생됨을 구조적으로
     고정한다(``validator.VALID_EXCHANGES`` 값 동등, ``store._KNOWN_EXCHANGES``
     identity).

**test-only — src/ante 무변경**. canonical 리터럴(KRX/NYSE/NASDAQ/AMEX/
TEST)은 테스트에 하드코딩하지 않고 전부 ``CANONICAL_EXCHANGES`` 를 import·
parametrize한다(테스트가 SSOT를 추종). 의도된 단일 상수
``ORACLE``/``"*"``/``"TEST"`` 만 리터럴로 둔다. 표면별 에러코드 문자열·
표면별 세부 거동·axis B(preset/source 가용성)·legacy out-of-vocab read
면제 재검증은 비목표(각 구현 이슈 per-surface 테스트 책임).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
import pytest_asyncio
from click.testing import CliRunner

from ante.account.errors import InvalidExchangeError
from ante.account.models import Account
from ante.account.service import AccountService
from ante.cli.main import cli
from ante.core.database import Database
from ante.core.exchange import (
    CANONICAL_EXCHANGES,
    STRATEGY_EXCHANGES,
    is_canonical,
    is_strategy_allowed,
)
from ante.data.store import ParquetStore
from ante.eventbus.bus import EventBus
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.validator import StrategyValidator

# 의도된 단일 상수만 리터럴로 둔다(canonical 집합은 SSOT import).
#  - ORACLE: #1561 oracle probe 시그니처(어떤 신규 입력 경계에서도 거부).
#  - WILDCARD: StrategyMeta 전용 — 그 외 표면에서 거부.
ORACLE = "ORACLE_INVALID_EXCHANGE"
WILDCARD = "*"

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


# ── 공유 fixture/헬퍼 (per-surface 테스트 패턴 재사용) ──────────────


@pytest.fixture(autouse=True)
def _isolated_cli_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """모든 CLI invoke를 tmp_path 기반 config-dir/db-path 로 격리.

    Codex branch review [P2]: ``runner`` fixture 가 인증만 mock 하면
    canonical ``instrument list``/``sync``/``import`` (및 config/db 에 닿는
    모든 CLI invoke)가 기본 ``get_config_dir()``(``~/.config/ante`` 또는
    repo ``config/``)·``config/db/ante.db`` 를 사용한다. CI ``pytest -n
    auto`` 다중 워커가 동일 SQLite db 를 공유해 lock/dirty tree flaky 가
    되고, dev 환경에 broker 설정이 있으면 ``sync --exchange KRX`` 가 실제
    KIS 어댑터까지 도달할 수 있다(이슈 Non-Goal "실 broker/API 호출 금지"
    위반).

    격리 방식은 per-surface 테스트
    (``tests/unit/cli/test_instrument_exchange_validation.py`` 의
    ``TestSyncKrxSourcePasses`` 가 ``--db-path str(tmp_path / ...)`` 를
    전달해 tmp db + broker 미설정 config-dir 로 KIS 어댑터 미도달을 의도한
    것)와 **동일한 격리**를 ``ante.cli.main`` 의 경로 resolver patch 로
    모든 invoke 에 일괄 적용한 것이다(명시 옵션 누락 없음):

      * ``get_config_dir`` → tmp config-dir (broker 설정 부재 →
        ``sync KRX`` 는 "브로커 설정이 없습니다" 경로, 어댑터 호출 전 단계).
      * ``get_db_path`` → tmp SQLite (워커별 ``tmp_path`` 격리, 공유 db 0).
      * ``get_data_path`` → tmp data dir (``data/`` cwd 상대 경로 격리).

    instrument/backtest 커맨드는 함수 내부에서
    ``from ante.cli.main import get_db_path`` 등을 import 하므로
    ``ante.cli.main`` 심볼 patch 가 그대로 전파된다(명시 옵션 미전달 시
    ``resolved_* = opt or get_*(ctx)`` 폴백이 tmp 로 고정).

    추가 안전망으로 ``ante.broker.kis.KISAdapter`` 를 stub 으로 교체해
    (격리가 어떤 경로로든 우회되어도) 실 네트워크/broker 호출이 0 임을
    이중 보장한다(canonical-sync 는 어댑터 도달 전 단계 단언이라 stub 으로
    충분 — 테스트 의미 불변).
    """
    cfg_dir = tmp_path / "cli_config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cli_db" / "ante.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "cli_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("ante.cli.main.get_config_dir", lambda ctx=None: cfg_dir)
    monkeypatch.setattr("ante.cli.main.get_db_path", lambda ctx=None: str(db_path))
    monkeypatch.setattr("ante.cli.main.get_data_path", lambda ctx=None: str(data_dir))

    class _StubKISAdapter:
        """실 KIS 호출 차단용 stub (canonical-sync 어댑터 도달 전 단계 단언)."""

        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError(
                "KIS 어댑터는 contract 테스트에서 호출되지 않아야 한다 "
                "(broker 미설정 격리로 어댑터 도달 전 차단)."
            )

    monkeypatch.setattr("ante.broker.kis.KISAdapter", _StubKISAdapter)
    yield


@pytest.fixture()
def runner() -> CliRunner:
    """인증을 mock으로 우회한 CliRunner.

    ``tests/unit/cli/test_instrument_exchange_validation.py`` /
    ``test_cli_backtest_exchange_validation.py`` 패턴 재사용.

    config-dir/db-path/data-path 격리는 autouse ``_isolated_cli_paths``
    fixture 가 모든 invoke 에 일괄 적용한다(per-surface 의 명시
    ``--db-path`` 패턴과 동등 효과, 누락 없음).
    """
    r = CliRunner(mix_stderr=False)
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


@pytest_asyncio.fixture
async def account_service(tmp_path: Path):
    """초기화된 AccountService (``tests/unit/test_account.py`` 패턴)."""
    database = Database(str(tmp_path / "contract_account.db"))
    await database.connect()
    svc = AccountService(database, EventBus())
    await svc.initialize()
    yield svc
    await database.close()


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    """tmp_path 기반 ParquetStore (``tests/unit/test_parquet_exchange.py`` 패턴)."""
    return ParquetStore(base_path=tmp_path)


def _make_account(account_id: str, exchange: str) -> Account:
    """test preset로 게이트 격리한 Account.

    ``broker_type="test"`` preset은 broker/credentials 게이트를 통과시키므로
    ``service.create()`` 가 실패한다면 그 원인은 exchange 게이트로 좁혀진다.
    account_id 는 ``RESTRICTED_NEW_ACCOUNT_IDS`` ("test") /
    ``INVALID_RUNTIME_ACCOUNT_IDS`` ("default") 바깥의 valid ID 를 쓴다.
    """
    return Account(
        account_id=account_id,
        name="contract",
        exchange=exchange,
        currency="KRW",
        broker_type="test",
        credentials={"app_key": "test", "app_secret": "test"},
    )


def _ohlcv_df(symbol: str = "005930") -> pl.DataFrame:
    """테스트용 OHLCV DataFrame (``test_parquet_exchange.py`` 패턴)."""
    base = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    return pl.DataFrame(
        {
            "timestamp": [base],
            "symbol": [symbol],
            "open": [50000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [1000000],
            "amount": [50000000000],
            "source": ["test"],
        }
    )


def _ohlcv_rows(symbol: str = "005930") -> list[dict]:
    """append() 용 OHLCV row 리스트."""
    return [
        {
            "timestamp": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            "symbol": symbol,
            "open": 50000.0,
            "high": 51000.0,
            "low": 49000.0,
            "close": 50500.0,
            "volume": 1000000,
            "amount": 50000000000,
            "source": "test",
        }
    ]


def _strategy_src(exchange: str) -> str:
    """``StrategyMeta(exchange=<value>)`` 를 가진 유효 전략 소스.

    exchange 외 요소(Strategy 상속·meta·on_step)는 모두 충족시켜
    ``ValidationResult.errors`` 의 차이가 exchange 게이트로만 좁혀지게 한다.
    """
    return (
        "from ante.strategy import Strategy, StrategyMeta\n\n"
        "class ContractStrategy(Strategy):\n"
        "    meta = StrategyMeta(\n"
        '        name="contract", version="1.0.0", description="contract",\n'
        f'        exchange="{exchange}",\n'
        "    )\n\n"
        "    async def on_step(self, context):\n"
        "        return []\n"
    )


def _validate_strategy(tmp_path: Path, exchange: str):
    """StrategyMeta 경계: 주어진 exchange 로 전략을 정적 검증한다."""
    filepath = tmp_path / "contract_strategy.py"
    filepath.write_text(_strategy_src(exchange))
    return StrategyValidator().validate(filepath)


def _has_exchange_error(result) -> bool:  # noqa: ANN001
    """ValidationResult 가 exchange-vocabulary 게이트로 invalid 거부했는지."""
    return (not result.valid) and any(
        "Invalid exchange value" in e for e in result.errors
    )


def _import_json(tmp_path: Path, exchange: str) -> Path:
    """invalid/canonical row 한 건을 담은 instrument import JSON 파일."""
    json_file = tmp_path / "instruments.json"
    json_file.write_text(json.dumps([{"symbol": "X", "exchange": exchange}]))
    return json_file


def _assert_not_classified_invalid_exchange(result) -> None:  # noqa: ANN001
    """instrument CLI 결과가 INSTRUMENT_INVALID_EXCHANGE 로 분류되지 않았음.

    canonical 은 vocabulary 게이트를 통과하므로 invalid-exchange envelope 가
    나오면 안 된다. 게이트 통과 후 source-bound(``sync``)·broker 설정 부재
    등 downstream 실패는 비-JSON stderr 경로일 수 있으므로(예: ``sync KRX``
    → "브로커 설정이 없습니다"), stdout 이 JSON 이면 ``code`` 가
    ``INSTRUMENT_INVALID_EXCHANGE`` 가 아님을, 비-JSON 이면 그 자체로
    invalid-exchange 미분류임을 확인한다(축 A; 전체 success·표면별 후속
    거동은 비목표).
    """
    out = result.stdout.strip()
    if out:
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            assert payload.get("code") != "INSTRUMENT_INVALID_EXCHANGE", out
    # 비-JSON / 빈 stdout: vocabulary 게이트 통과 후 downstream 경로 →
    # invalid-exchange 로 분류되지 않았음(축 A).
    assert "INSTRUMENT_INVALID_EXCHANGE" not in result.stdout


# ── TestCanonicalSetContract — SSOT 모듈 자체 불변식 ────────────────


class TestCanonicalSetContract:
    """``ante.core.exchange`` 계약 불변식(cross-module 전제)."""

    def test_canonical_exchanges_is_frozenset(self) -> None:
        assert isinstance(CANONICAL_EXCHANGES, frozenset)

    def test_strategy_exchanges_is_canonical_union_wildcard(self) -> None:
        assert STRATEGY_EXCHANGES == CANONICAL_EXCHANGES | {WILDCARD}

    def test_wildcard_is_not_canonical(self) -> None:
        assert is_canonical(WILDCARD) is False

    def test_wildcard_is_strategy_allowed(self) -> None:
        assert is_strategy_allowed(WILDCARD) is True

    def test_test_exchange_remains_canonical(self) -> None:
        """``TEST`` 는 테스트/fixture 용도로 계속 허용된다(검증 시나리오)."""
        assert "TEST" in CANONICAL_EXCHANGES


# ── TestOracleInvalidRejectionMatrix — #1561 재현 통합 고정 ─────────


class TestOracleInvalidRejectionMatrix:
    """``ORACLE`` 가 **모든 신규 입력 경계**에서 거부된다.

    표면별 에러코드 문자열 재검증은 비목표(per-surface 책임) — 여기서는
    "성공 처리되지 않음"(거부)만 cross-module 으로 고정한다.
    """

    def test_instrument_list_rejects_oracle(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["instrument", "list", "--exchange", ORACLE])
        assert result.exit_code != 0, result.stdout

    def test_instrument_sync_rejects_oracle(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["instrument", "sync", "--exchange", ORACLE])
        assert result.exit_code != 0, result.stdout

    def test_instrument_import_rejects_oracle(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            cli, ["instrument", "import", str(_import_json(tmp_path, ORACLE))]
        )
        assert result.exit_code != 0, result.stdout

    def test_strategy_meta_rejects_oracle(self, tmp_path: Path) -> None:
        assert _has_exchange_error(_validate_strategy(tmp_path, ORACLE))

    @pytest.mark.asyncio
    async def test_account_create_rejects_oracle(self, account_service) -> None:
        with pytest.raises(InvalidExchangeError):
            await account_service.create(_make_account("oracle-acct", ORACLE))

    def test_datastore_write_rejects_oracle(self, store: ParquetStore) -> None:
        with pytest.raises(ValueError, match="유효하지 않은 exchange"):
            store.write("005930", "1d", _ohlcv_df(), exchange=ORACLE)

    def test_datastore_append_rejects_oracle(self, store: ParquetStore) -> None:
        with pytest.raises(ValueError, match="유효하지 않은 exchange"):
            store.append("005930", "1m", _ohlcv_rows(), exchange=ORACLE)

    def test_backtest_run_rejects_oracle(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        strategy = tmp_path / "s.py"
        strategy.write_text("# dummy")
        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-01",
                "--exchange",
                ORACLE,
            ],
        )
        assert result.exit_code != 0, result.stdout


# ── TestWildcardRejectionMatrix — `*` 는 StrategyMeta 표면만 허용 ────


class TestWildcardRejectionMatrix:
    """``*`` 는 StrategyMeta 표면에서만 허용, 그 외 모두 거부."""

    def test_instrument_list_rejects_wildcard(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["instrument", "list", "--exchange", WILDCARD])
        assert result.exit_code != 0, result.stdout

    def test_instrument_sync_rejects_wildcard(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["instrument", "sync", "--exchange", WILDCARD])
        assert result.exit_code != 0, result.stdout

    def test_instrument_import_rejects_wildcard(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            cli, ["instrument", "import", str(_import_json(tmp_path, WILDCARD))]
        )
        assert result.exit_code != 0, result.stdout

    @pytest.mark.asyncio
    async def test_account_create_rejects_wildcard(self, account_service) -> None:
        with pytest.raises(InvalidExchangeError):
            await account_service.create(_make_account("wild-acct", WILDCARD))

    def test_datastore_write_rejects_wildcard(self, store: ParquetStore) -> None:
        with pytest.raises(ValueError, match="유효하지 않은 exchange"):
            store.write("005930", "1d", _ohlcv_df(), exchange=WILDCARD)

    def test_datastore_append_rejects_wildcard(self, store: ParquetStore) -> None:
        with pytest.raises(ValueError, match="유효하지 않은 exchange"):
            store.append("005930", "1m", _ohlcv_rows(), exchange=WILDCARD)

    def test_backtest_run_rejects_wildcard(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        strategy = tmp_path / "s.py"
        strategy.write_text("# dummy")
        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-01",
                "--exchange",
                WILDCARD,
            ],
        )
        assert result.exit_code != 0, result.stdout

    def test_strategy_meta_allows_wildcard(self, tmp_path: Path) -> None:
        """**StrategyMeta 만** ``*`` 허용 — exchange 게이트로 거부되지 않음."""
        assert not _has_exchange_error(_validate_strategy(tmp_path, WILDCARD))


# ── TestCanonicalAcceptanceMatrix — canonical 5종 게이트 통과(축 A) ──


class TestCanonicalAcceptanceMatrix:
    """canonical 각 값이 각 표면의 exchange-vocabulary 게이트에서
    invalid-exchange 로 거부되지 **않는다**(축 A).

    매트릭스를 ``sorted(CANONICAL_EXCHANGES)`` 로 parametrize 해 canonical
    집합 변경 시 검증 범위가 자동 추종한다(테스트 측 리터럴 하드코딩 0).
    axis B(preset/source 가용성)·표면별 후속 거동은 검증 대상이 아니다.
    """

    @pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
    def test_instrument_list_accepts_canonical(
        self, runner: CliRunner, exchange: str
    ) -> None:
        """core.md상 list 는 canonical 허용 표면 → INVALID_EXCHANGE 아님."""
        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "list", "--exchange", exchange],
        )
        _assert_not_classified_invalid_exchange(result)

    @pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
    def test_instrument_import_dry_run_accepts_canonical(
        self, runner: CliRunner, tmp_path: Path, exchange: str
    ) -> None:
        """core.md상 import 는 canonical 허용 표면 → INVALID_EXCHANGE 아님."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "instrument",
                "import",
                str(_import_json(tmp_path, exchange)),
                "--dry-run",
            ],
        )
        _assert_not_classified_invalid_exchange(result)

    @pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
    def test_instrument_sync_does_not_classify_canonical_as_invalid(
        self, runner: CliRunner, exchange: str
    ) -> None:
        """``sync`` 는 source-bound(KIS/KRX) — 전체 success 가 아니라
        "비-canonical 로 분류되지 않음"만 확인(전체 success 는 #1577 위임)."""
        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "sync", "--exchange", exchange],
        )
        _assert_not_classified_invalid_exchange(result)

    @pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
    @pytest.mark.asyncio
    async def test_account_create_accepts_canonical(
        self, account_service, exchange: str
    ) -> None:
        """test preset로 게이트 격리 → exchange 게이트만 통과 검증."""
        acct = await account_service.create(
            _make_account(f"acct-{exchange.lower()}", exchange)
        )
        assert acct.exchange == exchange

    @pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
    def test_datastore_write_accepts_canonical(
        self, store: ParquetStore, exchange: str
    ) -> None:
        store.write("005930", "1d", _ohlcv_df(), exchange=exchange)
        assert len(store.read("005930", "1d", exchange=exchange)) == 1

    @pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
    def test_backtest_run_does_not_reject_canonical(
        self, runner: CliRunner, tmp_path: Path, exchange: str
    ) -> None:
        """canonical override 는 BACKTEST_INVALID_EXCHANGE 아님(축 A)."""
        strategy = tmp_path / "s.py"
        strategy.write_text("# dummy")
        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            runner.invoke(
                cli,
                [
                    "backtest",
                    "run",
                    str(strategy),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-01",
                    "--exchange",
                    exchange,
                ],
            )
        # canonical 검증 통과 시에만 BacktestService 가 호출된다.
        mock_service.assert_called_once()

    @pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
    def test_strategy_meta_accepts_canonical(
        self, tmp_path: Path, exchange: str
    ) -> None:
        assert not _has_exchange_error(_validate_strategy(tmp_path, exchange))


# ── TestSsotDriftGuard — 표면 파생 집합의 SSOT 파생을 구조적 고정 ────


class TestSsotDriftGuard:
    """표면 파생 집합이 SSOT 에서 파생됨을 구조적으로 고정.

    equality/parametrize 는 "테스트가 SSOT 를 추종"을 보장할 뿐 "소비자
    코드의 중복 상수 0"을 증명하지는 않는다(과장 표현 금지). ``patch`` 로
    ``CANONICAL_EXCHANGES`` 모듈 상수를 교체하는 drift 테스트는 소비자
    import-time 이름 바인딩에 미전파되어 brittle/flaky 이므로 쓰지 않는다.
    """

    def test_strategy_validator_set_equals_strategy_exchanges(self) -> None:
        from ante.strategy.validator import VALID_EXCHANGES

        assert VALID_EXCHANGES == set(STRATEGY_EXCHANGES)

    def test_data_store_known_exchanges_is_canonical_identity(self) -> None:
        """identity 로 더 강하게 고정(값 동등보다 강함)."""
        from ante.data.store import _KNOWN_EXCHANGES

        assert _KNOWN_EXCHANGES is CANONICAL_EXCHANGES
