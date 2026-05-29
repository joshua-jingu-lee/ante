#!/usr/bin/env python3
"""*_SCHEMA 상수 파싱 기반 DB 스키마 문서 자동 생성/check.

src/ante/ 하위 모든 .py 파일에서 공식 DDL 상수인 *_SCHEMA를 찾고,
legacy 예외인 _CREATE_TABLE_SQL을 함께 파싱하여
docs/architecture/generated/db-schema.md를 생성한다.

SSOT: 모듈 소스 코드 내 DDL 상수 -> docs/architecture/generated/db-schema.md (자동 생성)

사용법:
    python scripts/generate_db_schema.py
    python scripts/generate_db_schema.py --output <path>
    python scripts/generate_db_schema.py --stdout
    python scripts/generate_db_schema.py --check

    <path> 기본값: docs/architecture/generated/db-schema.md
"""

from __future__ import annotations

import argparse
import ast
import difflib
import importlib.util
import re
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import TextIO

# ── 프로젝트 루트 ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src" / "ante"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "architecture" / "generated" / "db-schema.md"
KST = timezone(timedelta(hours=9))
LAST_UPDATED_RE = re.compile(r"^> 마지막 갱신: (?P<value>.+)$", re.MULTILINE)


def _load_import_guard():
    guard_path = PROJECT_ROOT / "scripts" / "check_import_path.py"
    spec = importlib.util.spec_from_file_location("check_import_path", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_current_worktree_import_path() -> None:
    guard = _load_import_guard()
    try:
        guard.check_import_path(PROJECT_ROOT)
    except guard.ImportPathCheckError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


# ── 테이블 설명 매핑 ──────────────────────────────────────────────────────

TABLE_DESCRIPTIONS: dict[str, str] = {
    "accounts": "계좌 등록 정보",
    "bots": "봇 등록 정보",
    "signal_keys": "봇별 시그널 키",
    "strategies": "전략 등록 정보",
    "trades": "체결 기록",
    "fill_outbox": "체결 이벤트 transactional outbox (#1949)",
    "positions": "현재 포지션",
    "position_history": "포지션 변동 이력",
    "bot_budgets": "봇별 예산",
    "treasury_transactions": "자금 트랜잭션 이력",
    "treasury_state": "계좌별 자산 상태",
    "treasury_daily_snapshots": "일간 자산 스냅샷",
    "order_registry": "주문 ID -> 봇 매핑",
    "dynamic_config": "동적 설정값",
    "dynamic_config_history": "동적 설정 변경 이력",
    "event_log": "이벤트 감사 로그",
    "backtest_runs": "백테스트 실행 이력",
    "reports": "전략 리포트",
    "approvals": "결재 요청",
    "members": "멤버 (사용자/에이전트) 등록 정보",
    "instruments": "종목 메타데이터",
    "sessions": "서버사이드 세션",
    "audit_log": "멤버 액션 감사 로그",
}

# ── 보존 정책 매핑 ──────────────────────────────────────────────────────

RETENTION_POLICIES: dict[str, str] = {
    "event_log": "30일 후 삭제",
    "position_history": "영구 보존",
    "trades": "영구 보존",
    "treasury_transactions": "영구 보존",
    "approvals": "영구 보존",
    "members": "영구 보존",
    "instruments": "영구 보존",
    "signal_keys": "영구 보존",
    "dynamic_config_history": "90일 후 삭제",
    "sessions": "만료 후 삭제",
    "audit_log": "영구 보존",
}

DEFAULT_RETENTION = "영구 보존"

# ── 논리적 ER 관계 (FK 없는 연관) ──────────────────────────────────────

LOGICAL_RELATIONS: list[tuple[str, str, str, str]] = [
    # (from_table, cardinality, to_table, label)
    ("accounts", "||--o{", "bots", "account_id"),
    ("bots", "||--o|", "signal_keys", "bot_id"),
    ("bots", "||--o{", "trades", "bot_id"),
    ("bots", "||--o{", "positions", "bot_id"),
    ("bots", "||--o{", "position_history", "bot_id"),
    ("bots", "||--||", "bot_budgets", "bot_id"),
    ("bots", "||--o{", "treasury_transactions", "bot_id"),
    ("bots", "||--o{", "order_registry", "bot_id"),
    ("strategies", "||--o{", "bots", "strategy_id"),
    ("strategies", "||--o{", "trades", "strategy_id"),
    ("strategies", "||--o{", "reports", "strategy_name"),
    ("dynamic_config", "||--o{", "dynamic_config_history", "key"),
    ("members", "||--o{", "sessions", "member_id"),
    ("members", "||--o{", "audit_log", "member_id"),
]


# ── AST 기반 스키마 상수 추출 ──────────────────────────────────────────

# 공식 *_SCHEMA 상수 + account 모듈의 legacy _CREATE_TABLE_SQL 예외
_SCHEMA_NAME_RE = re.compile(r"^[A-Z_]*SCHEMA$|^_CREATE_TABLE_SQL$")


def _extract_schema_constants(filepath: Path) -> list[tuple[str, str, str]]:
    """AST를 사용하여 파일에서 공식 스키마 상수를 추출한다.

    Returns:
        (상수명, DDL 문자열, 모듈 경로) 튜플 리스트
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    results: list[tuple[str, str, str]] = []
    # src/ante 이후 경로를 모듈명으로 변환
    try:
        rel = filepath.relative_to(SRC_DIR)
    except ValueError:
        return []
    module_path = str(rel.with_suffix("")).replace("/", ".")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if not _SCHEMA_NAME_RE.match(target.id):
                continue
            # 상수 값 추출
            value = _extract_string_value(node.value)
            if value and "CREATE TABLE" in value.upper():
                results.append((target.id, value, module_path))

    return results


def _extract_string_value(node: ast.expr) -> str | None:
    """AST 노드에서 문자열 리터럴 값을 추출한다."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # f-string은 지원하지 않음
        return None
    return None


# ── DDL 파싱 ──────────────────────────────────────────────────────────────

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+"
    r"ON\s+(\w+)\s*\(([^)]+)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_REFERENCES_RE = re.compile(
    r"REFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)",
    re.IGNORECASE,
)
_RETENTION_COMMENT_RE = re.compile(
    r"--\s*retention:\s*(\S+)",
    re.IGNORECASE,
)


