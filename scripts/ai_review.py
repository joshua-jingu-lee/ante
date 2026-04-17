#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def detect_base(args: argparse.Namespace) -> int:
    if args.base_ref:
        print(normalize_ref(args.base_ref))
        return 0

    default_ref = normalize_ref(args.default_branch)
    head_ref = args.head_ref or run("git", "branch", "--show-current")

    if head_ref.startswith("epic/"):
        print(default_ref)
        return 0

    candidates: list[tuple[int, str]] = []
    refs = run(
        "git",
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/remotes/origin/epic",
    )
    for ref in [line.strip() for line in refs.splitlines() if line.strip()]:
        rc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ref, "HEAD"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if rc.returncode != 0:
            continue
        ahead = int(run("git", "rev-list", "--count", f"{ref}..HEAD"))
        candidates.append((ahead, ref))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        print(candidates[0][1])
        return 0

    print(default_ref)
    return 0


def normalize_ref(ref: str) -> str:
    if ref.startswith("origin/"):
        return ref
    return f"origin/{ref}"


def extract_claude(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text())
    result_text = payload.get("result")
    if not isinstance(result_text, str):
        raise SystemExit("Claude output did not include a string 'result' field.")

    try:
        parsed = json.loads(result_text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Claude result was not valid JSON: {exc}") from exc

    Path(args.output).write_text(json.dumps(parsed, indent=2) + "\n")
    return 0


def load_review(path: str) -> dict:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise SystemExit("Review output must be a JSON object.")
    return data


def render(args: argparse.Namespace) -> int:
    data = load_review(args.input)
    engine = args.engine.capitalize()
    phase = "branch review" if args.phase == "branch" else "PR approval"
    verdict = "PASS" if data.get("approved") else "FAIL"

    print(f"## {engine} {phase}")
    print(f"- Verdict: **{verdict}**")
    print(f"- Summary: {data.get('summary', '').strip()}")

    blocking = data.get("blocking_findings") or []
    followups = data.get("followups") or []

    if blocking:
        print("")
        print("### Blocking Findings")
        for idx, finding in enumerate(blocking, start=1):
            title = finding.get("title", "").strip()
            details = finding.get("details", "").strip()
            files = ", ".join(finding.get("files") or [])
            print(f"{idx}. **{title}**")
            print(f"   - {details}")
            if files:
                print(f"   - Files: `{files}`")

    if followups:
        print("")
        print("### Follow-ups")
        for idx, item in enumerate(followups, start=1):
            print(f"{idx}. {item}")

    return 0


def check(args: argparse.Namespace) -> int:
    data = load_review(args.input)
    approved = bool(data.get("approved"))
    blocking = data.get("blocking_findings") or []
    if approved and not blocking:
        return 0

    summary = data.get("summary", "").strip()
    if summary:
        print(summary, file=sys.stderr)
    for finding in blocking:
        print(f"- {finding.get('title', 'Blocking finding')}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect-base")
    p_detect.add_argument("--head-ref", default="")
    p_detect.add_argument("--default-branch", default="main")
    p_detect.add_argument("--base-ref", default="")
    p_detect.set_defaults(func=detect_base)

    p_extract = sub.add_parser("extract-claude")
    p_extract.add_argument("--input", required=True)
    p_extract.add_argument("--output", required=True)
    p_extract.set_defaults(func=extract_claude)

    p_render = sub.add_parser("render")
    p_render.add_argument("--engine", required=True, choices=["claude", "codex"])
    p_render.add_argument("--phase", required=True, choices=["branch", "pr"])
    p_render.add_argument("--input", required=True)
    p_render.set_defaults(func=render)

    p_check = sub.add_parser("check")
    p_check.add_argument("--input", required=True)
    p_check.set_defaults(func=check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
