#!/bin/bash
set -euo pipefail

PR_NUMBER="${PR_NUMBER:?PR_NUMBER is required}"
HEAD_REF="${HEAD_REF:?HEAD_REF is required}"
ATTEMPT="${ATTEMPT:?ATTEMPT is required}"
FIX_THRESHOLD="${FIX_THRESHOLD:-3}"

WORKSPACE="${GITHUB_WORKSPACE:-$(pwd)}"
TMP_DIR="$(mktemp -d)"
RAW_PATH="$TMP_DIR/claude-pr-fix-raw.json"
STATUS_PATH="${FIX_STATUS_PATH:-$TMP_DIR/claude-pr-fix-status.json}"
PROMPT_FILE="$TMP_DIR/claude-pr-fix-prompt.txt"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/actions-runners/bin/claude}"

CLAUDE_REVIEW_DIR="${CLAUDE_REVIEW_DIR:-}"
CODEX_REVIEW_DIR="${CODEX_REVIEW_DIR:-}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
BASE_REF="${BASE_REF:-origin/$DEFAULT_BRANCH}"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

copy_fix_artifacts() {
  if [[ -n "${FIX_RAW_PATH:-}" && -f "$RAW_PATH" && "$RAW_PATH" != "$FIX_RAW_PATH" ]]; then
    cp "$RAW_PATH" "$FIX_RAW_PATH"
  fi
}

write_fix_status() {
  local state="$1"
  local failure_kind="$2"
  local message="$3"
  local new_head_sha="${4:-}"

  python3 - "$STATUS_PATH" "$state" "$failure_kind" "$message" "$new_head_sha" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "state": sys.argv[2],
    "failure_kind": sys.argv[3],
    "message": sys.argv[4],
    "new_head_sha": sys.argv[5],
}
path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
PY
  copy_fix_artifacts
}

build_context() {
  local review_dir="$1"
  local label="$2"

  if [[ -z "$review_dir" || ! -f "$review_dir/status.json" ]]; then
    return 0
  fi

  local approved
  local failure_kind
  approved="$(python3 "$WORKSPACE/scripts/ai_review.py" analysis-field --input "$review_dir/status.json" --field approved)"
  failure_kind="$(python3 "$WORKSPACE/scripts/ai_review.py" analysis-field --input "$review_dir/status.json" --field failure_kind)"

  if [[ "$approved" == "true" || "$failure_kind" != "content" ]]; then
    return 0
  fi

  printf '\n--- %s approval findings ---\n' "$label"
  if [[ -f "$review_dir/summary.md" ]]; then
    cat "$review_dir/summary.md"
    printf '\n'
  else
    local message
    message="$(python3 "$WORKSPACE/scripts/ai_review.py" analysis-field --input "$review_dir/status.json" --field message)"
    printf '%s\n' "$message"
  fi
}

git fetch --no-tags origin "${BASE_REF#origin/}" || true

FAILURE_CONTEXT="$(
  {
    build_context "$CLAUDE_REVIEW_DIR" "Claude"
    build_context "$CODEX_REVIEW_DIR" "Codex"
  }
)"

cat > "$PROMPT_FILE" <<EOF
You are Claude Code acting as the PR repair worker for the ANTE repository.

Context:
- Workspace root: $WORKSPACE
- PR number: #$PR_NUMBER
- Attempt: $ATTEMPT/$FIX_THRESHOLD
- Base ref: $BASE_REF
- Head ref: $HEAD_REF

Goal:
Fix only the blocking findings from the failed PR approval checks below on the current branch.

Requirements:
1. Treat AGENTS.md, docs/architecture/README.md, docs/runbooks/07-review-gate.md, and relevant docs/specs as the source of truth.
2. Make the minimal code, test, generated-doc, and spec updates needed to resolve the blocking findings.
3. Do not widen scope beyond the reported blocking findings.
4. Run focused validation for the touched area when feasible, and keep the branch in a committable state.
5. Do not open or merge a PR yourself. Leave changes in the current branch so the workflow can commit and push them.

