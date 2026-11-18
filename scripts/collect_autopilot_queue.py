#!/usr/bin/env python3
"""Collect the /autopilot queue snapshot via the GitHub search API (#2538).

Prints a single JSON array that merges the ``items`` of every search page.
The array is written once, only after every page succeeded; on any failure
stdout stays empty and the process exits 1.
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
MAX_PAGES = 10
# GitHub search API returns at most 1,000 results per query.
SEARCH_RESULT_CAP = 1000
GH_TIMEOUT_SECONDS = 60


class QueueCollectError(RuntimeError):
    """Raised when the queue snapshot cannot be collected completely."""


def build_query(repo: str) -> str:
    excluded = " ".join(f"-label:{label}" for label in EXCLUDED_LABELS)
    return f"repo:{repo} is:issue is:open sort:created-asc {excluded}"


def _run_gh(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise QueueCollectError("gh executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise QueueCollectError(f"gh {' '.join(args[:2])} timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise QueueCollectError(
            f"gh {' '.join(args[:2])} exited {completed.returncode}: {detail}"
        )
    return completed.stdout


def resolve_repo() -> str:
    output = _run_gh(["repo", "view", "--json", "nameWithOwner"])
    try:
        repo = json.loads(output)["nameWithOwner"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise QueueCollectError(f"unexpected gh repo view output: {output!r}") from exc
    if not isinstance(repo, str) or not repo:
        raise QueueCollectError(f"unexpected gh repo view output: {output!r}")
    return repo


def fetch_page(query: str, page: int) -> dict[str, Any]:
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
        ]
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise QueueCollectError(f"page {page}: response is not JSON") from exc
    if not isinstance(payload, dict):
        raise QueueCollectError(f"page {page}: response is not a JSON object")
    if "items" not in payload or not isinstance(payload["items"], list):
        raise QueueCollectError(f"page {page}: response has no 'items' array")
    if payload.get("incomplete_results") is True:
        raise QueueCollectError(
            f"page {page}: incomplete_results is true (search timed out)"
        )
    return payload


def collect(repo: str) -> list[Any]:
    query = build_query(repo)
    items: list[Any] = []
    for page in range(1, MAX_PAGES + 1):
        payload = fetch_page(query, page)
        if page == 1:
            total = payload.get("total_count")
            if isinstance(total, int) and total > SEARCH_RESULT_CAP:
                raise QueueCollectError(
                    f"total_count {total} exceeds the search API cap "
                    f"of {SEARCH_RESULT_CAP}; snapshot would be truncated"
                )
        batch = payload["items"]
        if not batch:
            break
        items.extend(batch)
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        help="owner/name to search (default: gh repo view of the current checkout)",
    )
    args = parser.parse_args(argv)

    try:
        repo = args.repo or resolve_repo()
        items = collect(repo)
    except QueueCollectError as exc:
        print(f"collect_autopilot_queue: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps(items, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
