#!/bin/bash
set -euo pipefail

REPO_SLUG="${1:-joshua-jingu-lee/ante}"
RUNNER_ROOT="${RUNNER_ROOT:-$HOME/actions-runners}"
TOOLS_DIR="$RUNNER_ROOT/bin"
ARCHIVE_DIR="$RUNNER_ROOT/_downloads"
REPO_URL="https://github.com/$REPO_SLUG"

mkdir -p "$RUNNER_ROOT" "$TOOLS_DIR" "$ARCHIVE_DIR"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need_cmd gh
need_cmd tar
need_cmd curl
need_cmd python3

CLAUDE_SRC="$(command -v claude)"
CODEX_SRC="$(command -v codex)"

ln -sf "$CLAUDE_SRC" "$TOOLS_DIR/claude"
ln -sf "$CODEX_SRC" "$TOOLS_DIR/codex"

LATEST_TAG="$(gh api repos/actions/runner/releases/latest --jq '.tag_name')"
VERSION="${LATEST_TAG#v}"
ARCHIVE_NAME="actions-runner-osx-arm64-$VERSION.tar.gz"
ARCHIVE_PATH="$ARCHIVE_DIR/$ARCHIVE_NAME"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/$LATEST_TAG/$ARCHIVE_NAME"

if [[ ! -f "$ARCHIVE_PATH" ]]; then
  curl -L "$DOWNLOAD_URL" -o "$ARCHIVE_PATH"
fi

configure_runner() {
  local runner_name="$1"
  local label="$2"
  local runner_dir="$RUNNER_ROOT/$runner_name"

  mkdir -p "$runner_dir"

  if [[ ! -f "$runner_dir/config.sh" ]]; then
    tar -xzf "$ARCHIVE_PATH" -C "$runner_dir"
  fi

  local token
  token="$(gh api -X POST "repos/$REPO_SLUG/actions/runners/registration-token" --jq '.token')"

  if [[ -f "$runner_dir/.runner" ]]; then
    echo "Runner $runner_name already configured; refreshing labels and settings"
  fi

  (
    cd "$runner_dir"
    ./config.sh \
      --unattended \
      --replace \
      --url "$REPO_URL" \
      --token "$token" \
      --name "$runner_name" \
      --labels "$label" \
      --work "_work"

    ./svc.sh install
    ./svc.sh start
    ./svc.sh status || true
  )
}

configure_runner "ante-claude-review" "claude-review"
configure_runner "ante-codex-review" "codex-review"

echo ""
echo "Installed runners under: $RUNNER_ROOT"
echo "Binaries:"
echo "  claude -> $TOOLS_DIR/claude"
echo "  codex  -> $TOOLS_DIR/codex"
