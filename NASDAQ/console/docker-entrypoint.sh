#!/bin/sh
# Clone the ledger repository on first start, then serve.
set -eu
REPO_DIR="$(dirname "${CONSOLE_PKG_DIR:-/data/repo/NASDAQ}")"
if [ ! -d "$REPO_DIR/.git" ]; then
  if [ -z "${CONSOLE_REPO_URL:-}" ]; then
    echo "CONSOLE_REPO_URL is not set and $REPO_DIR is not a git clone" >&2
    exit 1
  fi
  git clone --branch "${CONSOLE_REPO_BRANCH:-main}" --single-branch "$CONSOLE_REPO_URL" "$REPO_DIR"
fi
export HOME="${HOME:-/data}"
git config --global --add safe.directory "$REPO_DIR" || true
exec python -m uvicorn nafa_console.app:app --host 0.0.0.0 --port 8080 --proxy-headers --no-access-log
