#!/usr/bin/env bash
# simplicio-tasks installer (thin launcher → scripts/install_lib.py)
# Usage: bash scripts/install.sh <runtime> [--global] [--target DIR]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# A python that really runs: it prints its version, and that version is at least 3.11 (requires-python of pyproject.toml).
# A program that only prints an error fails the probe, so the next PATH match is tried.
usable() {
  local version major minor
  version="$("$1" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null)" || return 1
  major="${version%%.*}"
  minor="${version#*.}"
  case "$major.$minor" in *[!0-9.]* | . | "") return 1 ;; esac
  [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }
}

PY=""
while IFS= read -r candidate; do
  if usable "$candidate"; then
    PY="$candidate"
    break
  fi
done < <(type -ap python3 python 2>/dev/null || true)
if [ -z "$PY" ] && command -v uv >/dev/null 2>&1; then  # no usable Python on PATH: uv installs one in the user folder
  uv python install 3.11 >&2 || true
  candidate="$(uv python find 3.11 2>/dev/null || true)"
  if [ -n "$candidate" ] && usable "$candidate"; then PY="$candidate"; fi
fi
if [ -z "$PY" ]; then
  echo "No usable Python 3.11 or newer was found. Install one (for example: uv python install 3.11, or https://www.python.org/downloads/), open a new terminal, and run this installer again." >&2
  exit 1
fi
exec "$PY" "$DIR/install_lib.py" "$@"