def _module_name_from_path(module_path: str) -> str:
    """모듈 경로에서 최상위 모듈명을 추출한다.

    예: 'trade.recorder' -> 'trade'
    """
    return module_path.split(".")[0]


def _count_columns(body: str) -> int:
    """CREATE TABLE 본문에서 컬럼 수를 센다."""
    count = 0
    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        # CONSTRAINT, PRIMARY KEY(...), CHECK(...), FOREIGN KEY(...) 제외
        upper = line.upper().lstrip()
        if upper.startswith(("CONSTRAINT ", "PRIMARY KEY", "CHECK(", "FOREIGN KEY")):
            continue
        # 복합 PRIMARY KEY 같은 것
        if upper.startswith("PRIMARY KEY ("):
            continue
        if upper.startswith("UNIQUE(") or upper.startswith("UNIQUE ("):
            continue
        # 빈 괄호 닫기
        if upper in (")", ");"):
            continue
        # 컬럼 정의: 첫 토큰이 식별자
        tokens = line.split()
        if tokens and re.match(r"^[a-zA-Z_]\w*$", tokens[0]):
            count += 1
    return count


def _extract_fk_relations(ddl: str) -> list[tuple[str, str, str, str]]:
    """DDL에서 REFERENCES 절로부터 FK 관계를 추출한다."""
    relations: list[tuple[str, str, str, str]] = []
    for table_match in _CREATE_TABLE_RE.finditer(ddl):
        from_table = table_match.group(1)
        body = table_match.group(2)
        for ref_match in _REFERENCES_RE.finditer(body):
            to_table = ref_match.group(1)
            fk_col = ref_match.group(2)
            relations.append((from_table, "||--o{", to_table, fk_col))
    return relations


