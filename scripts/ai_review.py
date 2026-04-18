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

    # Claude CLI 2.x returns schema-validated JSON under 'structured_output'
    # when --json-schema is used. Older CLI versions embedded the JSON string
    # in 'result'. Support both.
    structured = payload.get("structured_output")
    if isinstance(structured, dict):
        parsed = structured
    else:
        result_text = payload.get("result")
        if not isinstance(result_text, str) or not result_text.strip():
            raise SystemExit(
                "Claude output did not include structured_output "
                "or a non-empty 'result' string."
            )
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


def summarize_text(text: str, limit: int = 400) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def classify_failure_text(text: str) -> tuple[str, str]:
    lowered = text.lower()

    if any(
        pattern in lowered
        for pattern in (
            "usage limit",
            "rate limit",
            "quota",
            "try again at",
            "credits remaining",
        )
    ):
        return (
            "quota",
            "AI 사용량 제한 또는 요금제 한도로 인해 리뷰 워커가 완료되지 못했습니다.",
        )

    if any(
        pattern in lowered
        for pattern in (
            "not logged in",
            "authentication",
            "please run /login",
            "login required",
            "auth token",
        )
    ):
        return (
            "auth_error",
            "AI CLI 인증이 만료되었거나 누락되어 리뷰 워커가 실행되지 못했습니다.",
        )

    if any(
        pattern in text
        for pattern in (
            (
                "Input must be provided either through stdin or as a prompt "
                "argument when using --print"
            ),
        )
    ) or any(
        pattern in lowered
        for pattern in (
            "unknown option",
            "invalid option",
            "missing required argument",
            "json schema",
            "schema validation",
        )
    ):
        return (
            "script_error",
            (
                "리뷰 워커 스크립트 또는 CLI 호출 방식에 오류가 있어 "
                "자동 리뷰를 시작하지 못했습니다."
            ),
        )

    return (
        "infra_error",
        (
            "리뷰 워커가 구조화된 결과를 남기기 전에 실패했습니다. "
            "Actions 로그를 확인해 주세요."
        ),
    )


def build_status_payload(
    *,
    engine: str,
    phase: str,
    state: str,
    approved: bool,
    failure_kind: str,
    message: str,
    review_output_available: bool,
    auto_fix_eligible: bool,
    raw_excerpt: str = "",
) -> dict:
    return {
        "engine": engine,
        "phase": phase,
        "state": state,
        "approved": approved,
        "failure_kind": failure_kind,
        "message": message.strip(),
        "review_output_available": review_output_available,
        "auto_fix_eligible": auto_fix_eligible,
        "raw_excerpt": raw_excerpt.strip(),
    }


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
    failure_kind: str = "",
    attempt: int | None = None,
    state: str = "",
    source_engines: list[str] | None = None,
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
    if failure_kind:
        metadata["failure_kind"] = failure_kind
    if attempt is not None:
        metadata["attempt"] = attempt
    if state:
        metadata["state"] = state
    if source_engines:
        metadata["source_engines"] = source_engines
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


def build_review_status(args: argparse.Namespace) -> int:
    data = load_review(args.input)
    approved = bool(data.get("approved"))
    status = build_status_payload(
        engine=args.engine,
        phase=args.phase,
        state="approved" if approved else "rejected",
        approved=approved,
        failure_kind="" if approved else "content",
        message=data.get("summary", ""),
        review_output_available=True,
        auto_fix_eligible=(args.phase == "pr" and not approved),
    )
    Path(args.output).write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n"
    )
    return 0


def classify_failure(args: argparse.Namespace) -> int:
    text = ""
    path = Path(args.input)
    if path.exists():
        text = path.read_text(errors="replace")

    failure_kind, message = classify_failure_text(text)
    status = build_status_payload(
        engine=args.engine,
        phase=args.phase,
        state="error",
        approved=False,
        failure_kind=failure_kind,
        message=message,
        review_output_available=False,
        auto_fix_eligible=False,
        raw_excerpt=summarize_text(text),
    )
    Path(args.output).write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n"
    )
    return 0


