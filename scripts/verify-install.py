#!/usr/bin/env python3
"""Ante 클린 설치 및 KIS 모의투자 E2E 검증 스크립트.

사용법:
    # 1단계: 클린 설치 + 부팅 검증 (장 시간 무관)
    python scripts/verify-install.py install

    # 2단계: KIS 조회 API 검증 (장 시간 무관)
    python scripts/verify-install.py query

    # 3단계: KIS 주문 API 검증 (장 시간 필요: 09:00-15:30)
    python scripts/verify-install.py order

    # 전체 실행
    python scripts/verify-install.py all

필수 조건:
    - config/secrets.env 에 KIS_APP_KEY, KIS_APP_SECRET 설정
    - config/system.toml 에 broker.account_no 설정
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

# 색상 출력
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


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
        "ante.web",
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


async def stage_query() -> bool:
    """KIS 모의투자 조회 API를 테스트한다 (장 시간 무관)."""
    log_step("Stage 2: KIS 조회 API 검증")

    # 프로젝트 루트에서 실행
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root / "src"))

    from ante.config import Config

    config = Config.load(config_dir=project_root / "config")

    broker_config = config.get("broker", {})
    app_key = config.get_secret("KIS_APP_KEY")
    app_secret = config.get_secret("KIS_APP_SECRET")
    account_no = broker_config.get("account_no", "")

    if not app_key or not app_secret:
        log_fail("KIS_APP_KEY / KIS_APP_SECRET 가 설정되지 않았습니다")
        log_info("config/secrets.env 파일을 확인하세요")
        return False

    if not account_no:
        log_fail("broker.account_no 가 설정되지 않았습니다")
        log_info("config/system.toml [broker] 섹션을 확인하세요")
        return False

    log_ok(f"설정 확인: app_key={app_key[:4]}****, account={account_no}")

    # KISAdapter 생성 + 연결
    from ante.broker import KISAdapter

    adapter_config = {
        "app_key": app_key,
        "app_secret": app_secret,
        "account_no": account_no,
        "is_paper": broker_config.get("is_paper", True),
        "commission_rate": broker_config.get("commission_rate", 0.00015),
        "sell_tax_rate": broker_config.get("sell_tax_rate", 0.0023),
    }

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
        balance = await adapter.get_balance()
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


async def stage_order() -> bool:
    """KIS 모의투자 주문 API를 테스트한다 (장 시간 필요: 09:00-15:30)."""
    log_step("Stage 3: KIS 주문 API 검증 (장 시간 필요)")

    import datetime

    now = datetime.datetime.now()
    if now.hour < 9 or now.hour >= 16:
        log_warn("현재 장 시간이 아닙니다 (09:00-15:30)")
        log_info("장 시간에 다시 실행해 주세요")
        return False

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root / "src"))

    from ante.config import Config

    config = Config.load(config_dir=project_root / "config")

    broker_config = config.get("broker", {})
    app_key = config.get_secret("KIS_APP_KEY")
    app_secret = config.get_secret("KIS_APP_SECRET")
    account_no = broker_config.get("account_no", "")

    from ante.broker import KISAdapter

    adapter_config = {
        "app_key": app_key,
        "app_secret": app_secret,
        "account_no": account_no,
        "is_paper": broker_config.get("is_paper", True),
        "commission_rate": broker_config.get("commission_rate", 0.00015),
        "sell_tax_rate": broker_config.get("sell_tax_rate", 0.0023),
    }

    if not adapter_config.get("is_paper", True):
        log_fail("실전투자 계좌로는 주문 검증을 수행할 수 없습니다")
        log_info("config/system.toml에서 is_paper = true 를 확인하세요")
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

사용법: python scripts/verify-install.py <stage>

  {CYAN}install{RESET}  Stage 1: 클린 설치 + 부팅 검증 (장 시간 무관)
  {CYAN}query{RESET}    Stage 2: KIS 조회 API 검증 (장 시간 무관)
  {CYAN}order{RESET}    Stage 3: KIS 주문 API 검증 (장 시간 필요 09:00-15:30)
  {CYAN}all{RESET}      전체 단계 실행
""")


def main() -> None:
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    stage = sys.argv[1]
    results: dict[str, bool] = {}

    if stage in ("install", "all"):
        results["install"] = stage_install()

    if stage in ("query", "all"):
        results["query"] = asyncio.run(stage_query())

    if stage in ("order", "all"):
        results["order"] = asyncio.run(stage_order())

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
