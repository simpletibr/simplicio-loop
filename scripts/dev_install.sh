#!/usr/bin/env bash
# Development workspace bootstrap for the monorepo.
#
# Creates ONE venv and installs the root package editable. The Mapper and the Dev CLI
# are built into the single simplicio-loop distribution, so nothing is fetched from
# PyPI for them and the loop always runs against the in-repo sources.
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

# Cross-package build/test tooling that more than one package's own local
# gate needs at some point, installed once here so `scripts/check.py
# --package <name>` (or `--package all`) is runnable from a plain fresh venv
# with nothing else pre-installed on the machine:
#   - build/wheel/setuptools: `python -m build` (root package's install-smoke
#     test, `scripts/install_smoke.py`) and the mapper package's own
#     `python -m build --no-isolation` dist-frontier tests both need a real
#     PEP 517 front end + build backend already importable in THIS venv
#     (--no-isolation explicitly skips pip's normal isolated-build-env
#     fetch, so whatever backend a package declares under
#     [build-system].requires must already be installed here, not just
#     declared).
#   - hatchling: the mapper package's build backend (packages/mapper's own
#     [dev] extra below already lists it, but installing it explicitly here
#     too keeps this step self-describing and idempotent either way).
"$VENV_PY" -m pip install --upgrade build wheel setuptools "hatchling>=1.27,<1.33" >/dev/null

# One editable install: mapper + dev-cli are built into the root distribution.
"$VENV_PY" -m pip install -e "$REPO[dev]"
# Lint/type/property-test tooling the mapper and dev-cli gates use.
"$VENV_PY" -m pip install "ruff>=0.15,<0.17" "mypy>=1.19.1" "hypothesis>=6.100,<7" "pytest-cov>=6" "cryptography>=43,<51"

echo
echo "monorepo dev workspace ready: $VENV_DIR"
echo "activate with: source $VENV_DIR/bin/activate"
echo "mapper + dev-cli are part of the loop distribution; nothing is fetched from PyPI."
