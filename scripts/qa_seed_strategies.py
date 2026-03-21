"""QA 전략 레지스트리 시딩 스크립트.

strategies/ 디렉토리의 qa_*.py 전략 파일을 스캔하여
DB 레지스트리에 자동 등록한다. 이미 등록된 전략은 건너뛴다.

Usage::

    python scripts/qa_seed_strategies.py
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import logging
from pathlib import Path
from typing import Any

from ante.core.database import Database
from ante.strategy.base import StrategyMeta
from ante.strategy.registry import StrategyRegistry

logger = logging.getLogger(__name__)


def _extract_meta_from_file(filepath: Path) -> StrategyMeta | None:
    """AST를 파싱하여 전략 파일에서 StrategyMeta를 추출한다.

    런타임 import 없이 정적으로 메타데이터를 읽는다.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        logger.warning("구문 오류 — 건너뜀: %s", filepath)
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_strategy = any(
            (isinstance(base, ast.Name) and base.id == "Strategy")
            or (isinstance(base, ast.Attribute) and base.attr == "Strategy")
            for base in node.bases
        )
        if not is_strategy:
            continue

        for item in node.body:
            if isinstance(item, ast.Assign):
                targets = item.targets
                value = item.value
            elif isinstance(item, ast.AnnAssign):
                targets = [item.target]
                value = item.value
            else:
                continue

            for target in targets:
                if not isinstance(target, ast.Name) or target.id != "meta":
                    continue
                if not isinstance(value, ast.Call):
                    continue
                return _parse_strategy_meta_call(value)

    logger.warning("StrategyMeta를 찾을 수 없음 — 건너뜀: %s", filepath)
    return None


def _parse_strategy_meta_call(call: ast.Call) -> StrategyMeta:
    """ast.Call 노드에서 StrategyMeta 키워드 인자를 파싱."""
    kwargs: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            continue
        value = _eval_constant(kw.value)
        if value is not None:
            kwargs[kw.arg] = value
    return StrategyMeta(**kwargs)


def _eval_constant(node: ast.expr) -> Any:
    """AST 상수 노드를 Python 값으로 변환한다."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_eval_constant(elt) for elt in node.elts]
    return None


async def seed_strategies(strategies_dir: Path, db_path: str) -> int:
    """strategies_dir의 qa_*.py 파일을 DB에 등록한다.

    Returns:
        등록된 전략 수.
    """
    db = Database(db_path)
    await db.connect()

    try:
        registry = StrategyRegistry(db)
        await registry.initialize()

        strategy_files = sorted(strategies_dir.glob("qa_*.py"))
        if not strategy_files:
            logger.warning("시딩 대상 전략 파일 없음: %s", strategies_dir)
            return 0

        registered_count = 0
        for filepath in strategy_files:
            meta = _extract_meta_from_file(filepath)
            if meta is None:
                continue

            strategy_id = f"{meta.name}_v{meta.version}"
            if await registry.exists(strategy_id):
                logger.info("이미 등록됨 — 건너뜀: %s", strategy_id)
                continue

            try:
                await registry.register(filepath=filepath, meta=meta)
                registered_count += 1
                logger.info("전략 등록 완료: %s", strategy_id)
            except Exception:
                logger.exception("전략 등록 실패: %s", filepath.name)

        return registered_count
    finally:
        await db.close()


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="QA 전략 레지스트리 시딩")
    parser.add_argument(
        "--strategies-dir",
        type=Path,
        default=Path("strategies"),
        help="전략 파일 디렉토리 (기본: strategies/)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="db/ante.db",
        help="SQLite DB 경로 (기본: db/ante.db)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[qa-seed] %(message)s",
    )

    count = asyncio.run(seed_strategies(args.strategies_dir, args.db_path))
    logger.info("시딩 완료: %d개 전략 등록", count)


if __name__ == "__main__":
    main()
