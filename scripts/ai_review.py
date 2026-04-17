#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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


def extract_issue_number_from_ref(ref: str) -> str:
    for pattern in (
        r"#(\d+)",
        r"(?:^|/)(\d+)(?:[-/]|$)",
    ):
        match = re.search(pattern, ref)
        if match:
            return match.group(1)
    return ""


def extract_issue(args: argparse.Namespace) -> int:
    issue_number = extract_issue_number_from_ref(args.head_ref)
    if issue_number:
        print(issue_number)
    return 0


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


def normalize_titles(titles: list[str]) -> list[str]:
    normalized = [title.strip() for title in titles if title and title.strip()]
    return sorted(dict.fromkeys(normalized))


def build_review_metadata(
    *,
    engine: str,
    phase: str,
    stage: str,
    approved: bool,
    titles: list[str],
    head_ref: str,
    head_sha: str,
    analysis: dict | None,
) -> dict:
    metadata = {
        "engine": engine,
        "phase": phase,
        "stage": stage,
        "approved": approved,
        "titles": normalize_titles(titles),
        "head_ref": head_ref,
        "head_sha": head_sha,
    }
    if analysis:
        metadata["failure_count"] = analysis.get("failure_count")
        metadata["threshold"] = analysis.get("threshold")
        metadata["same_title_streak"] = analysis.get("same_title_streak")
        metadata["blocked"] = analysis.get("blocked")
    return metadata


def extract_comment_metadata(body: str) -> dict | None:
    match = re.search(
        r"<!--\s*ai-review-meta:\s*(\{.*?\})\s*-->", body, flags=re.DOTALL
    )
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def analyze_review_loop(args: argparse.Namespace) -> int:
    comments = json.loads(Path(args.comments).read_text())
    if not isinstance(comments, list):
        raise SystemExit("Issue comments payload must be a JSON array.")

    current = load_review(args.input)
    current_titles = normalize_titles(
        [finding.get("title", "") for finding in current.get("blocking_findings") or []]
    )

    history: list[dict] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        metadata = extract_comment_metadata(comment.get("body", ""))
        if not metadata:
            continue
        if metadata.get("engine") != args.engine:
            continue
        if metadata.get("phase") != args.phase:
            continue
        if metadata.get("stage") != "completed":
            continue
        history.append(metadata)

    failures = [item for item in history if not item.get("approved")]
    approved = bool(current.get("approved"))
    failure_count = len(failures) + (0 if approved else 1)

    same_title_streak = 0
    if not approved and current_titles:
        same_title_streak = 1
        for item in reversed(failures):
            previous_titles = normalize_titles(item.get("titles") or [])
            if previous_titles == current_titles:
                same_title_streak += 1
            else:
                break

    blocked = (not approved) and failure_count >= args.threshold
    escalate = same_title_streak >= 3 or blocked

    result = {
        "failure_count": failure_count,
        "threshold": args.threshold,
        "same_title_streak": same_title_streak,
        "blocked": blocked,
        "escalate": escalate,
        "current_titles": current_titles,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def analysis_field(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.input).read_text())
    value = data.get(args.field)
    if isinstance(value, bool):
        print("true" if value else "false")
    elif value is None:
        print("")
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    else:
        print(value)
    return 0