# ── 데이터 구조 ──────────────────────────────────────────────────────────


class TableInfo:
    """파싱된 테이블 정보."""

    def __init__(
        self,
        name: str,
        module: str,
        module_path: str,
        columns: int,
        ddl: str,
        description: str,
    ) -> None:
        self.name = name
        self.module = module
        self.module_path = module_path
        self.columns = columns
        self.ddl = ddl
        self.description = description


class IndexInfo:
    """파싱된 인덱스 정보."""

    def __init__(
        self,
        name: str,
        table: str,
        columns: str,
    ) -> None:
        self.name = name
        self.table = table
        self.columns = columns


# ── 스키마 수집 ──────────────────────────────────────────────────────────


def collect_schemas() -> tuple[list[TableInfo], list[IndexInfo], str]:
    """src/ante/ 하위에서 공식 스키마 상수를 수집하고 파싱한다.

    Returns:
        (테이블 리스트, 인덱스 리스트, 전체 DDL 문자열)
    """
    tables: list[TableInfo] = []
    indexes: list[IndexInfo] = []
    all_ddl_parts: list[str] = []

    # 모든 .py 파일 탐색
    py_files = sorted(SRC_DIR.rglob("*.py"))

    # 중복 방지 (동일 테이블이 여러 파일에 정의된 경우)
    seen_tables: set[str] = set()
    seen_indexes: set[str] = set()

    for py_file in py_files:
        constants = _extract_schema_constants(py_file)
        for _const_name, ddl_text, module_path in constants:
            module_name = _module_name_from_path(module_path)
            all_ddl_parts.append(ddl_text)

            # 테이블 파싱
            for m in _CREATE_TABLE_RE.finditer(ddl_text):
                table_name = m.group(1)
                if table_name in seen_tables:
                    continue
                seen_tables.add(table_name)
                body = m.group(2)
                col_count = _count_columns(body)
                # 전체 CREATE TABLE 문 추출 (DDL 블록용)
                full_ddl = m.group(0)
                desc = TABLE_DESCRIPTIONS.get(table_name, "")
                tables.append(
                    TableInfo(
                        name=table_name,
                        module=module_name,
                        module_path=module_path,
                        columns=col_count,
                        ddl=full_ddl,
                        description=desc,
                    )
                )

            # 인덱스 파싱
            for m in _CREATE_INDEX_RE.finditer(ddl_text):
                idx_name = m.group(1)
                if idx_name in seen_indexes:
                    continue
                seen_indexes.add(idx_name)
                idx_table = m.group(2)
                idx_cols = m.group(3).strip()
                indexes.append(
                    IndexInfo(name=idx_name, table=idx_table, columns=idx_cols)
                )

    all_ddl = "\n".join(all_ddl_parts)
    return tables, indexes, all_ddl


# ── Markdown 생성 ────────────────────────────────────────────────────────


def _write_header(
    out: TextIO,
    table_count: int,
    index_count: int,
    generated_at: str,
) -> None:
    """문서 헤더 및 통계 요약을 출력한다."""
    out.write("# Ante DB Schema Reference\n\n")
    out.write(
        "Ante 시스템의 전체 데이터베이스 스키마를 정리한 문서입니다. "
        "각 테이블의 DDL, 인덱스, ER 다이어그램, 보존 정책을 확인할 수 있습니다.\n\n"
    )
    out.write(
        "> 생성 명령: "
        "`PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py`\n"
    )
    out.write(
        "> Check 명령: "
        "`PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py --check`\n"
    )
    out.write(f"> 마지막 갱신: {generated_at}\n\n")
    out.write(f"- 테이블: **{table_count}**개\n")
    out.write(f"- 인덱스: **{index_count}**개\n\n")


