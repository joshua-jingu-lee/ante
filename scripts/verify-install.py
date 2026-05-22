#!/usr/bin/env python3
"""Ante 클린 설치 및 KIS 모의투자 E2E 검증 스크립트.

사용법:
    # 1단계: 클린 설치 + 부팅 검증 (장 시간 무관)
    python scripts/verify-install.py install

    # 2단계: KIS 조회 API 검증 (장 시간 무관)
    python scripts/verify-install.py query [account_id]

    # 3단계: KIS 주문 API 검증 (장 시간 필요: 09:00-15:30)
    python scripts/verify-install.py order [account_id]

    # 전체 실행
    python scripts/verify-install.py all [account_id]

필수 조건:
    - `ante account create`로 등록된 KIS 국내 계좌
    - KIS 조회/주문 검증은 해당 계좌의 broker_config.is_paper=true 필요
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

# 색상 출력
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

DEFAULT_VERIFY_ACCOUNT_ID = "domestic-demo"
KIS_REQUIRED_CREDENTIALS = ("app_key", "app_secret", "account_no")


def _assert_python_313() -> None:
    """Ante는 CPython 3.13 단일 런타임만 지원한다.

    이 가드는 verify-install.py 진입 시 첫 호출되어, 사용자의 로컬 ``python3``가
    공식 런타임과 다른 버전이면 즉시 fail-fast로 종료한다. 3.13의 모든 patch
    버전(3.13.0, 3.13.1, …)에서는 통과한다.
    """
    if sys.version_info < (3, 13) or sys.version_info >= (3, 14):
        print(
            f"{RED}{BOLD}Ante는 Python 3.13 단일 런타임만 지원합니다 "
            f"(현재: {sys.version}).{RESET}\n"
            f"  python3.13 -m venv .venv && source .venv/bin/activate "
            f'&& pip install -e ".[dev]"'
        )
        sys.exit(1)


def log_step(msg: str) -> None:
    print(f"\n{CYAN}{BOLD}▶ {msg}{RESET}")


def log_ok(msg: str) -> None:
    print(f"  {GREEN}✓ {msg}{RESET}")


def log_fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


def log_warn(msg: str) -> None:
    print(f"  {YELLOW}⚠ {msg}{RESET}")


def log_info(msg: str) -> None:
    print(f"  {msg}")


def _ensure_src_path(project_root: Path) -> None:
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def _load_import_guard(project_root: Path):
    guard_path = project_root / "scripts" / "check_import_path.py"
    spec = importlib.util.spec_from_file_location("check_import_path", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_current_worktree_import_path(project_root: Path) -> None:
    guard = _load_import_guard(project_root)
    try:
        guard.check_import_path(project_root)
    except guard.ImportPathCheckError as exc:
        log_fail(str(exc))
        raise SystemExit(1) from exc


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _mask_secret(value: Any, *, visible: int = 4) -> str:
    text = str(value)
    if not text:
        return "****"
    return f"{text[:visible]}****"


def _kis_adapter_config_from_account(account: Any) -> dict[str, Any]:
    return {
        "exchange": account.exchange,
        "trading_mode": _enum_value(account.trading_mode),
        "buy_commission_rate": float(account.buy_commission_rate),
        "sell_commission_rate": float(account.sell_commission_rate),
        **account.credentials,
        **account.broker_config,
    }


def _is_paper_endpoint(adapter_config: dict[str, Any]) -> bool:
    return bool(adapter_config.get("is_paper", True))


def _guard_paper_endpoint(
    adapter_config: dict[str, Any],
    *,
    account_id: str,
    action: str,
) -> bool:
    if _is_paper_endpoint(adapter_config):
        return True
    log_fail(f"실전투자 엔드포인트 계좌로는 {action} 검증을 수행할 수 없습니다")
    log_info(f"account_id={account_id}의 broker_config.is_paper=true 여부를 확인하세요")
    return False


def _account_table_exists(db_path: Path) -> bool:
    try:
        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'accounts'"
            ).fetchone()
    except sqlite3.Error as e:
        log_fail(f"Account DB 확인 실패: {e}")
        return False
    return row is not None


def _print_account_create_hint(account_id: str) -> None:
    log_info("서버를 정지한 뒤 아래 형식으로 검증 계좌를 먼저 등록하세요:")
    log_info(
        "ante account create --broker-type kis-domestic "
        f'--account-id {account_id} --name "국내 모의투자" '
        "--trading-mode virtual "
        "--credential-env app_key=KIS_PAPER_APP_KEY "
        "--credential-env app_secret=KIS_PAPER_APP_SECRET "
        "--credential account_no=5012XXXX-01 "
        "--broker-config is_paper=true"
    )


async def _load_kis_adapter_config(account_id: str) -> dict[str, Any] | None:
    project_root = Path(__file__).resolve().parent.parent
    _assert_current_worktree_import_path(project_root)
    _ensure_src_path(project_root)

    from ante.account import AccountNotFoundError, AccountService
    from ante.config import Config
    from ante.core import Database
    from ante.eventbus import EventBus

    config = Config.load(config_dir=project_root / "config")
    db_path = config.resolve_path("db.path", "db/ante.db")
    if not db_path.exists():
        log_fail(f"Account DB를 찾을 수 없습니다: {db_path}")
        _print_account_create_hint(account_id)
        return None
    if not _account_table_exists(db_path):
        log_fail(f"Account DB에 accounts 테이블이 없습니다: {db_path}")
        _print_account_create_hint(account_id)
        return None

    db = Database(str(db_path))
    await db.connect()
    try:
        account_service = AccountService(db=db, eventbus=EventBus(history_size=100))
        await account_service.initialize()
        try:
            account = await account_service.get(account_id)
        except AccountNotFoundError:
            log_fail(f"검증 계좌를 찾을 수 없습니다: account_id={account_id}")
            _print_account_create_hint(account_id)
            return None

        if account.broker_type != "kis-domestic":
            log_fail(
                "KIS 검증은 kis-domestic 계좌만 지원합니다: "
                f"account_id={account.account_id}, broker_type={account.broker_type}"
            )
            return None

        adapter_config = _kis_adapter_config_from_account(account)
        missing = [
            key for key in KIS_REQUIRED_CREDENTIALS if not adapter_config.get(key)
        ]
        if missing:
            log_fail(
                "KIS 계좌 credential이 부족합니다: "
                f"account_id={account.account_id}, missing={', '.join(missing)}"
            )
            _print_account_create_hint(account.account_id)
            return None

        log_ok(
            "계좌 설정 확인: "
            f"account_id={account.account_id}, "
            f"trading_mode={_enum_value(account.trading_mode)}, "
            f"is_paper={_is_paper_endpoint(adapter_config)}, "
            f"account={_mask_secret(adapter_config['account_no'])}"
        )
        return adapter_config
    finally:
        await db.close()


# ── Stage 1: 클린 설치 + 부팅 ─────────────────────────


def stage_install() -> bool:
    """클린 디렉토리에 Ante를 설치하고 import 가능 여부를 확인한다."""
    log_step("Stage 1: 클린 설치 검증")

    project_root = Path(__file__).resolve().parent.parent
    install_dir = Path("/tmp/ante-verify")

    # 기존 검증 디렉토리 정리
    if install_dir.exists():
        log_info(f"기존 디렉토리 삭제: {install_dir}")
        shutil.rmtree(install_dir)

    install_dir.mkdir(parents=True)
    log_info(f"설치 디렉토리: {install_dir}")

    ok = True

    # 1-1. venv 생성
    log_info("가상환경 생성 중...")
    venv_dir = install_dir / ".venv"
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log_fail(f"venv 생성 실패: {result.stderr}")
        return False
    log_ok("venv 생성 완료")

    pip = str(venv_dir / "bin" / "pip")
    python = str(venv_dir / "bin" / "python")

    # 1-2. pip install ante
    log_info("Ante 패키지 설치 중...")
    result = subprocess.run(
        [pip, "install", str(project_root)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        log_fail(f"pip install 실패:\n{result.stderr[-500:]}")
        return False
    log_ok("pip install 성공")

    # 1-3. 핵심 모듈 import 확인
    modules_to_check = [
        "ante.config",
        "ante.eventbus",
        "ante.strategy",
        "ante.rule",
        "ante.treasury",
        "ante.bot",
        "ante.broker",
        "ante.broker.kis",
        "ante.gateway",
        "ante.trade",
        "ante.data",
        "ante.backtest",
        "ante.report",
        "ante.notification",
    ]

    log_info("모듈 import 확인 중...")
    for mod in modules_to_check:
        result = subprocess.run(
            [python, "-c", f"import {mod}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log_fail(f"import {mod} 실패: {result.stderr.strip()}")
            ok = False
        else:
            log_ok(f"import {mod}")

    # 1-4. config 파일 복사 + 부팅 테스트 (Ctrl+C로 즉시 종료)
    log_info("설정 파일 복사 중...")
    config_dest = install_dir / "config"
    config_dest.mkdir()

    # system.toml
    toml_example = project_root / "config" / "system.toml.example"
    toml_dest = config_dest / "system.toml"
    if toml_example.exists():
        shutil.copy2(toml_example, toml_dest)
        log_ok("system.toml.example → system.toml")
    else:
        log_warn("system.toml.example 없음 — 기본값으로 부팅 시도")

    # secrets.env (실제 키가 있으면 복사)
    env_source = project_root / "config" / "secrets.env"
    if env_source.exists():
        shutil.copy2(env_source, config_dest / "secrets.env")
        log_ok("secrets.env 복사 완료 (실제 키 사용)")
    else:
        log_warn("secrets.env 없음 — 브로커 없이 부팅 테스트")

    # 1-5. 부팅 테스트 (3초 후 SIGINT)
    log_info("부팅 테스트 (3초 후 자동 종료)...")
    src_path = project_root / "src"
    boot_script = f"""
