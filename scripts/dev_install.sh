#!/usr/bin/env bash
# Development workspace bootstrap for the monorepo (mapper + fast + dev-cli + loop).
#
# Creates ONE venv and installs the four in-repo packages editable, from their
# in-repo paths, in dependency order (mapper, fast, dev-cli, then loop) --
# so the loop always runs against its in-repo siblings, never a stale PyPI
# release of simplicio-mapper/simplicio-fast/simplicio-cli.
#
# Usage:
#   bash scripts/dev_install.sh [VENV_DIR]
#
# VENV_DIR defaults to .venv at the repo root. Re-running is safe (idempotent
# editable reinstall).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VENV_DIR="${1:-$REPO/.venv}"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "python3 is required." >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "creating venv at $VENV_DIR"
  "$PY" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
if [ ! -x "$VENV_PY" ]; then
  # Windows venv layout
  VENV_PY="$VENV_DIR/Scripts/python.exe"
fi

"$VENV_PY" -m pip install --upgrade pip >/dev/null

# Dependency order matters: fast/dev-cli/loop each expect the mapper contract
# and CLI to already be importable when THEIR own extras resolve.
"$VENV_PY" -m pip install -e "$REPO/packages/mapper[dev]"
"$VENV_PY" -m pip install -e "$REPO/packages/fast"
"$VENV_PY" -m pip install -e "$REPO/packages/dev-cli[dev]"
"$VENV_PY" -m pip install -e "$REPO[dev]"

echo
echo "monorepo dev workspace ready: $VENV_DIR"
echo "activate with: source $VENV_DIR/bin/activate"
echo "the loop now runs against the in-repo mapper/fast/dev-cli siblings, not a published release."
