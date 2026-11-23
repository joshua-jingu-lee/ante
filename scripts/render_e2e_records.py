"""e2e 시나리오의 실행 기록 디렉터리를 마크다운 요약으로 낸다 (#2823).

CI의 ``test`` 잡은 e2e 단계 뒤에 이 스크립트의 출력을 잡의 요약
(``$GITHUB_STEP_SUMMARY``)에 붙인다. 기록이 없거나 깨졌으면 그 사실을 적고
exit 0이다 — 요약 단계가 잡의 결론을 바꾸지 않는다.

    python scripts/render_e2e_records.py "$RUNNER_TEMP/e2e-records"
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

RECORD_VERSION = 1
TITLE = "## e2e 시나리오 실행 기록"
OUTCOME_LABELS = {"passed": "통과", "failed": "실패", "skipped": "건너뜀"}


def _text(value: Any) -> str:
    """표의 칸에 넣을 수 있게 HTML로 이스케이프하고 ``|``·줄바꿈을 막는다."""
    escaped = html.escape(str(value), quote=True)
    return escaped.replace("|", "&#124;").replace("\n", " ")


def _number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "-"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def _optional(value: Any) -> str:
    return "-" if value is None else _text(value)


def _cli_steps(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in record["steps"] if s.get("kind") == "cli"]


def _call_count(step: dict[str, Any]) -> int:
    count = step.get("count")
    return count if isinstance(count, int) and count > 0 else 1


def _unexpected(step: dict[str, Any]) -> bool:
    """기대와 다르게 끝난 호출: 성공을 기대했는데 실패했거나 그 반대."""
    return bool(step.get("failed")) != bool(step.get("expect_failure"))


def load_records(record_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """읽은 기록(nodeid 순)과 읽지 못한 파일의 이름."""
    records: list[dict[str, Any]] = []
    broken: list[str] = []
    for path in sorted(record_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            broken.append(path.name)
            continue
        if (
            not isinstance(record, dict)
            or record.get("version") != RECORD_VERSION
            or not isinstance(record.get("nodeid"), str)
            or not isinstance(record.get("steps"), list)
            or not all(isinstance(s, dict) for s in record["steps"])
        ):
            broken.append(path.name)
            continue
        records.append(record)
    records.sort(key=lambda r: r["nodeid"])
    return records, broken


def _summary_rows(records: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 시나리오 | 결과 | 시간(초) | CLI 호출 | 실패한 호출 | 외부 접속 시도 |",
        "|---|---|---|---|---|---|",
    ]
    for record in records:
        cli = _cli_steps(record)
        outcome = record.get("outcome")
        label = OUTCOME_LABELS.get(str(outcome), _optional(outcome))
        lines.append(
            f"| <code>{_text(record['nodeid'])}</code> | {label}"
            f" | {_number(record.get('seconds'))}"
            f" | {sum(_call_count(s) for s in cli)}"
            f" | {sum(_call_count(s) for s in cli if _unexpected(s))}"
            f" | {_number(record.get('net_attempts'))} |"
        )
    return lines


def _step_row(index: int, step: dict[str, Any]) -> str:
    if step.get("kind") == "start":
        ready = step.get("ready_seconds")
        state = f"준비 {_number(ready)}초" if step.get("ok") else "준비 실패"
        return f"| {index} | 데몬 시작 | - | - | - | {state} |"
    args = step.get("args")
    words = args if isinstance(args, list) else []
    command = _text(" ".join(str(a) for a in words))
    count = _call_count(step)
    repeat = f" ×{count}" if count > 1 else ""
    mark = " (기대와 다름)" if _unexpected(step) else ""
    expected = " (실패 기대)" if step.get("expect_failure") else ""
    return (
        f"| {index} | <code>{command}</code>{repeat}{expected}{mark}"
        f" | {_optional(step.get('returncode'))}"
        f" | {_optional(step.get('status'))}"
        f" | {_optional(step.get('code'))}"
        f" | {_number(step.get('seconds'))} |"
    )


def _detail_block(record: dict[str, Any]) -> list[str]:
    outcome = record.get("outcome")
    label = OUTCOME_LABELS.get(str(outcome), _optional(outcome))
    lines = [
        "<details>",
        f"<summary><code>{_text(record['nodeid'])}</code> — {label}</summary>",
        "",
        "| # | 명령 | 종료 코드 | status | code | 시간(초) |",
        "|---|---|---|---|---|---|",
    ]
    lines += [_step_row(i, s) for i, s in enumerate(record["steps"], start=1)]
    lines += ["", "</details>", ""]
    return lines


def render(record_dir: Path) -> str:
    """기록 디렉터리를 마크다운으로. 디렉터리가 없어도 예외를 내지 않는다."""
    lines = [TITLE, ""]
    if not record_dir.is_dir():
        lines.append("기록이 없다(e2e 단계가 돌지 않았거나 기록을 남기지 못했다).")
        return "\n".join(lines) + "\n"
    records, broken = load_records(record_dir)
    if not records:
        lines.append("기록이 없다(기록 디렉터리가 비어 있다).")
    else:
        lines += _summary_rows(records)
        lines += ["", "시나리오별 호출(연속으로 같은 호출은 ×N 한 행):", ""]
        for record in records:
            lines += _detail_block(record)
    if broken:
        names = ", ".join(f"<code>{_text(n)}</code>" for n in broken)
        lines += ["", f"읽지 못한 기록 {len(broken)}개: {names}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("record_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(render(args.record_dir))
    except Exception as exc:
        sys.stdout.write(f"{TITLE}\n\n요약을 만들지 못했다({type(exc).__name__}).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
