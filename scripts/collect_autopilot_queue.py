#!/usr/bin/env python3
"""Collect the /autopilot queue snapshot via the GitHub search API (#2538).

Prints a single JSON array of open issue candidates, each reduced to the
fields queue selection needs (number, title, label names, timestamps, URL,
body). The array is written once as UTF-8 without escaping non-ASCII text,
only after every page succeeded; on any failure stdout stays empty and the
process exits 1.

Limitation: pages are fetched separately, so the snapshot is not atomic. With
more than 100 candidates, issues opened, closed or relabelled during collection
may be missed or duplicated.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

EXCLUDED_LABELS = (
    "needs-triage",
    "question",
    "blocked",
    "blocked:review-loop",
    "blocked:pr-review-loop",
    "process",
    "epic",
)
PER_PAGE = 100
# GitHub search API returns at most 1,000 results per query.
SEARCH_RESULT_CAP = 1000
MAX_PAGES = SEARCH_RESULT_CAP // PER_PAGE
GH_TIMEOUT_SECONDS = 60


class QueueCollectError(RuntimeError):
    """Raised when the queue snapshot cannot be collected completely."""


def build_query(repo: str) -> str:
    excluded = " ".join(f"-label:{label}" for label in EXCLUDED_LABELS)
    return f"repo:{repo} is:issue is:open sort:created-asc {excluded}"


def _run_gh(args: list[str], label: str) -> str:
    try:
        completed = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError as exc:
        raise QueueCollectError(f"{label}: cannot run gh: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise QueueCollectError(f"{label}: timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise QueueCollectError(f"{label}: gh exited {completed.returncode}: {detail}")
    return completed.stdout


def resolve_repo() -> str:
    label = "gh repo view"
    output = _run_gh(["repo", "view", "--json", "nameWithOwner"], label)
    try:
        repo = json.loads(output)["nameWithOwner"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise QueueCollectError(f"{label}: unexpected output: {output!r}") from exc
    if not isinstance(repo, str) or not repo:
        raise QueueCollectError(f"{label}: unexpected output: {output!r}")
    return repo


def fetch_page(query: str, page: int) -> dict[str, Any]:
    label = f"gh api search/issues page {page}"
    output = _run_gh(
        [
            "api",
            "--method",
            "GET",
            "search/issues",
            "-f",
            f"q={query}",
            "-f",
            f"per_page={PER_PAGE}",
            "-f",
            f"page={page}",
        ],
        label,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise QueueCollectError(f"{label}: response is not JSON") from exc
    if not isinstance(payload, dict):
        raise QueueCollectError(f"{label}: response is not a JSON object")
    if "items" not in payload or not isinstance(payload["items"], list):
        raise QueueCollectError(f"{label}: response has no 'items' array")
    if payload.get("incomplete_results") is True:
        raise QueueCollectError(
            f"{label}: incomplete_results is true (search timed out)"
        )
    return payload


def slim_issue(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise QueueCollectError(f"search item is not an object: {item!r}")
    try:
        return {
            "number": item["number"],
            "title": item["title"],
            "labels": [label["name"] for label in item["labels"]],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "html_url": item["html_url"],
            "body": item["body"] or "",
        }
    except (KeyError, TypeError) as exc:
        raise QueueCollectError(
            f"search item #{item.get('number')} is missing field: {exc}"
        ) from exc


def collect(repo: str) -> list[dict[str, Any]]:
    query = build_query(repo)
    issues: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        payload = fetch_page(query, page)
        if page == 1:
            total = payload.get("total_count")
            if not isinstance(total, int) or isinstance(total, bool):
                raise QueueCollectError(
                    f"page 1: total_count missing or not an integer: {total!r}"
                )
            if total > SEARCH_RESULT_CAP:
                raise QueueCollectError(
                    f"total_count {total} exceeds the search API cap "
                    f"of {SEARCH_RESULT_CAP}; snapshot would be truncated"
                )
        batch = payload["items"]
        issues.extend(slim_issue(item) for item in batch)
        if len(batch) < PER_PAGE:
            break
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        help="owner/name to search (default: gh repo view of the current checkout)",
    )
    args = parser.parse_args(argv)

    try:
        repo = args.repo or resolve_repo()
        issues = collect(repo)
    except QueueCollectError as exc:
        print(f"collect_autopilot_queue: {exc}", file=sys.stderr)
        return 1

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(issues, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
