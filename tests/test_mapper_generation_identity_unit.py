"""BUG 1 regression: a read-only Mapper re-survey must not look like drift.

``_mapper_generation`` reads Mapper's content identity from
``.simplicio-loop/index-state.json``'s ``signature`` (``head`` + ``tree_hash``
only) so a later preflight can tell "the tree this run's mapper survey
pinned" from "the tree now". Two fields are deliberately excluded from that
identity because both were empirically observed to change across a
back-to-back, read-only Mapper re-survey of a completely unchanged tree
(``simplicio-loop orient`` re-run between ``prepare`` and ``wave``, e.g. the
host refreshing context before a retry):

* ``index-state.json``'s own ``updated_at`` -- Mapper rewrites this
  timestamp to "now" on *every* invocation, including a pure read-only one.
* ``signature.status_hash`` -- a hash of Mapper's own ``git status`` snapshot
  at survey time; Mapper's own scan writes timestamped bookkeeping under its
  own excluded output directory, and that housekeeping alone was observed to
  shift ``status_hash`` between two surveys with no tracked or working-tree
  file touched at all.

Folding either into the identity dict compared for equality turns every such
re-survey into a false "active attempt mapper generation changed" block.
"""
from __future__ import annotations

import json

from simplicio_loop import runner


def _write_index_state(repo, *, head="h1", tree_hash="t1", status_hash="s1", updated_at="2026-01-01T00:00:00Z"):
    simplicio_dir = repo / ".simplicio-loop"
    simplicio_dir.mkdir(parents=True, exist_ok=True)
    (simplicio_dir / "index-state.json").write_text(
        json.dumps({
            "schema": "simplicio.mapper.index-state/v1",
            "signature": {"head": head, "tree_hash": tree_hash, "status_hash": status_hash},
            "updated_at": updated_at,
        }),
        encoding="utf-8",
    )


def test_mapper_generation_identity_is_stable_across_a_reindex_with_the_same_content(tmp_path):
    """A rewrite of index-state.json that only bumps ``updated_at`` (the
    real-world effect of a read-only Mapper re-survey against an unchanged
    tree) must not change the generation identity the loop pins/compares.
    """
    _write_index_state(tmp_path, updated_at="2026-01-01T00:00:00Z")
    first = runner._mapper_generation(tmp_path)

    _write_index_state(tmp_path, updated_at="2026-01-01T00:05:00Z")
    second = runner._mapper_generation(tmp_path)

    assert first == second, (first, second)


def test_mapper_generation_identity_is_stable_across_status_hash_churn(tmp_path):
    """``status_hash`` alone changing (Mapper's own re-survey bookkeeping
    noise, observed empirically -- never a tracked/working-tree file) must
    not change the identity either.
    """
    _write_index_state(tmp_path, status_hash="s1")
    first = runner._mapper_generation(tmp_path)

    _write_index_state(tmp_path, status_hash="s2")
    second = runner._mapper_generation(tmp_path)

    assert first == second, (first, second)
    assert "status_hash" not in first


def test_mapper_generation_identity_changes_when_head_or_tree_hash_changes(tmp_path):
    """The identity must still change -- fail closed -- when Mapper's own
    ``head`` or ``tree_hash`` reflects a real content change.
    """
    _write_index_state(tmp_path, tree_hash="t1")
    first = runner._mapper_generation(tmp_path)

    _write_index_state(tmp_path, tree_hash="t2")
    second = runner._mapper_generation(tmp_path)
    assert first != second

    _write_index_state(tmp_path, head="h2", tree_hash="t1")
    third = runner._mapper_generation(tmp_path)
    assert third != first