def render_issue_comment(args: argparse.Namespace) -> int:
    phase_label = (
        "Codex 브랜치 리뷰"
        if args.phase == "branch"
        else f"{args.engine.capitalize()} PR 승인"
    )
    short_sha = args.head_sha[:7] if args.head_sha else ""
    lines: list[str] = []
    analysis = json.loads(Path(args.analysis).read_text()) if args.analysis else {}

    if args.stage == "requested":
        lines.extend(
            [
                "🤖 **Claude Code 리뷰 요청**",
                f"- 단계: {phase_label}",
                f"- 브랜치: `{args.head_ref}`",
            ]
        )
        if short_sha:
            lines.append(f"- HEAD: `{short_sha}`")
        lines.append("- 다음 단계: GitHub Actions가 리뷰를 시작합니다.")
        if args.run_url:
            lines.append(f"- run: {args.run_url}")
    elif args.stage == "started":
        lines.extend(
            [
                f"🧠 **{phase_label} 시작**",
                f"- 브랜치: `{args.head_ref}`",
            ]
        )
        if short_sha:
            lines.append(f"- HEAD: `{short_sha}`")
        if args.run_url:
            lines.append(f"- run: {args.run_url}")
    elif args.stage == "completed":
        data = load_review(args.input)
        approved = bool(data.get("approved"))
        verdict = "PASS" if approved else "FAIL"
        emoji = "✅" if approved else "❌"
        blocking = data.get("blocking_findings") or []
        followups = data.get("followups") or []
        titles = [finding.get("title", "").strip() for finding in blocking]

        lines.extend(
            [
                f"{emoji} **{phase_label} 완료**",
                f"- Verdict: `{verdict}`",
                f"- 브랜치: `{args.head_ref}`",
            ]
        )
        if short_sha:
            lines.append(f"- HEAD: `{short_sha}`")
        lines.append(f"- Summary: {data.get('summary', '').strip()}")
        if args.run_url:
            lines.append(f"- run: {args.run_url}")

        if not approved and analysis:
            failure_count = analysis.get("failure_count")
            threshold = analysis.get("threshold")
            same_title_streak = analysis.get("same_title_streak") or 0
            if failure_count and threshold:
                lines.append(f"- Failure Count: `{failure_count}/{threshold}`")
            if same_title_streak >= 2:
                lines.append(
                    f"- Repeat Pattern: 같은 blocking finding이 `{same_title_streak}`회 연속 반복됨"  # noqa: E501
                )
            if analysis.get("blocked"):
                lines.append(
                    "- Status: `blocked:review-loop` 라벨이 추가되었고 자동 브랜치 리뷰를 중단합니다."  # noqa: E501
                )
            elif analysis.get("escalate"):
                lines.append(
                    "- Escalation: 같은 차단 이슈가 반복되어 사람 확인이 필요합니다."
                )

        if blocking:
            lines.extend(["", "**Blocking Findings**"])
            for idx, finding in enumerate(blocking, start=1):
                title = finding.get("title", "").strip()
                details = finding.get("details", "").strip()
                files = ", ".join(finding.get("files") or [])
                lines.append(f"{idx}. **{title}**")
                if details:
                    lines.append(f"   - {details}")
                if files:
                    lines.append(f"   - Files: `{files}`")

        if followups:
            lines.extend(["", "**Follow-ups**"])
            for idx, item in enumerate(followups, start=1):
                lines.append(f"{idx}. {item}")

        metadata = build_review_metadata(
            engine=args.engine,
            phase=args.phase,
            stage=args.stage,
            approved=approved,
            titles=titles,
            head_ref=args.head_ref,
            head_sha=args.head_sha,
            analysis=analysis,
        )
        lines.extend(
            [
                "",
                f"<!-- ai-review-meta: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))} -->",  # noqa: E501
            ]
        )
    else:
        raise SystemExit(f"Unknown stage: {args.stage}")

    print("\n".join(lines).strip())
    return 0


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

    p_issue = sub.add_parser("extract-issue")
    p_issue.add_argument("--head-ref", required=True)
    p_issue.set_defaults(func=extract_issue)

    p_issue_comment = sub.add_parser("render-issue-comment")
    p_issue_comment.add_argument(
        "--stage", required=True, choices=["requested", "started", "completed"]
    )
    p_issue_comment.add_argument("--engine", required=True, choices=["claude", "codex"])
    p_issue_comment.add_argument("--phase", required=True, choices=["branch", "pr"])
    p_issue_comment.add_argument("--head-ref", required=True)
    p_issue_comment.add_argument("--head-sha", default="")
    p_issue_comment.add_argument("--run-url", default="")
    p_issue_comment.add_argument("--input", default="")
    p_issue_comment.add_argument("--analysis", default="")
    p_issue_comment.set_defaults(func=render_issue_comment)

    p_analyze = sub.add_parser("analyze-review-loop")
    p_analyze.add_argument("--comments", required=True)
    p_analyze.add_argument("--input", required=True)
    p_analyze.add_argument("--engine", required=True, choices=["claude", "codex"])
    p_analyze.add_argument("--phase", required=True, choices=["branch", "pr"])
    p_analyze.add_argument("--threshold", required=True, type=int)
    p_analyze.set_defaults(func=analyze_review_loop)

    p_field = sub.add_parser("analysis-field")
    p_field.add_argument("--input", required=True)
    p_field.add_argument("--field", required=True)
    p_field.set_defaults(func=analysis_field)

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