import asyncio, signal, sys, os
os.chdir("{install_dir}")
sys.path.insert(0, "{src_path}")

async def boot_test():
    from ante.config import Config
    from ante.core import Database
    from ante.eventbus import EventBus
    from pathlib import Path

    config = Config.load(config_dir=Path("config"))
    config.validate()
    print("CONFIG_OK")

    db_path = config.get("db.path", "db/ante.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    await db.connect()
    print("DB_OK")

    eventbus = EventBus(history_size=100)
    print("EVENTBUS_OK")

    await db.close()
    print("BOOT_OK")

asyncio.run(boot_test())
"""
    result = subprocess.run(
        [python, "-c", boot_script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(install_dir),
    )
    output = result.stdout
    if "BOOT_OK" in output:
        log_ok("부팅 테스트 성공 (Config → DB → EventBus)")
    else:
        log_fail(f"부팅 테스트 실패:\n{result.stderr[-500:]}")
        ok = False

    if ok:
        log_ok("Stage 1 완료: 클린 설치 검증 통과")
    else:
        log_fail("Stage 1 실패: 일부 항목에서 오류 발생")
    return ok


# ── Stage 2: KIS 조회 API 검증 ────────────────────────


async def stage_query(account_id: str) -> bool:
    """KIS 모의투자 조회 API를 테스트한다 (장 시간 무관)."""
    log_step(f"Stage 2: KIS 조회 API 검증 (account_id={account_id})")

    adapter_config = await _load_kis_adapter_config(account_id)
    if adapter_config is None:
        return False
    if not _guard_paper_endpoint(
        adapter_config,
        account_id=account_id,
        action="조회 API",
    ):
        return False

    # KISAdapter 생성 + 연결
    from ante.broker import KISAdapter

    adapter = KISAdapter(config=adapter_config)
    ok = True

    # 2-1. 인증 (토큰 발급)
    log_info("KIS 인증 (OAuth 토큰 발급)...")
    try:
        await adapter.connect()
        if adapter.access_token:
            log_ok(f"토큰 발급 성공: {adapter.access_token[:10]}...")
        else:
            log_fail("토큰이 비어 있음")
            ok = False
    except Exception as e:
        log_fail(f"인증 실패: {e}")
        return False

    # 2-2. 계좌 잔고 조회
    log_info("계좌 잔고 조회...")
    try:
        balance = await adapter.get_account_balance()
        log_ok(f"잔고 조회 성공: {balance}")
    except Exception as e:
        log_fail(f"잔고 조회 실패: {e}")
        ok = False

    # 2-3. 보유 포지션 조회
    log_info("보유 포지션 조회...")
    try:
        positions = await adapter.get_positions()
        log_ok(f"포지션 조회 성공: {len(positions)}건")
        for pos in positions[:5]:
            log_info(f"    {pos}")
    except Exception as e:
        log_fail(f"포지션 조회 실패: {e}")
        ok = False

    # 2-4. 현재가 조회 (삼성전자 005930)
    log_info("현재가 조회 (005930 삼성전자)...")
    try:
        price = await adapter.get_current_price("005930")
        log_ok(f"현재가 조회 성공: {price}")
    except Exception as e:
        log_fail(f"현재가 조회 실패: {e}")
        ok = False

    # 2-5. 종목 마스터 조회
    log_info("종목 마스터 조회...")
    try:
        instruments = await adapter.get_instruments()
        log_ok(f"종목 마스터 조회 성공: {len(instruments)}건")
        if instruments:
            sample = instruments[:3]
            for inst in sample:
                log_info(f"    {inst.get('symbol', '?')} {inst.get('name', '?')}")
    except Exception as e:
        log_fail(f"종목 마스터 조회 실패: {e}")
        ok = False

    # 정리
    try:
        await adapter.disconnect()
    except Exception:
        pass

    if ok:
        log_ok("Stage 2 완료: KIS 조회 API 검증 통과")
    else:
        log_fail("Stage 2 실패: 일부 API에서 오류 발생")
    return ok


# ── Stage 3: KIS 주문 API 검증 ────────────────────────


async def stage_order(account_id: str) -> bool:
    """KIS 모의투자 주문 API를 테스트한다 (장 시간 필요: 09:00-15:30)."""
    log_step(f"Stage 3: KIS 주문 API 검증 (account_id={account_id}, 장 시간 필요)")

    import datetime

    now = datetime.datetime.now()
    if now.hour < 9 or now.hour >= 16:
        log_warn("현재 장 시간이 아닙니다 (09:00-15:30)")
        log_info("장 시간에 다시 실행해 주세요")
        return False

    adapter_config = await _load_kis_adapter_config(account_id)
    if adapter_config is None:
        return False

    from ante.broker import KISAdapter

    if not _guard_paper_endpoint(
        adapter_config,
        account_id=account_id,
        action="주문 API",
    ):
        return False

    adapter = KISAdapter(config=adapter_config)
    ok = True

    try:
        await adapter.connect()
        log_ok("KIS 인증 성공")
    except Exception as e:
        log_fail(f"인증 실패: {e}")
        return False

    # 3-1. 시장가 매수 (소액 ETF: KODEX 200 — 069500)
    test_symbol = "069500"  # KODEX 200
    test_qty = 1

    log_info(f"시장가 매수 테스트 ({test_symbol} x {test_qty})...")
    buy_order_id = None
    try:
        buy_order_id = await adapter.submit_order(
            symbol=test_symbol,
            side="buy",
            quantity=test_qty,
            order_type="market",
        )
        log_ok(f"시장가 매수 주문 성공: order_id={buy_order_id}")
    except Exception as e:
        log_fail(f"시장가 매수 실패: {e}")
        ok = False

    # 잠시 대기 (체결 확인)
    if buy_order_id:
        await asyncio.sleep(2)
        log_info("주문 상태 조회...")
        try:
            status = await adapter.get_order_status(buy_order_id)
            log_ok(f"주문 상태: {status}")
        except Exception as e:
            log_fail(f"주문 상태 조회 실패: {e}")
            ok = False

    # 3-2. 지정가 매수 + 취소
    log_info(f"지정가 매수 + 취소 테스트 ({test_symbol})...")
    try:
        # 현재가 대비 낮은 가격으로 지정가 주문 (체결 안 되게)
        price = await adapter.get_current_price(test_symbol)
        limit_price = int(price * 0.9)  # 10% 낮은 가격

        limit_order_id = await adapter.submit_order(
            symbol=test_symbol,
            side="buy",
            quantity=1,
            order_type="limit",
            price=limit_price,
        )
        log_ok(f"지정가 매수 주문 성공: order_id={limit_order_id}, price={limit_price}")

        await asyncio.sleep(1)

        # 취소
        await adapter.cancel_order(limit_order_id)
        log_ok("주문 취소 성공")
    except Exception as e:
        log_fail(f"지정가 매수/취소 실패: {e}")
        ok = False

    # 3-3. 매도 (3-1에서 매수한 물량)
    if buy_order_id:
        log_info(f"시장가 매도 테스트 ({test_symbol} x {test_qty})...")
        await asyncio.sleep(2)
        try:
            sell_order_id = await adapter.submit_order(
                symbol=test_symbol,
                side="sell",
                quantity=test_qty,
                order_type="market",
            )
            log_ok(f"시장가 매도 주문 성공: order_id={sell_order_id}")
        except Exception as e:
            log_fail(f"시장가 매도 실패: {e}")
            ok = False

    try:
        await adapter.disconnect()
    except Exception:
        pass

    if ok:
        log_ok("Stage 3 완료: KIS 주문 API 검증 통과")
    else:
        log_fail("Stage 3 실패: 일부 주문에서 오류 발생")
    return ok


# ── CLI ────────────────────────────────────────────────


def print_usage() -> None:
    print(f"""
{BOLD}Ante E2E 검증 스크립트{RESET}

사용법: python scripts/verify-install.py <stage> [account_id]

  {CYAN}install{RESET}  Stage 1: 클린 설치 + 부팅 검증 (장 시간 무관)
  {CYAN}query{RESET}    Stage 2: KIS 조회 API 검증 (장 시간 무관)
  {CYAN}order{RESET}    Stage 3: KIS 주문 API 검증 (장 시간 필요 09:00-15:30)
  {CYAN}all{RESET}      전체 단계 실행

account_id 기본값: {DEFAULT_VERIFY_ACCOUNT_ID}
query/order/all은 `ante account create`로 등록된 kis-domestic 계좌를 사용합니다.
query/order는 해당 계좌의 broker_config.is_paper=true일 때만 실행합니다.
""")


def main() -> None:
    _assert_python_313()

    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print_usage()
        sys.exit(1)

    stage = sys.argv[1]
    account_id = sys.argv[2] if len(sys.argv) == 3 else DEFAULT_VERIFY_ACCOUNT_ID
    results: dict[str, bool] = {}

    if stage == "install" and len(sys.argv) == 3:
        print_usage()
        sys.exit(1)

    if stage in ("install", "all"):
        results["install"] = stage_install()

    if stage in ("query", "all"):
        results["query"] = asyncio.run(stage_query(account_id))

    if stage in ("order", "all"):
        results["order"] = asyncio.run(stage_order(account_id))

    if stage not in ("install", "query", "order", "all"):
        print_usage()
        sys.exit(1)

    # 결과 요약
    print(f"\n{BOLD}{'=' * 50}{RESET}")
    print(f"{BOLD}검증 결과 요약{RESET}")
    print(f"{'=' * 50}")
    for name, passed in results.items():
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  Stage {name}: {status}")

    all_passed = all(results.values())
    print(f"{'=' * 50}")
    if all_passed:
        print(f"{GREEN}{BOLD}모든 검증 통과{RESET}")
    else:
        print(f"{RED}{BOLD}일부 검증 실패{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