def analyze_fix_loop(args: argparse.Namespace) -> int:
    comments = json.loads(Path(args.comments).read_text())
    if not isinstance(comments, list):
        raise SystemExit("PR comments payload must be a JSON array.")

    attempts = 0
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        metadata = extract_comment_metadata(comment.get("body", ""))
        if not metadata:
            continue
        if metadata.get("engine") != "claude":
            continue
        if metadata.get("phase") != "pr":
            continue
        if metadata.get("stage") != "fix-completed":
            continue
        attempts += 1

    result = {
        "attempt_count": attempts,
        "threshold": args.threshold,
        "blocked": attempts >= args.threshold,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
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
            failure_kind="" if approved else "content",
        )
        lines.extend(
            [
                "",
                f"<!-- ai-review-meta: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))} -->",  # noqa: E501
            ]
        )
    elif args.stage == "error":
        status = json.loads(Path(args.status).read_text())
        failure_kind = status.get("failure_kind", "infra_error")
        emoji = "⚠️"
        lines.extend(
            [
                f"{emoji} **{phase_label} 실행 실패**",
                "- Verdict: `ERROR`",
                f"- 브랜치: `{args.head_ref}`",
            ]
        )
        if short_sha:
            lines.append(f"- HEAD: `{short_sha}`")
        lines.append(f"- Failure Kind: `{failure_kind}`")
        lines.append(f"- Summary: {status.get('message', '').strip()}")
        if status.get("raw_excerpt"):
            lines.append(f"- Raw: `{status.get('raw_excerpt')}`")
        if args.run_url:
            lines.append(f"- run: {args.run_url}")

        metadata = build_review_metadata(
            engine=args.engine,
            phase=args.phase,
            stage=args.stage,
            approved=False,
            titles=[],
            head_ref=args.head_ref,
            head_sha=args.head_sha,
            analysis=None,
            failure_kind=failure_kind,
        )
        lines.extend(
            [
                "",
                f"<!-- ai-review-meta: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))} -->",  # noqa: E501
            ]
        )
    elif args.stage == "fix-started":
        source_engines = [
            item.strip()
            for item in (args.source_engines or "").split(",")
            if item.strip()
        ]
        lines.extend(
            [
                "🔁 **Claude 재수정 시작**",
                f"- Attempt: `{args.attempt}/{args.threshold}`",
                f"- 브랜치: `{args.head_ref}`",
            ]
        )
        if short_sha:
            lines.append(f"- HEAD: `{short_sha}`")
        if source_engines:
            formatted = ", ".join(f"`{item}`" for item in source_engines)
            lines.append(f"- Trigger: {formatted}")
        if args.run_url:
            lines.append(f"- run: {args.run_url}")
    elif args.stage == "fix-completed":
        status = json.loads(Path(args.status).read_text())
        state = status.get("state", "unknown")
        emoji = "✅" if state == "pushed" else "⚠️"
        headline = "Claude 재수정 완료" if state == "pushed" else "Claude 재수정 종료"
        new_head_sha = status.get("new_head_sha") or args.head_sha
        new_short_sha = new_head_sha[:7] if new_head_sha else ""
        lines.extend(
            [
                f"{emoji} **{headline}**",
                f"- Attempt: `{args.attempt}/{args.threshold}`",
                f"- Result: `{state.upper()}`",
                f"- 브랜치: `{args.head_ref}`",
            ]
        )
        if new_short_sha:
            lines.append(f"- HEAD: `{new_short_sha}`")
        lines.append(f"- Summary: {status.get('message', '').strip()}")
        if args.run_url:
            lines.append(f"- run: {args.run_url}")

        metadata = build_review_metadata(
            engine="claude",
            phase="pr",
            stage="fix-completed",
            approved=False,
            titles=[],
            head_ref=args.head_ref,
            head_sha=new_head_sha,
            analysis=None,
            attempt=args.attempt,
            state=state,
        )
        lines.extend(
            [
                "",
                f"<!-- ai-review-meta: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))} -->",  # noqa: E501
            ]
        )
    elif args.stage == "fix-skipped":
        reason = args.reason or "infra_error"
        message = args.message.strip() if args.message else ""
        lines.extend(
            [
                "⏸️ **Claude 재수정 중단**",
                f"- 브랜치: `{args.head_ref}`",
            ]
        )
        if short_sha:
            lines.append(f"- HEAD: `{short_sha}`")
        if args.attempt and args.threshold:
            lines.append(f"- Attempt Budget: `{args.attempt}/{args.threshold}`")
        lines.append(f"- Reason: `{reason}`")
        if message:
            lines.append(f"- Summary: {message}")
        if args.run_url:
            lines.append(f"- run: {args.run_url}")

        metadata = build_review_metadata(
            engine="claude",
            phase="pr",
            stage="fix-skipped",
            approved=False,
            titles=[],
            head_ref=args.head_ref,
            head_sha=args.head_sha,
            analysis=None,
            failure_kind=reason,
            attempt=args.attempt if args.attempt else None,
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
        "--stage",
        required=True,
        choices=[
            "requested",
            "started",
            "completed",
            "error",
            "fix-started",
            "fix-completed",
            "fix-skipped",
        ],
    )
    p_issue_comment.add_argument("--engine", required=True, choices=["claude", "codex"])
    p_issue_comment.add_argument("--phase", required=True, choices=["branch", "pr"])
    p_issue_comment.add_argument("--head-ref", required=True)
    p_issue_comment.add_argument("--head-sha", default="")
    p_issue_comment.add_argument("--run-url", default="")
    p_issue_comment.add_argument("--input", default="")
    p_issue_comment.add_argument("--analysis", default="")
    p_issue_comment.add_argument("--status", default="")
    p_issue_comment.add_argument("--attempt", type=int, default=0)
    p_issue_comment.add_argument("--threshold", type=int, default=0)
    p_issue_comment.add_argument("--reason", default="")
    p_issue_comment.add_argument("--message", default="")
    p_issue_comment.add_argument("--source-engines", default="")
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

    p_status = sub.add_parser("build-review-status")
    p_status.add_argument("--engine", required=True, choices=["claude", "codex"])
    p_status.add_argument("--phase", required=True, choices=["branch", "pr"])
    p_status.add_argument("--input", required=True)
    p_status.add_argument("--output", required=True)
    p_status.set_defaults(func=build_review_status)

    p_classify = sub.add_parser("classify-failure")
    p_classify.add_argument("--engine", required=True, choices=["claude", "codex"])
    p_classify.add_argument("--phase", required=True, choices=["branch", "pr"])
    p_classify.add_argument("--input", required=True)
    p_classify.add_argument("--output", required=True)
    p_classify.set_defaults(func=classify_failure)

    p_fix = sub.add_parser("analyze-fix-loop")
    p_fix.add_argument("--comments", required=True)
    p_fix.add_argument("--threshold", required=True, type=int)
    p_fix.set_defaults(func=analyze_fix_loop)

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
