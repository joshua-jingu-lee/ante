#!/bin/bash
set -euo pipefail

ENGINE="${1:?engine is required (claude|codex)}"
PHASE="${2:?phase is required (branch|pr)}"

WORKSPACE="${GITHUB_WORKSPACE:-$(pwd)}"
SCHEMA_PATH="$WORKSPACE/.github/review-output.schema.json"
TMP_DIR="$(mktemp -d)"
RAW_PATH="$TMP_DIR/raw.json"
RESULT_PATH="$TMP_DIR/result.json"
SUMMARY_PATH="$TMP_DIR/summary.md"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/actions-runners/bin/claude}"
CODEX_BIN="${CODEX_BIN:-$HOME/actions-runners/bin/codex}"

HEAD_REF="${HEAD_REF:-${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-$(git branch --show-current)}}}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
BASE_REF="${BASE_REF:-}"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

BASE_REF="$(
  python3 "$WORKSPACE/scripts/ai_review.py" detect-base \
    --head-ref "$HEAD_REF" \
    --default-branch "$DEFAULT_BRANCH" \
    --base-ref "$BASE_REF"
)"

BASE_SHORT="${BASE_REF#origin/}"
git fetch --no-tags origin "$BASE_SHORT" || true

if [[ "$PHASE" == "branch" ]]; then
  REVIEW_ROLE="$ENGINE branch reviewer"
  PHASE_GOAL="PR을 만들기 전 브랜치 단위 사전 리뷰"
else
  REVIEW_ROLE="$ENGINE PR approver"
  PHASE_GOAL="PR head SHA 기준 최종 승인 판정"
fi

PROMPT=$(cat <<EOF
You are the $REVIEW_ROLE for the ANTE repository.

Context:
- Workspace root: $WORKSPACE
- Phase: $PHASE
- Goal: $PHASE_GOAL
- Base ref: $BASE_REF
- Head ref: $HEAD_REF

Instructions:
1. Review the current checkout against $BASE_REF.
2. Focus only on blocking issues: correctness bugs, regressions, spec/contract violations, missing critical tests, security issues.
3. Use AGENTS.md, docs/architecture/README.md, docs/runbooks/07-review-gate.md, and relevant docs/specs for changed modules as the source of truth.
4. Do not modify files.
5. Approve only if there are zero blocking findings.
6. Return JSON that matches the provided schema exactly.

Helpful commands you may use:
- git diff --name-only $BASE_REF...HEAD
- git diff $BASE_REF...HEAD
- rg -n "pattern" path
- sed -n '1,200p' file
EOF
)

if [[ "$ENGINE" == "codex" ]]; then
  "$CODEX_BIN" exec \
    --cd "$WORKSPACE" \
    --sandbox read-only \
    --output-schema "$SCHEMA_PATH" \
    --output-last-message "$RESULT_PATH" \
    "$PROMPT"
elif [[ "$ENGINE" == "claude" ]]; then
  CLAUDE_SCHEMA="$(python3 - <<'PY' "$SCHEMA_PATH"
import json, sys
from pathlib import Path
print(json.dumps(json.loads(Path(sys.argv[1]).read_text()), separators=(",", ":")))
PY
)"
  # Feed the review prompt via stdin. `--add-dir` is variadic, so passing the
  # prompt positionally after it can be parsed as another directory instead of
  # the actual print-mode input.
  printf '%s' "$PROMPT" | "$CLAUDE_BIN" -p \
    --output-format json \
    --json-schema "$CLAUDE_SCHEMA" \
    --allowedTools "Bash(git *) Bash(rg *) Bash(cat *) Bash(sed *) Read Glob Grep" \
    --add-dir "$WORKSPACE" > "$RAW_PATH"
  python3 "$WORKSPACE/scripts/ai_review.py" extract-claude --input "$RAW_PATH" --output "$RESULT_PATH"
else
  echo "Unknown engine: $ENGINE" >&2
  exit 2
fi

python3 "$WORKSPACE/scripts/ai_review.py" render \
  --engine "$ENGINE" \
  --phase "$PHASE" \
  --input "$RESULT_PATH" > "$SUMMARY_PATH"

if [[ -n "${REVIEW_RESULT_PATH:-}" ]]; then
  cp "$RESULT_PATH" "$REVIEW_RESULT_PATH"
fi

if [[ -n "${REVIEW_SUMMARY_PATH:-}" ]]; then
  cp "$SUMMARY_PATH" "$REVIEW_SUMMARY_PATH"
fi

cat "$SUMMARY_PATH"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat "$SUMMARY_PATH" >> "$GITHUB_STEP_SUMMARY"
fi

APPROVED="false"
if python3 "$WORKSPACE/scripts/ai_review.py" check --input "$RESULT_PATH"; then
  APPROVED="true"
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "approved=$APPROVED"
    echo "base_ref=$BASE_REF"
  } >> "$GITHUB_OUTPUT"
fi

if [[ "$APPROVED" != "true" ]]; then
  exit 1
fi
