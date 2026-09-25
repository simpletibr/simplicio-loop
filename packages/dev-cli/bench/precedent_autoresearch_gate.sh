#!/usr/bin/env bash
# precedent_autoresearch_gate.sh — binary correctness gate for the #90 autoresearch run on
# simplicio/precedent.py::build_precedent_block(). Pre-existing, independent assertions (not
# written to match any particular mutation) plus ruff. Exit 0 = pass, anything else = reject.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

python3 -m pytest tests/python/test_mapping_retry_flow.py \
    -k "precedent or index_repo_skips_heavy_embedding" -q
pytest_rc=$?

ruff check simplicio/precedent.py
ruff_rc=$?

if [ $pytest_rc -ne 0 ] || [ $ruff_rc -ne 0 ]; then
    exit 1
fi
exit 0
