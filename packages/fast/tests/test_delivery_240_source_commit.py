from pathlib import Path

import simplicio_fast.delivery as delivery
from simplicio_fast.delivery import DeliveryEngine


def test_non_git_source_commit_discovery_is_cached(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def fake_source_commit(root: Path) -> tuple[str | None, str | None]:
        nonlocal calls
        calls += 1
        return None, "not_a_git_checkout"

    monkeypatch.setattr(delivery, "_source_commit", fake_source_commit)
    engine = DeliveryEngine(tmp_path, tmp_path / "snapshot.sfast")
    assert engine._source_commit_receipt() == (None, "not_a_git_checkout")
    assert engine._source_commit_receipt() == (None, "not_a_git_checkout")
    assert calls == 1
