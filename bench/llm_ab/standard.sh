#!/usr/bin/env bash
# bench/llm_ab/standard.sh -- thin wrapper around standard.py, the ONE
# canonical benchmark matrix command for every release. See
# bench/llm_ab/STANDARD.md for what the matrix covers and why.
#
# Usage:
#   SIMPLICIO_BENCH_KEYS=/path/to/keys.env bash bench/llm_ab/standard.sh
#   # or:
#   bash bench/llm_ab/standard.sh --keys-file /path/to/keys.env
#
# Never commit a keys.env file. Runs on the python/venv already on PATH --
# activate the venv you want measured before invoking this, same as run.py.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${HERE}/standard.py" "$@"