Failed approval summaries:
$FAILURE_CONTEXT
EOF

set +e
"$CLAUDE_BIN" -p \
  --output-format json \
  --allowedTools "Read Glob Grep Edit MultiEdit Write Bash(git status) Bash(git diff *) Bash(git add *) Bash(git commit *) Bash(git push *) Bash(rg *) Bash(cat *) Bash(sed *) Bash(pytest *) Bash(ruff *) Bash(mypy *) Bash(npm run build) Bash(python *)" \
  --add-dir "$WORKSPACE" \
  < "$PROMPT_FILE" > "$RAW_PATH"
CLAUDE_EXIT=$?
set -e

if [[ "$CLAUDE_EXIT" -ne 0 ]]; then
  python3 "$WORKSPACE/scripts/ai_review.py" classify-failure \
    --engine claude \
    --phase pr \
    --input "$RAW_PATH" \
    --output "$STATUS_PATH"
  copy_fix_artifacts
  exit 1
fi

set +e
python3 - "$RAW_PATH" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text())
except Exception:
    sys.exit(0)

if isinstance(data, dict) and data.get("is_error") is True:
    sys.exit(1)

sys.exit(0)
PY
IS_ERROR_EXIT=$?
set -e

if [[ "$IS_ERROR_EXIT" -ne 0 ]]; then
  python3 "$WORKSPACE/scripts/ai_review.py" classify-failure \
    --engine claude \
    --phase pr \
    --input "$RAW_PATH" \
    --output "$STATUS_PATH"
  copy_fix_artifacts
  exit 1
fi

if [[ -z "$(git status --short)" ]]; then
  write_fix_status \
    "no_changes" \
    "no_change" \
    "Claude 재수정 워커가 실행되었지만 추적된 파일 변경이 없어 새 커밋을 만들지 못했습니다. 수동 확인이 필요합니다."
  exit 1
fi

git config user.name "ante-claude-review[bot]"
git config user.email "ante-claude-review@users.noreply.github.com"

set +e
git add -A >> "$RAW_PATH" 2>&1
ADD_EXIT=$?
set -e
if [[ "$ADD_EXIT" -ne 0 ]]; then
  write_fix_status \
    "error" \
    "infra_error" \
    "Claude 재수정 결과를 staging하는 중 git add가 실패했습니다. Actions 로그를 확인해 주세요."
  exit 1
fi

if git diff --cached --quiet; then
  write_fix_status \
    "no_changes" \
    "no_change" \
    "Claude 재수정 워커가 실행되었지만 staging된 변경이 없어 새 커밋을 만들지 못했습니다. 수동 확인이 필요합니다."
  exit 1
fi

set +e
git commit -m "fix(review): address PR approval findings" >> "$RAW_PATH" 2>&1
COMMIT_EXIT=$?
set -e
if [[ "$COMMIT_EXIT" -ne 0 ]]; then
  write_fix_status \
    "error" \
    "infra_error" \
    "Claude 재수정 결과를 커밋하는 중 오류가 발생했습니다. Actions 로그를 확인해 주세요."
  exit 1
fi

set +e
git push origin "HEAD:$HEAD_REF" >> "$RAW_PATH" 2>&1
PUSH_EXIT=$?
set -e
if [[ "$PUSH_EXIT" -ne 0 ]]; then
  write_fix_status \
    "error" \
    "infra_error" \
    "Claude 재수정 커밋을 원격 브랜치로 push하지 못했습니다. Actions 로그를 확인해 주세요."
  exit 1
fi

NEW_HEAD_SHA="$(git rev-parse HEAD)"
write_fix_status \
  "pushed" \
  "" \
  "Claude가 blocking finding을 반영한 새 커밋을 push했고 PR 승인 체크가 다시 시작됩니다." \
  "$NEW_HEAD_SHA"
