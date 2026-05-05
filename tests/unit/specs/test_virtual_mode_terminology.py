"""paper/is_paper terminology guard (#1232)."""

from __future__ import annotations

import importlib.util
import re
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]

SEARCH_ROOTS = [
    REPO_ROOT / "docs" / "specs",
    REPO_ROOT / "docs" / "architecture",
    REPO_ROOT / "guide",
    REPO_ROOT / "scripts",
]

DISALLOWED_PATTERNS = [
    re.compile(r"--account-id\s+paper\b", re.IGNORECASE),
    re.compile(r"\(paper\)", re.IGNORECASE),
    re.compile(r"\bpaper/live\b", re.IGNORECASE),
    re.compile(r"\bpaper01\b", re.IGNORECASE),
    re.compile(r"config/system\.toml[^\n]*is_paper", re.IGNORECASE),
    re.compile(r"\bPaper(?:Executor|PortfolioView|OrderView)\b"),
    re.compile(r"\bpaper\.py\b"),
]


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        files.extend(
            p for p in root.rglob("*") if p.is_file() and p.suffix in {".md", ".py"}
        )
    return files


def _load_verify_install_module() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "verify-install.py"
    spec = importlib.util.spec_from_file_location("verify_install", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execution_mode_paper_residue_is_not_reintroduced() -> None:
    """실행 모드 용어로 보이는 paper 잔재는 docs/guide/scripts에 남기지 않는다."""
    violations: list[str] = []
    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8")
        for pattern in DISALLOWED_PATTERNS:
            if pattern.search(text):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {pattern.pattern}")

    assert violations == []


def test_verify_install_builds_kis_config_from_account() -> None:
    """verify-install은 Account.credentials/broker_config를 KIS config로 사용한다."""
    module = _load_verify_install_module()
    account = SimpleNamespace(
        exchange="KRX",
        trading_mode=SimpleNamespace(value="virtual"),
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
        credentials={
            "app_key": "app-key",
            "app_secret": "app-secret",
            "account_no": "5012345601",
        },
        broker_config={"is_paper": True},
    )

    adapter_config = module._kis_adapter_config_from_account(account)

    assert adapter_config == {
        "exchange": "KRX",
        "trading_mode": "virtual",
        "buy_commission_rate": 0.00015,
        "sell_commission_rate": 0.00195,
        "app_key": "app-key",
        "app_secret": "app-secret",
        "account_no": "5012345601",
        "is_paper": True,
    }


def test_verify_install_rejects_live_kis_endpoint() -> None:
    """KIS 실전투자 엔드포인트로는 설치 검증 query/order를 실행하지 않는다."""
    module = _load_verify_install_module()

    assert (
        module._guard_paper_endpoint(
            {"is_paper": False},
            account_id="domestic-live",
            action="조회 API",
        )
        is False
    )


def test_verify_install_checks_accounts_table_before_account_service(
    tmp_path: Path,
) -> None:
    """검증 스크립트는 빈 SQLite 파일을 Account DB로 오인하지 않는다."""
    module = _load_verify_install_module()
    db_path = tmp_path / "ante.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE accounts (account_id TEXT PRIMARY KEY)")

    assert module._account_table_exists(db_path) is True

    empty_db_path = tmp_path / "empty.db"
    with sqlite3.connect(empty_db_path):
        pass

    assert module._account_table_exists(empty_db_path) is False