def _write_toc(out: TextIO) -> None:
    """목차를 출력한다."""
    out.write("## 목차\n\n")
    out.write("- [ER 다이어그램](#er-다이어그램)\n")
    out.write("- [테이블 목록](#테이블-목록)\n")
    out.write("- [DDL](#ddl)\n")
    out.write("- [인덱스 목록](#인덱스-목록)\n")
    out.write("- [보존 정책](#보존-정책)\n\n")
    out.write("---\n\n")


def _write_er_diagram(
    out: TextIO,
    tables: list[TableInfo],
    all_ddl: str,
) -> None:
    """Mermaid ER 다이어그램을 출력한다."""
    out.write("## ER 다이어그램\n\n")
    out.write("```mermaid\nerDiagram\n")

    # 존재하는 테이블 이름 집합
    existing_tables = {t.name for t in tables}

    # DDL에서 FK 관계 추출
    fk_relations = _extract_fk_relations(all_ddl)

    # 논리적 관계와 FK 관계를 합침 (중복 제거)
    seen_relations: set[tuple[str, str]] = set()
    all_relations: list[tuple[str, str, str, str]] = []

    # 논리적 관계 먼저 (우선순위)
    for from_t, card, to_t, label in LOGICAL_RELATIONS:
        if from_t in existing_tables and to_t in existing_tables:
            key = (from_t, to_t)
            if key not in seen_relations:
                seen_relations.add(key)
                all_relations.append((from_t, card, to_t, label))

    # FK 관계 추가
    for from_t, card, to_t, label in fk_relations:
        key = (from_t, to_t)
        if key not in seen_relations:
            if from_t in existing_tables and to_t in existing_tables:
                seen_relations.add(key)
                all_relations.append((from_t, card, to_t, label))

    for from_t, card, to_t, label in all_relations:
        out.write(f'    {from_t} {card} {to_t} : "{label}"\n')

    out.write("```\n\n")


def _write_table_list(out: TextIO, tables: list[TableInfo]) -> None:
    """테이블 요약 표를 출력한다."""
    out.write("## 테이블 목록\n\n")
    out.write("| # | 테이블 | 모듈 | 설명 | 컬럼 수 |\n")
    out.write("|---|--------|------|------|---------|\n")

    for i, table in enumerate(tables, 1):
        anchor = table.name
        out.write(
            f"| {i} | [{table.name}](#{anchor}) | "
            f"`{table.module}` | {table.description} | {table.columns} |\n"
        )

    out.write("\n")


def _write_ddl(out: TextIO, tables: list[TableInfo], indexes: list[IndexInfo]) -> None:
    """테이블별 DDL 블록을 출력한다."""
    out.write("## DDL\n\n")

    # 인덱스를 테이블별로 그룹화
    idx_by_table: dict[str, list[IndexInfo]] = {}
    for idx in indexes:
        idx_by_table.setdefault(idx.table, []).append(idx)

    for table in tables:
        out.write(f"### {table.name}\n\n")
        out.write(f"모듈: `{table.module_path}`\n\n")
        out.write("```sql\n")
        out.write(table.ddl.strip())
        out.write("\n")

        # 관련 인덱스 출력
        table_indexes = idx_by_table.get(table.name, [])
        if table_indexes:
            out.write("\n")
            for idx in table_indexes:
                out.write(
                    f"CREATE INDEX IF NOT EXISTS {idx.name}\n"
                    f"    ON {idx.table}({idx.columns});\n"
                )

        out.write("```\n\n")


def _write_index_list(out: TextIO, indexes: list[IndexInfo]) -> None:
    """인덱스 목록을 출력한다."""
    out.write("## 인덱스 목록\n\n")
    out.write("| # | 인덱스명 | 테이블 | 컬럼 |\n")
    out.write("|---|----------|--------|------|\n")

    for i, idx in enumerate(indexes, 1):
        out.write(f"| {i} | `{idx.name}` | `{idx.table}` | `{idx.columns}` |\n")

    out.write("\n")


