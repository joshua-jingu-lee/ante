"""SQL INSERT 문 출력기.

기존 시나리오 SQL 파일 포맷에 맞춰 INSERT 문을 생성한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tests.fixtures.seed.generators.trading import (
    TradingResult,
)
from tests.fixtures.seed.generators.treasury import (
    TreasurySnapshot,
)


@dataclass
class StrategyDef:
    """전략 정의."""

    strategy_id: str
    name: str
    version: str
    filepath: str
    status: str  # 'registered' | 'active' | 'inactive'
    registered_at: str  # datetime('now', '-N days') 형식 또는 절대 시간
    description: str
    author: str


@dataclass
class BotDef:
    """봇 정의."""

    bot_id: str
    name: str
    strategy_id: str
    bot_type: str  # 'live' | 'paper'
    status: str  # 'created' | 'running' | 'stopped' | 'error'
    created_at: str
    interval_seconds: int = 60
    symbols: list[str] | None = None


@dataclass
class MemberDef:
    """멤버 정의."""

    member_id: str
    member_type: str  # 'human' | 'agent'
    role: str  # 'master' | 'admin' | 'default'
    org: str
    name: str
    emoji: str
    status: str
    scopes: list[str]
    created_at: str


@dataclass
class EventLogDef:
    """이벤트 로그 정의."""

    event_id: str
    event_type: str
    timestamp: str
    payload: dict


def _sql_str(value: str | None) -> str:
    """SQL 문자열 이스케이프."""
    if value is None:
        return "NULL"
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _sql_val(value: float | int | str | None) -> str:
    """SQL 값 포맷."""
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return _sql_str(value)
    return str(value)


def write_scenario_sql(
    path: Path,
    scenario_name: str,
    strategies: list[StrategyDef],
    bots: list[BotDef],
    trading_results: dict[str, TradingResult],
    treasury: TreasurySnapshot,
    members: list[MemberDef],
    event_logs: list[EventLogDef] | None = None,
    seed: int = 0,
) -> None:
    """시나리오 SQL 파일을 생성한다."""
    lines: list[str] = []
    today = date.today().isoformat()

    lines.append(f"-- 시나리오: {scenario_name}")
    lines.append(f"-- 생성: generate_scenario.py (seed={seed})")
    lines.append(f"-- 생성일: {today}")
    lines.append("")

    # ── 전략 ──
    lines.append("-- ── 전략 ────────────────────────────────────────────")
    for s in strategies:
        config_json = json.dumps({"strategy_id": s.strategy_id}, ensure_ascii=False)
        lines.append(
            "INSERT INTO strategies (strategy_id, name, version, filepath, status, "
            "registered_at, description, author)"
        )
        lines.append(
            f"VALUES ({_sql_str(s.strategy_id)}, {_sql_str(s.name)}, "
            f"{_sql_str(s.version)}, {_sql_str(s.filepath)}, {_sql_str(s.status)}, "
            f"{_sql_str(s.registered_at)}, {_sql_str(s.description)}, "
            f"{_sql_str(s.author)});"
        )
        lines.append("")

    # ── 봇 ──
    lines.append("-- ── 봇 ──────────────────────────────────────────────")
    for b in bots:
        config = {
            "bot_id": b.bot_id,
            "strategy_id": b.strategy_id,
            "name": b.name,
            "bot_type": b.bot_type,
            "interval_seconds": b.interval_seconds,
        }
        if b.symbols:
            config["symbols"] = b.symbols
        config_json = json.dumps(config, ensure_ascii=False)
        lines.append(
            "INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, "
            "status, created_at)"
        )
        lines.append(
            f"VALUES ({_sql_str(b.bot_id)}, {_sql_str(b.name)}, "
            f"{_sql_str(b.strategy_id)}, {_sql_str(b.bot_type)}, "
            f"{_sql_str(config_json)}, {_sql_str(b.status)}, "
            f"{_sql_str(b.created_at)});"
        )
        lines.append("")

    # ── 거래 내역 ──
    total_trades = sum(len(r.trades) for r in trading_results.values())
    if total_trades > 0:
        lines.append(f"-- ── 거래 내역 ({total_trades}건) ────────────────────────")
        for bot_id, result in trading_results.items():
            if not result.trades:
                continue
            lines.append(f"-- {bot_id}: {len(result.trades)}건")
            for t in result.trades:
                lines.append(
                    "INSERT INTO trades (trade_id, bot_id, strategy_id, symbol, side, "
                    "quantity, price, status, commission, timestamp, created_at)"
                )
                lines.append(
                    f"VALUES ({_sql_str(t.trade_id)}, {_sql_str(t.bot_id)}, "
                    f"{_sql_str(t.strategy_id)}, {_sql_str(t.symbol)}, "
                    f"{_sql_str(t.side)}, {t.quantity}, {t.price}, "
                    f"{_sql_str(t.status)}, {t.commission}, "
                    f"{_sql_str(t.timestamp)}, {_sql_str(t.timestamp)});"
                )
            lines.append("")

    # ── 포지션 이력 ──
    total_ph = sum(len(r.position_history) for r in trading_results.values())
    if total_ph > 0:
        lines.append(f"-- ── 포지션 이력 ({total_ph}건) ──────────────────────")
        for bot_id, result in trading_results.items():
            if not result.position_history:
                continue
            for ph in result.position_history:
                lines.append(
                    "INSERT INTO position_history (bot_id, symbol, action, quantity, "
                    "price, pnl, timestamp, created_at)"
                )
                lines.append(
                    f"VALUES ({_sql_str(ph.bot_id)}, {_sql_str(ph.symbol)}, "
                    f"{_sql_str(ph.action)}, {ph.quantity}, {ph.price}, "
                    f"{ph.pnl}, {_sql_str(ph.timestamp)}, {_sql_str(ph.timestamp)});"
                )
            lines.append("")

    # ── 최종 포지션 ──
    total_pos = sum(len(r.final_positions) for r in trading_results.values())
    if total_pos > 0:
        lines.append(f"-- ── 최종 포지션 ({total_pos}건) ────────────────────")
        for bot_id, result in trading_results.items():
            for p in result.final_positions:
                lines.append(
                    "INSERT INTO positions (bot_id, symbol, quantity, avg_entry_price, "
                    "realized_pnl, updated_at)"
                )
                lines.append(
                    f"VALUES ({_sql_str(p.bot_id)}, {_sql_str(p.symbol)}, "
                    f"{p.quantity}, {p.avg_entry_price}, {p.realized_pnl}, "
                    f"{_sql_str(p.updated_at)});"
                )
        lines.append("")

    # ── 예산 ──
    if treasury.budgets:
        lines.append("-- ── 예산 ────────────────────────────────────────────")
        for b in treasury.budgets:
            lines.append(
                "INSERT INTO bot_budgets (bot_id, allocated, available, reserved, "
                "spent, returned)"
            )
            lines.append(
                f"VALUES ({_sql_str(b.bot_id)}, {b.allocated}, {b.available}, "
                f"{b.reserved}, {b.spent}, {b.returned});"
            )
        lines.append("")

    # ── Treasury 상태 ──
    lines.append("-- ── Treasury 상태 ────────────────────────────────────")
    lines.append(
        f"INSERT OR IGNORE INTO treasury_state (key, value) "
        f"VALUES ('account_balance', {treasury.account_balance});"
    )
    lines.append(
        f"INSERT OR IGNORE INTO treasury_state (key, value) "
        f"VALUES ('allocated', {treasury.allocated});"
    )
    lines.append(
        f"INSERT OR IGNORE INTO treasury_state (key, value) "
        f"VALUES ('unallocated', {treasury.unallocated});"
    )
    lines.append("")

    # ── 자금 변동 이력 ──
    if treasury.transactions:
        lines.append(
            f"-- ── 자금 변동 이력 ({len(treasury.transactions)}건) "
            f"────────────────────"
        )
        for tx in treasury.transactions:
            lines.append(
                "INSERT INTO treasury_transactions (bot_id, transaction_type, amount, "
                "description, created_at)"
            )
            lines.append(
                f"VALUES ({_sql_str(tx.bot_id)}, {_sql_str(tx.transaction_type)}, "
                f"{tx.amount}, {_sql_str(tx.description)}, "
                f"{_sql_str(tx.created_at)});"
            )
        lines.append("")

    # ── 이벤트 로그 ──
    if event_logs:
        lines.append(f"-- ── 이벤트 로그 ({len(event_logs)}건) ──────────────────")
        for ev in event_logs:
            payload_json = json.dumps(ev.payload, ensure_ascii=False)
            lines.append(
                "INSERT INTO event_log (event_id, event_type, timestamp, payload)"
            )
            lines.append(
                f"VALUES ({_sql_str(ev.event_id)}, {_sql_str(ev.event_type)}, "
                f"{_sql_str(ev.timestamp)}, {_sql_str(payload_json)});"
            )
        lines.append("")

    # ── 멤버 ──
    if members:
        lines.append("-- ── 멤버 ────────────────────────────────────────────")
        for m in members:
            scopes_json = json.dumps(m.scopes, ensure_ascii=False)
            lines.append(
                "INSERT OR IGNORE INTO members (member_id, type, role, org, name, "
                "emoji, status, scopes, created_at)"
            )
            lines.append(
                f"VALUES ({_sql_str(m.member_id)}, {_sql_str(m.member_type)}, "
                f"{_sql_str(m.role)}, {_sql_str(m.org)}, {_sql_str(m.name)}, "
                f"{_sql_str(m.emoji)}, {_sql_str(m.status)}, "
                f"{_sql_str(scopes_json)}, {_sql_str(m.created_at)});"
            )
        lines.append("")

    # 파일 쓰기
    path.write_text("\n".join(lines), encoding="utf-8")