def _write_retention(out: TextIO, tables: list[TableInfo]) -> None:
    """보존 정책 표를 출력한다."""
    out.write("## 보존 정책\n\n")
    out.write("| 테이블 | 정책 |\n")
    out.write("|--------|------|\n")

    for table in tables:
        policy = RETENTION_POLICIES.get(table.name, DEFAULT_RETENTION)
        out.write(f"| `{table.name}` | {policy} |\n")

    out.write("\n")


# ── 메인 생성 함수 ──────────────────────────────────────────────────────


def generate_db_schema(
    out: TextIO,
    *,
    generated_at: str | None = None,
) -> tuple[int, int]:
    """DB 스키마 문서를 생성하고 (테이블 수, 인덱스 수)를 반환한다."""
    tables, indexes, all_ddl = collect_schemas()
    generated_at = generated_at or _today_kst()

    _write_header(out, len(tables), len(indexes), generated_at)
    _write_toc(out)
    _write_er_diagram(out, tables, all_ddl)
    _write_table_list(out, tables)
    _write_ddl(out, tables, indexes)
    _write_index_list(out, indexes)
    _write_retention(out, tables)

    return len(tables), len(indexes)


def render_db_schema(*, generated_at: str | None = None) -> tuple[str, int, int]:
    """DB 스키마 문서를 문자열로 생성한다."""
    out = StringIO()
    table_count, index_count = generate_db_schema(out, generated_at=generated_at)
    return out.getvalue(), table_count, index_count


def _today_kst() -> str:
    return datetime.now(tz=KST).strftime("%Y-%m-%d")


def _extract_last_updated(text: str) -> str | None:
    match = LAST_UPDATED_RE.search(text)
    if match is None:
        return None
    return match.group("value")


def _existing_or_today(output_path: Path) -> str:
    if output_path.exists():
        existing = _extract_last_updated(output_path.read_text(encoding="utf-8"))
        if existing:
            return existing
    return _today_kst()


def _print_diff_summary(current: str, expected: str, rel_output: Path) -> None:
    diff = list(
        difflib.unified_diff(
            current.splitlines(),
            expected.splitlines(),
            fromfile=f"a/{rel_output}",
            tofile=f"b/{rel_output}",
            lineterm="",
        )
    )
    max_lines = 120
    for line in diff[:max_lines]:
        print(line)
    if len(diff) > max_lines:
        print(f"... diff truncated ({len(diff) - max_lines} more lines)")


def _display_path(output_path: Path) -> Path:
    try:
        return output_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return output_path


def _check_output(output_path: Path, content: str) -> int:
    current = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    rel_output = _display_path(output_path)
    if current == content:
        print(f"{rel_output} is up to date.")
        return 0

    print(f"{rel_output} is stale.")
    print("Run: PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py")
    print()
    _print_diff_summary(current, content, rel_output)
    return 1


# ── CLI entrypoint ───────────────────────────────────────────────────────


def main() -> None:
    """스크립트 진입점."""
    _assert_current_worktree_import_path()
    parser = argparse.ArgumentParser(
        description="*_SCHEMA 상수 파싱 기반 DB 스키마 문서 자동 생성/check",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="출력 파일 경로 (기본: docs/architecture/generated/db-schema.md)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="파일 대신 stdout으로 출력",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="파일을 수정하지 않고 generated 문서가 최신인지 확인",
    )
    args = parser.parse_args()

    output_path = args.output
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    if args.stdout and args.check:
        parser.error("--stdout and --check cannot be used together")

    if args.stdout:
        table_count, index_count = generate_db_schema(sys.stdout)
        print(
            f"\n<!-- {table_count} tables, {index_count} indexes documented -->",
            file=sys.stderr,
        )
    elif args.check:
        content, _table_count, _index_count = render_db_schema(
            generated_at=_existing_or_today(output_path)
        )
        raise SystemExit(_check_output(output_path, content))
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as f:
            table_count, index_count = generate_db_schema(f)

        rel_output = _display_path(output_path)
        print(f"Generated {rel_output} ({table_count} tables, {index_count} indexes)")


if __name__ == "__main__":
    main()
